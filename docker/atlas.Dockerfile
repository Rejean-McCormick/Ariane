# docker/atlas.Dockerfile
#
# Container image for running the Atlas HTTP server.
#
# Usage (example):
#
#   docker build -f docker/atlas.Dockerfile -t ariane-atlas .
#
#   docker run --rm \
#     -p 8080:8080 \
#     -v "$PWD/config:/app/config:ro" \
#     -v "$PWD/logs:/app/logs" \
#     ariane-atlas
#
# Notes:
#   - Server config is read from config/atlas.yml (or atlas.example.yml).
#   - Logging config is read from config/logging.yml (or logging.example.yml).
#   - See scripts/run_atlas.sh for environment variables and behaviour.

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
# - Prefer pyproject.toml if present
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
# Default configuration paths
# ---------------------------------------------------------------------------

# These can be overridden at runtime:
#   -e ATLAS_CONFIG=/app/config/atlas.yml
#   -e ATLAS_LOGGING_CONFIG=/app/config/logging.yml
ENV ATLAS_CONFIG=/app/config/atlas.yml \
    ATLAS_LOGGING_CONFIG=/app/config/logging.yml

# scripts/run_atlas.sh reads ATLAS_CONFIG_PATH and ATLAS_LOGGING_CONFIG_PATH,
# but we set ATLAS_CONFIG/ATLAS_LOGGING_CONFIG for convenience. The script
# falls back to the example files if the explicit ones are missing.

# Expose default HTTP port
EXPOSE 8080

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

ENTRYPOINT ["bash", "scripts/run_atlas.sh"]
