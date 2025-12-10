"""
CLI example for the Guidance Client.

This example shows how to:

- Connect to an Atlas HTTP API via the AtlasClient.
- Select a context and a pair of states (current + target).
- Build a guidance session using the GuidanceEngine.
- Walk through the steps in a simple text-only CLI.

NOTE:
- This example does NOT probe a real UI. Instead, it assumes you
  know the current_state_id and target_state_id in a given context.
- It constructs a synthetic LocalUISnapshot using the fingerprints
  of the chosen "current" state so that matching is trivial.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from consumers.guidance import (
    GoalType,
    GuidanceGoal,
    GuidanceEngine,
    GuidanceEngineConfig,
    GuidanceStepKind,
    LocalUISnapshot,
    NullProbe,
)
from consumers.sdk.client import AtlasClient
from consumers.sdk.types import StateView


def _select_state_by_id(states, state_id: str) -> Optional[StateView]:
    for st in states:
        if getattr(st, "state_id", None) == state_id:
            return st
    return None


def run_cli(
    base_url: str,
    context_id: str,
    current_state_id: str,
    target_state_id: str,
) -> int:
    # 1) Set up Atlas client and fetch context/states.
    client = AtlasClient(base_url=base_url)

    ctx = client.get_context(context_id)
    if ctx is None:
        print(f"[error] Context '{context_id}' not found.", file=sys.stderr)
        return 1

    states = client.list_states(context_id)
    if not states:
        print(f"[error] No states found in context '{context_id}'.", file=sys.stderr)
        return 1

    current_state = _select_state_by_id(states, current_state_id)
    if current_state is None:
        print(
            f"[error] Current state '{current_state_id}' not found in context '{context_id}'.",
            file=sys.stderr,
        )
        return 1

    # 2) Synthesize a LocalUISnapshot from the current state's fingerprints.
    #    This lets the matching logic trivially resolve the current state.
    fingerprints = dict(getattr(current_state, "fingerprints", {}) or {})

    snapshot = LocalUISnapshot(
        context_hint=context_id,
        fingerprints=fingerprints,
        elements=[],
        metadata={
            "source": "cli-guidance-example",
            "current_state_id": current_state_id,
        },
    )

    # 3) Create a NullProbe (not actually used, since we pass snapshots explicitly).
    probe = NullProbe()

    # 4) Build the guidance engine.
    engine_config = GuidanceEngineConfig()
    engine = GuidanceEngine(client=client, probe=probe, config=engine_config)

    # 5) Define the goal: reach target_state_id.
    goal = GuidanceGoal(
        goal_type=GoalType.TARGET_STATE,
        target_state_id=target_state_id,
        label=f"Reach state {target_state_id}",
    )

    # 6) Start a session using the synthetic snapshot.
    session = engine.start_session(context_id=context_id, goal=goal, snapshot=snapshot)

    print("=== Ariane Guidance CLI Example ===")
    print(f"Atlas base URL : {base_url}")
    print(f"Context        : {context_id}")
    print(f"Current state  : {current_state_id}")
    print(f"Target state   : {target_state_id}")
    print(f"Plan status    : {session.plan.status.value}")
    print()

    if not session.plan.steps:
        print("[info] The plan has no steps (possibly already at target).")
        print(f"Session status: {session.status.value}")
        return 0

    # 7) Walk through the guidance steps interactively.
    while True:
        step = session.current_step()

        # If there is no current step (e.g. completed), break.
        if step is None:
            if session.is_finished():
                print(f"[done] Session finished with status: {session.status.value}")
                break
            else:
                print("[info] No current step but session is not terminal; stopping.")
                break

        print(f"--- Step {step.step_index + 1} / {step.step_count} ---")
        print(f"Kind       : {step.kind.value}")
        print(f"Instruction: {step.instruction}")

        if step.notes:
            print(f"Notes      : {step.notes}")

        if step.element_hint is not None:
            hint = step.element_hint
            print("Element hint:")
            print(f"  id    : {getattr(hint, 'element_id', None)}")
            print(f"  role  : {hint.role}")
            print(f"  label : {hint.label}")
            if hint.bounding_box is not None:
                bb = hint.bounding_box
                print(f"  bbox  : x={bb.x}, y={bb.y}, w={bb.width}, h={bb.height}")

        print()

        # If this is an ERROR or COMPLETE step, we stop immediately.
        if step.kind in (GuidanceStepKind.ERROR, GuidanceStepKind.COMPLETE):
            print(f"[terminal] Reached {step.kind.value} step. Stopping.")
            break

        user_input = input("Press [Enter] once you've completed this step (or 'q' to quit): ").strip()
        if user_input.lower() == "q":
            print("[info] User requested quit. Ending session.")
            break

        session = engine.advance_session(session)

        if session.is_finished():
            print(f"[done] Session finished with status: {session.status.value}")
            break

    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="CLI example for Ariane guidance client."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the Atlas HTTP API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--context-id",
        required=True,
        help="Context ID to use for guidance.",
    )
    parser.add_argument(
        "--current-state-id",
        required=True,
        help="State ID that represents the current UI state.",
    )
    parser.add_argument(
        "--target-state-id",
        required=True,
        help="State ID that represents the target UI state.",
    )

    args = parser.parse_args(argv)

    try:
        return run_cli(
            base_url=args.base_url,
            context_id=args.context_id,
            current_state_id=args.current_state_id,
            target_state_id=args.target_state_id,
        )
    except KeyboardInterrupt:
        print("\n[info] Interrupted by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
