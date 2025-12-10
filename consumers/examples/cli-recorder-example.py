"""
CLI example: human-guided recording with SessionRecorder.

This script shows how to:

- Read a recorder config (see config/recorder.example.yml).
- Construct a Theseus ExplorationDriver and StateTracker.
- Wrap them in SessionRecorder.
- Let a human operator perform steps in the UI.
- Capture states and transitions compatible with Atlas.
- Export them as an Atlas bundle, either to filesystem or directly
  into an Atlas HTTP server.

This is meant as a reference / demo, not a production tool.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml  # Requires PyYAML

from common.models.transition import Action, ActionType
from theseus.core.exporter import Exporter, ExporterConfig
from theseus.core.state_tracker import StateTracker, StateTrackerConfig
from theseus.drivers.web.browser_session import WebBrowserSession
from theseus.recording.prompts import resolve_intent_from_phrase, suggest_intents_for_phrase
from theseus.recording.session_recorder import SessionRecorder
from consumers.sdk.client import AtlasClient, AtlasClientConfig, AtlasClientError


# --------------------------------------------------------------------------- #
# Config loading
# --------------------------------------------------------------------------- #


def load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if "recorder" not in data:
        raise SystemExit("Config root must contain a 'recorder' key")
    return data["recorder"]


# --------------------------------------------------------------------------- #
# Driver construction
# --------------------------------------------------------------------------- #


def build_driver(rec_cfg: Dict[str, Any]) -> WebBrowserSession:
    driver_cfg = rec_cfg.get("driver", {})
    driver_type = driver_cfg.get("type", "web")

    if driver_type != "web":
        raise SystemExit(
            f"cli-recorder-example currently only supports driver.type='web', "
            f"got '{driver_type}'"
        )

    web_cfg = driver_cfg.get("web", {})
    start_url = web_cfg.get("start_url") or "about:blank"
    browser = web_cfg.get("browser") or "firefox"
    options = web_cfg.get("options") or {}

    # WebBrowserSession is expected to implement ExplorationDriver
    # (reset(), capture_state(), list_actions(), perform_action()).
    return WebBrowserSession(
        start_url=start_url,
        browser=browser,
        options=options,
    )


# --------------------------------------------------------------------------- #
# Tracker & recorder construction
# --------------------------------------------------------------------------- #


def build_tracker(rec_cfg: Dict[str, Any]) -> StateTracker:
    tracker_cfg = rec_cfg.get("tracker", {}) or {}

    st_cfg = StateTrackerConfig(
        prefer_fingerprint_keys=tracker_cfg.get("prefer_fingerprint_keys", ["structural", "semantic"]),
        allow_id_fallback=bool(tracker_cfg.get("allow_id_fallback", True)),
        auto_generate_ids=bool(tracker_cfg.get("auto_generate_ids", True)),
    )
    return StateTracker(st_cfg)


def build_recorder(
    rec_cfg: Dict[str, Any],
    driver: WebBrowserSession,
    tracker: StateTracker,
) -> SessionRecorder:
    session_cfg = rec_cfg.get("session", {}) or {}

    author = session_cfg.get("author")
    default_intent_id = session_cfg.get("default_intent_id")
    base_metadata = session_cfg.get("base_metadata") or {}

    return SessionRecorder(
        driver=driver,
        state_tracker=tracker,
        author=author,
        default_intent_id=default_intent_id,
        base_metadata=base_metadata,
    )


# --------------------------------------------------------------------------- #
# Intent helpers (CLI-facing)
# --------------------------------------------------------------------------- #


def cli_resolve_intent(text: str, *, suggest: bool) -> Optional[str]:
    """
    Given a free-text description, resolve an intent_id for this step.

    Returns:
        intent_id (str) or None.

    This uses the registry in common.models.intents via prompts helpers.
    """
    text = (text or "").strip()
    if not text:
        return None

    intent = resolve_intent_from_phrase(text)
    if intent is not None:
        print(f"  → matched intent: {intent.id!r} ({intent.label})")
        return intent.id

    if not suggest:
        return None

    suggestions = suggest_intents_for_phrase(text, limit=5)
    if not suggestions:
        print("  → no intent suggestions found")
        return None

    print("  → intent suggestions:")
    for idx, s in enumerate(suggestions, start=1):
        print(f"    [{idx}] {s.intent.id} — {s.intent.label} ({s.match_hint}, score={s.score:.2f})")

    while True:
        raw = input("Select intent index (or press Enter for none): ").strip()
        if not raw:
            return None
        try:
            idx = int(raw)
        except ValueError:
            print("  Invalid number, try again.")
            continue
        if 1 <= idx <= len(suggestions):
            chosen = suggestions[idx - 1].intent
            print(f"  → chosen intent: {chosen.id!r} ({chosen.label})")
            return chosen.id
        print("  Index out of range, try again.")


# --------------------------------------------------------------------------- #
# Export helpers
# --------------------------------------------------------------------------- #


def build_exporter(rec_cfg: Dict[str, Any], tracker: StateTracker) -> Exporter:
    app_cfg = rec_cfg.get("app", {}) or {}
    env_metadata = {
        "source": "human_recorder",
        "tool": "cli-recorder-example",
    }

    exp_cfg = ExporterConfig(
        app_id=app_cfg.get("app_id") or "unknown-app",
        version=app_cfg.get("version"),
        platform=app_cfg.get("platform"),
        locale=app_cfg.get("locale"),
        environment={},
        metadata=env_metadata,
    )
    return Exporter(state_tracker=tracker, config=exp_cfg)


def export_to_filesystem(
    bundle: Dict[str, Any],
    rec_cfg: Dict[str, Any],
    session_id: str,
) -> None:
    out_cfg = rec_cfg.get("output", {}).get("filesystem", {}) or {}
    base_dir = Path(out_cfg.get("output_dir") or "./output/recordings")
    use_ts = bool(out_cfg.get("use_timestamp_subdirs", True))

    if use_ts:
        ts = time.strftime("%Y%m%d-%H%M%S")
        base_dir = base_dir / ts

    base_dir.mkdir(parents=True, exist_ok=True)

    path = base_dir / f"bundle-{session_id}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2, sort_keys=True)

    print(f"[export] wrote bundle to {path}")


def export_to_atlas(
    bundle: Dict[str, Any],
    rec_cfg: Dict[str, Any],
) -> None:
    atlas_cfg = rec_cfg.get("output", {}).get("atlas", {}) or {}
    base_url = atlas_cfg.get("base_url") or "http://localhost:8080"
    api_key = atlas_cfg.get("api_key")
    timeout = int(atlas_cfg.get("timeout", 10))

    client_cfg = AtlasClientConfig(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        api_key_header="X-API-Key",
    )
    client = AtlasClient(client_cfg)

    try:
        result = client.ingest_bundle(bundle)
    except AtlasClientError as exc:
        print(f"[export] Atlas ingest failed: {exc}", file=sys.stderr)
        return

    print("[export] Atlas ingest result:")
    print(json.dumps(result, indent=2, sort_keys=True))


# --------------------------------------------------------------------------- #
# CLI interaction
# --------------------------------------------------------------------------- #


def run_interactive(rec_cfg: Dict[str, Any]) -> None:
    driver = build_driver(rec_cfg)
    tracker = build_tracker(rec_cfg)
    recorder = build_recorder(rec_cfg, driver, tracker)

    prompts_cfg = rec_cfg.get("prompts", {}) or {}
    ask_intent_per_step = bool(prompts_cfg.get("ask_intent_per_step", True))
    suggest_intents = bool(prompts_cfg.get("suggest_intents", True))

    # Reset driver and capture initial state
    print("[session] resetting driver...")
    driver.reset()

    print("[session] capturing initial state...")
    initial_state = recorder.begin()
    print(f"[session] session_id={recorder.session_id}")
    print(f"[session] initial state id: {initial_state.id}")

    step_index = 0

    while True:
        print()
        print(f"--- Step {step_index} ---")
        print("Perform the next action in the UI, then describe it.")
        print("Enter an empty action type to finish recording.")

        raw_type = input(
            "Action type [click/key/text_input/navigation/scroll/other]: "
        ).strip()
        if not raw_type:
            print("[session] recording finished by user.")
            break

        raw_type_norm = raw_type.lower()
        type_map = {
            "click": ActionType.CLICK,
            "key": ActionType.KEY,
            "text_input": ActionType.TEXT_INPUT,
            "text": ActionType.TEXT_INPUT,
            "navigation": ActionType.NAVIGATION,
            "nav": ActionType.NAVIGATION,
            "scroll": ActionType.SCROLL,
            "other": ActionType.OTHER,
        }
        action_type = type_map.get(raw_type_norm, ActionType.OTHER)

        element_id = input("Element id (optional): ").strip() or None
        raw_input_val: Optional[str] = None
        if action_type in (ActionType.KEY, ActionType.TEXT_INPUT):
            raw_input_val = input("Text/keys entered (optional, will be stored as metadata): ").strip() or None

        action = Action(
            type=action_type,
            element_id=element_id,
            raw_input=raw_input_val,
            metadata={},
        )

        intent_id: Optional[str] = None
        if ask_intent_per_step:
            desc = input("What were you trying to do? (free text, optional): ").strip()
            if desc:
                intent_id = cli_resolve_intent(desc, suggest=suggest_intents)

        # Let the human perform the action and then confirm
        input("Press Enter AFTER you have performed this action in the UI...")

        # Capture the new state explicitly to keep the flow obvious
        next_state = driver.capture_state()

        step = recorder.record_step(
            action,
            intent_id=intent_id,
            next_state=next_state,
        )

        print(
            f"[step] recorded transition {step.transition_id!r} "
            f"{step.source_state_id} -> {step.target_state_id}"
        )
        step_index += 1

    # Export
    exporter = build_exporter(rec_cfg, tracker)
    bundle = exporter.build_bundle()

    output_cfg = rec_cfg.get("output", {}) or {}
    mode = (output_cfg.get("mode") or "atlas").lower()

    if mode == "filesystem":
        export_to_filesystem(bundle, rec_cfg, recorder.session_id)
    elif mode == "atlas":
        export_to_atlas(bundle, rec_cfg)
    else:
        print(f"[export] unknown output.mode={mode!r}, skipping export.")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Human-guided recorder example for Ariane / Theseus."
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config/recorder.example.yml"),
        help="Path to recorder YAML config (default: config/recorder.example.yml)",
    )

    args = parser.parse_args(argv)

    rec_cfg = load_config(args.config)
    run_interactive(rec_cfg)


if __name__ == "__main__":
    main()
