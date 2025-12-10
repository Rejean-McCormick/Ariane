# docker/theseus.Dockerfile
#
# Container image for running the Theseus scanner.
#
# Usage (example):
#
#   docker build -f docker/theseus.Dockerfile -t ariane-theseus .
#
#   docker run --rm \
#     -e THESEUS_DRIVER_FACTORY="myproject.drivers.firefox:make_driver" \
#     -v "$PWD/config:/app/config:ro" \
#     -v "$PWD/out:/app/out" \
#     ariane-theseus
#
# Notes:
#   - THESEUS_DRIVER_FACTORY must point to a callable that returns an
#     ExplorationDriver instance (see scripts/run_theseus.sh).
#   - Config is read from config/theseus.yml (or the example file).
#   - Output mode (filesystem vs Atlas) is configured in that YAML.

FROM python:3.11-slim

# ---------------------------------------------------------------------------
# Basic system setup
# ---------------------------------------------------------------------------

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install minimal tooling (bash for our scripts)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# App layout
# ---------------------------------------------------------------------------

WORKDIR /app

# Copy repo contents into the image
COPY . /app

# Install Python dependencies
# - Prefer pyproject.toml if present (editable install)
# - Fallback to requirements.txt
RUN python -m pip install --upgrade pip && \
    if [ -f "pyproject.toml" ]; then \
        python -m pip install . ; \
    elif [ -f "requirements.txt" ]; then \
        python -m pip install -r requirements.txt ; \
    else \
        echo "No pyproject.toml or requirements.txt found; assuming no extra deps." ; \
    fi

# ---------------------------------------------------------------------------
# Defaults & entrypoint
# ---------------------------------------------------------------------------

# Default config path inside the container (can be overridden at runtime)
ENV THESEUS_CONFIG=/app/config/theseus.yml

# scripts/run_theseus.sh expects THESEUS_DRIVER_FACTORY to be set by the user.
# For example:
#   -e THESEUS_DRIVER_FACTORY="myproject.drivers.firefox:make_driver"
#
# It is intentionally NOT given a default here.

ENTRYPOINT ["bash", "scripts/run_theseus.sh"]
