#!/usr/bin/env bash
#
# scripts/run_atlas.sh
#
# Start the Atlas HTTP server using YAML configuration.
#
# - Requires Python 3 and PyYAML: `pip install pyyaml`
# - Reads config from:
#       config/atlas.yml            (if present), otherwise
#       config/atlas.example.yml
# - Optionally reads logging config from:
#       config/logging.yml          (if present), otherwise
#       config/logging.example.yml
#
# The YAML structure is described in config/atlas.example.yml.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------------------
# Config file resolution
# ---------------------------------------------------------------------------

ATLAS_CONFIG_FILE="${ATLAS_CONFIG:-"$REPO_ROOT/config/atlas.yml"}"
if [ ! -f "$ATLAS_CONFIG_FILE" ]; then
  ATLAS_CONFIG_FILE="$REPO_ROOT/config/atlas.example.yml"
fi

if [ ! -f "$ATLAS_CONFIG_FILE" ]; then
  echo "Error: no Atlas config file found." >&2
  echo "Looked for:" >&2
  echo "  - $REPO_ROOT/config/atlas.yml" >&2
  echo "  - $REPO_ROOT/config/atlas.example.yml" >&2
  exit 1
fi

LOGGING_CONFIG_FILE=""
if [ -f "$REPO_ROOT/config/logging.yml" ]; then
  LOGGING_CONFIG_FILE="$REPO_ROOT/config/logging.yml"
elif [ -f "$REPO_ROOT/config/logging.example.yml" ]; then
  LOGGING_CONFIG_FILE="$REPO_ROOT/config/logging.example.yml"
fi

export ATLAS_CONFIG_PATH="$ATLAS_CONFIG_FILE"
export ATLAS_LOGGING_CONFIG_PATH="$LOGGING_CONFIG_FILE"

# ---------------------------------------------------------------------------
# Run embedded Python
# ---------------------------------------------------------------------------

PYTHONPATH="$REPO_ROOT:${PYTHONPATH:-}" python - << 'PYCODE'
import os
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import yaml  # type: ignore[import]
except ImportError:  # pragma: no cover
    print("Error: PyYAML is required. Install with:", file=sys.stderr)
    print("  pip install pyyaml", file=sys.stderr)
    sys.exit(1)

import logging
import logging.config

from atlas.api.http_server import run_server
from atlas.api.auth import AuthConfig, Principal
from atlas.storage.graph_store import GraphStoreConfig

# ---------------------------------------------------------------------------
# Load logging config (if any)
# ---------------------------------------------------------------------------

log_cfg_path = os.environ.get("ATLAS_LOGGING_CONFIG_PATH") or ""
if log_cfg_path:
    p = Path(log_cfg_path)
    if p.is_file():
        with p.open("r", encoding="utf-8") as f:
            log_cfg = yaml.safe_load(f) or {}
        logging.config.dictConfig(log_cfg)
    else:
        logging.basicConfig(level=logging.INFO)
else:
    logging.basicConfig(level=logging.INFO)

LOG = logging.getLogger("atlas.run_atlas")

# ---------------------------------------------------------------------------
# Load Atlas config
# ---------------------------------------------------------------------------

cfg_path = Path(os.environ["ATLAS_CONFIG_PATH"])
with cfg_path.open("r", encoding="utf-8") as f:
    root_cfg: Dict[str, Any] = yaml.safe_load(f) or {}

if "atlas" not in root_cfg:
    print(f"Error: root key 'atlas' not found in {cfg_path}", file=sys.stderr)
    sys.exit(1)

cfg = root_cfg["atlas"] or {}

server_cfg = cfg.get("server", {}) or {}
storage_cfg = cfg.get("storage", {}) or {}
auth_cfg = cfg.get("auth", {}) or {}

host = server_cfg.get("host", "0.0.0.0")
port = int(server_cfg.get("port", 8080))

# ---------------------------------------------------------------------------
# GraphStoreConfig (storage)
# ---------------------------------------------------------------------------

gcfg = GraphStoreConfig(
    max_contexts=storage_cfg.get("max_contexts"),
    max_states_per_context=storage_cfg.get("max_states_per_context"),
    max_transitions_per_context=storage_cfg.get("max_transitions_per_context"),
)

# ---------------------------------------------------------------------------
# AuthConfig
# ---------------------------------------------------------------------------

auth_enabled = bool(auth_cfg.get("enabled", False))
auth_header_name = auth_cfg.get("header_name", "X-API-Key")
auth_optional = bool(auth_cfg.get("optional", False))

principals: Dict[str, Principal] = {}
api_keys_cfg = auth_cfg.get("api_keys") or {}

for api_key, meta in api_keys_cfg.items():
    if not isinstance(meta, dict):
        continue
    principal_id = meta.get("id") or api_key
    scopes = list(meta.get("scopes") or [])
    metadata = dict(meta.get("metadata") or {})
    principals[api_key] = Principal(
        id=principal_id,
        scopes=scopes,
        metadata=metadata,
    )

auth_config = AuthConfig(
    enabled=auth_enabled,
    header_name=auth_header_name,
    optional=auth_optional,
    api_keys=principals,
) if auth_enabled else None

# ---------------------------------------------------------------------------
# Run server
# ---------------------------------------------------------------------------

LOG.info(
    "Starting Atlas HTTP server on %s:%d (config: %s)",
    host,
    port,
    cfg_path,
)

try:
    run_server(
        host=host,
        port=port,
        graph_config=gcfg,
        auth_config=auth_config,
    )
except KeyboardInterrupt:
    LOG.info("Atlas server stopped by user.")
PYCODE
