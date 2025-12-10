#!/usr/bin/env bash
#
# scripts/dev_env_setup.sh
#
# Convenience script to bootstrap a local development environment for Ariane.
#
# It will:
#   - Detect a Python 3 interpreter
#   - Create a local virtualenv in `.venv/` (if not already present)
#   - Install dependencies from one of:
#       pyproject.toml  ->  `pip install -e ".[dev]"` (if present)
#       requirements-dev.txt
#       requirements.txt
#
# Adjust this script as needed for your environment or dependency layout.
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== Ariane dev environment setup =="
echo "Repository root: $REPO_ROOT"
echo

# ---------------------------------------------------------------------------
# Detect Python 3
# ---------------------------------------------------------------------------

PYTHON_BIN="${PYTHON_BIN:-}"

if [ -z "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
  else
    echo "Error: Python 3 not found on PATH." >&2
    exit 1
  fi
fi

echo "Using Python: $PYTHON_BIN"
echo

# ---------------------------------------------------------------------------
# Create virtualenv (.venv)
# ---------------------------------------------------------------------------

VENV_DIR="${VENV_DIR:-"$REPO_ROOT/.venv"}"

if [ -d "$VENV_DIR" ]; then
  echo "Virtualenv already exists at: $VENV_DIR"
else
  echo "Creating virtualenv at: $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# Activate venv (POSIX-style)
# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

echo
echo "Virtualenv activated."
echo "Python: $(command -v python)"
echo

# ---------------------------------------------------------------------------
# Upgrade pip / tooling
# ---------------------------------------------------------------------------

echo "Upgrading pip and basic tooling..."
python -m pip install --upgrade pip setuptools wheel >/dev/null
echo "Done."
echo

# ---------------------------------------------------------------------------
# Install dependencies
# ---------------------------------------------------------------------------

have_pyproject=false
have_req_dev=false
have_req=false

if [ -f "pyproject.toml" ]; then
  have_pyproject=true
fi
if [ -f "requirements-dev.txt" ]; then
  have_req_dev=true
fi
if [ -f "requirements.txt" ]; then
  have_req=true
fi

if $have_pyproject; then
  echo "Found pyproject.toml – installing in editable mode with dev extras:"
  echo "  pip install -e '.[dev]'"
  python -m pip install -e ".[dev]"
elif $have_req_dev; then
  echo "Found requirements-dev.txt – installing:"
  echo "  pip install -r requirements-dev.txt"
  python -m pip install -r requirements-dev.txt
elif $have_req; then
  echo "Found requirements.txt – installing:"
  echo "  pip install -r requirements.txt"
  python -m pip install -r requirements.txt
else
  cat <<EOF

No dependency definition found (pyproject.toml, requirements-dev.txt, or requirements.txt).

You can now manually install any dependencies you need, for example:

  pip install <package>

EOF
fi

echo
echo "== Dev environment ready =="
echo
echo "To activate it later, run:"
echo "  source \"$VENV_DIR/bin/activate\""
echo
