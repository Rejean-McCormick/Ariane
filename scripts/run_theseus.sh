#!/usr/bin/env bash
#
# scripts/run_theseus.sh
#
# Example runner for a Theseus scan, driven by YAML config.
#
# Notes:
#   - Requires Python 3 and PyYAML (`pip install pyyaml`).
#   - Requires you to provide a driver factory via THESEUS_DRIVER_FACTORY:
#
#       export THESEUS_DRIVER_FACTORY="myproject.drivers.firefox:make_driver"
#       ./scripts/run_theseus.sh
#
#     where `make_driver()` returns an object implementing ExplorationDriver.
#
#   - Reads config from:
#       config/theseus.yml          (if present), otherwise
#       config/theseus.example.yml
#
#   - Output behavior (filesystem vs Atlas) is controlled by `output.mode`
#     in the YAML config (see config/theseus.example.yml).
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------------------
# Config file resolution
# ---------------------------------------------------------------------------

CONFIG_FILE="${THESEUS_CONFIG:-"$REPO_ROOT/config/theseus.yml"}"

if [ ! -f "$CONFIG_FILE" ]; then
  CONFIG_FILE="$REPO_ROOT/config/theseus.example.yml"
fi

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Error: no Theseus config file found." >&2
  echo "Looked for:" >&2
  echo "  - $REPO_ROOT/config/theseus.yml" >&2
  echo "  - $REPO_ROOT/config/theseus.example.yml" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Driver factory
# ---------------------------------------------------------------------------

# Must be of the form "module.path:factory_name"
# Example:
#   export THESEUS_DRIVER_FACTORY="myproject.drivers.firefox:make_driver"
DRV_FACTORY_STRING="${THESEUS_DRIVER_FACTORY:-}"

if [ -z "$DRV_FACTORY_STRING" ]; then
  cat >&2 <<EOF
Error: THESEUS_DRIVER_FACTORY is not set.

You must provide a factory that constructs an ExplorationDriver instance, e.g.:

  export THESEUS_DRIVER_FACTORY="myproject.drivers.firefox:make_driver"

where the module defines:

  from theseus.core.exploration_engine import ExplorationDriver

  def make_driver() -> ExplorationDriver:
      ...

EOF
  exit 1
fi

export THESEUS_CONFIG_PATH="$CONFIG_FILE"
export THESEUS_DRIVER_FACTORY="$DRV_FACTORY_STRING"

# ---------------------------------------------------------------------------
# Run embedded Python
# ---------------------------------------------------------------------------

PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}" python - << 'PYCODE'
import importlib
import os
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import yaml  # type: ignore[import]
except ImportError:  # pragma: no cover - runtime check
    print("Error: PyYAML is required. Install with:", file=sys.stderr)
    print("  pip install pyyaml", file=sys.stderr)
    sys.exit(1)

from common.models.ui_state import Platform
from theseus.pipelines.simple_scan import SimpleScanConfig, run_simple_scan
from theseus.pipelines.sandbox_tools import FileSink, FileSinkConfig
from consumers.sdk.client import AtlasClient, AtlasClientConfig

CONFIG_PATH = Path(os.environ["THESEUS_CONFIG_PATH"])
DRV_FACTORY_STRING = os.environ["THESEUS_DRIVER_FACTORY"]

# ---------------------------------------------------------------------------
# Load YAML config
# ---------------------------------------------------------------------------

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    root_cfg: Dict[str, Any] = yaml.safe_load(f) or {}

if "theseus" not in root_cfg:
    print(f"Error: root key 'theseus' not found in {CONFIG_PATH}", file=sys.stderr)
    sys.exit(1)

cfg = root_cfg["theseus"] or {}

app_cfg = cfg.get("app", {}) or {}
explore_cfg = cfg.get("exploration", {}) or {}
output_cfg = cfg.get("output", {}) or {}

# ---------------------------------------------------------------------------
# Map app / exploration config → SimpleScanConfig
# ---------------------------------------------------------------------------

app_id = app_cfg.get("app_id")
if not app_id:
    print("Error: theseus.app.app_id is required in config.", file=sys.stderr)
    sys.exit(1)

version = app_cfg.get("version")
platform_str = app_cfg.get("platform")
locale = app_cfg.get("locale")

platform = None
if platform_str:
    # Map simple string to Platform enum if possible, otherwise leave as None
    s = str(platform_str).strip().lower()
    try:
        platform = Platform(s)
    except ValueError:
        # best-effort: treat unknown as OTHER
        platform = Platform.OTHER

scan_config = SimpleScanConfig(
    app_id=app_id,
    version=version,
    platform=platform,
    locale=locale,
    max_depth=explore_cfg.get("max_depth"),
    max_states=explore_cfg.get("max_states"),
    max_transitions=explore_cfg.get("max_transitions"),
    skip_on_error=bool(explore_cfg.get("skip_on_error", True)),
    log_actions=bool(explore_cfg.get("log_actions", True)),
    environment={},
    metadata={},
)

# ---------------------------------------------------------------------------
# Resolve driver factory
# ---------------------------------------------------------------------------

def load_driver_factory(spec: str):
    """
    Load a factory callable from 'module.path:factory_name'.
    """
    if ":" not in spec:
        raise ValueError(f"Invalid THESEUS_DRIVER_FACTORY value: {spec!r}")
    mod_name, func_name = spec.split(":", 1)
    module = importlib.import_module(mod_name)
    factory = getattr(module, func_name, None)
    if factory is None:
        raise AttributeError(f"Factory {func_name!r} not found in module {mod_name!r}")
    return factory

try:
    driver_factory = load_driver_factory(DRV_FACTORY_STRING)
except Exception as exc:  # noqa: BLE001
    print(f"Error loading driver factory {DRV_FACTORY_STRING!r}: {exc}", file=sys.stderr)
    sys.exit(1)

driver = driver_factory()

# ---------------------------------------------------------------------------
# Run scan
# ---------------------------------------------------------------------------

print(f"Running Theseus scan for app_id={scan_config.app_id!r} using config {CONFIG_PATH}")
scan_result = run_simple_scan(driver=driver, config=scan_config, tracker_config=None)

print(f"Exploration finished: context_id={scan_result.context.context_id}")
print(f"  states:      {len(scan_result.bundle.get('states', []))}")
print(f"  transitions: {len(scan_result.bundle.get('transitions', []))}")

# ---------------------------------------------------------------------------
# Output handling
# ---------------------------------------------------------------------------

mode = (output_cfg.get("mode") or "filesystem").strip().lower()

if mode == "filesystem":
    fs_cfg = output_cfg.get("filesystem", {}) or {}
    output_dir = Path(fs_cfg.get("output_dir") or "./out/theseus")
    use_ts = bool(fs_cfg.get("use_timestamp_subdirs", True))

    sink = FileSink(
        config=FileSinkConfig(
            output_dir=output_dir,
            use_timestamp_subdirs=use_ts,
            bundle_filename="atlas_bundle.json",
            metadata_filename="scan_metadata.json",
        )
    )
    run_dir = sink.write(scan_result)
    print(f"Wrote bundle + metadata to: {run_dir}")

elif mode == "atlas":
    atlas_cfg = output_cfg.get("atlas", {}) or {}
    base_url = atlas_cfg.get("base_url") or "http://localhost:8080"
    api_key = atlas_cfg.get("api_key")
    timeout = int(atlas_cfg.get("timeout") or 10)

    client = AtlasClient(
        AtlasClientConfig(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
    )
    print(f"Posting bundle to Atlas at {base_url} ...")
    resp = client.ingest_bundle(scan_result.bundle)
    print("Atlas response:")
    print(resp)

else:
    print(f"Warning: unknown output.mode={mode!r}; no output written.", file=sys.stderr)

PYCODE
