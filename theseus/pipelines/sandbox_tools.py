"""
Sandbox tools for Theseus.

This module contains small, dependency-free utilities that make it easy
to:

- Run a simple scan against a driver in a local sandbox.
- Persist the resulting Atlas bundle to disk as JSON.
- Optionally keep per-run metadata (timestamps, etc.).

These helpers are meant for experimentation and local development, not
for production deployments.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..core.exploration_engine import ExplorationDriver
from .simple_scan import SimpleScanConfig, SimpleScanResult, run_simple_scan

LOG = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Filesystem sink
# --------------------------------------------------------------------------- #


@dataclass
class FileSinkConfig:
    """
    Configuration for writing scan results to the local filesystem.

    Attributes:
        output_dir:
            Base directory where all scan artifacts will be written.
        use_timestamp_subdirs:
            If True, each run gets its own timestamped subdirectory under
            `output_dir` (e.g. `output_dir/2025-01-01T12-34-56Z/`).
            If False, files are written directly into `output_dir`.
        bundle_filename:
            Filename to use for the main bundle JSON.
        metadata_filename:
            Filename to use for run metadata JSON.
    """

    output_dir: Path
    use_timestamp_subdirs: bool = True
    bundle_filename: str = "atlas_bundle.json"
    metadata_filename: str = "scan_metadata.json"


@dataclass
class FileSink:
    """
    Simple sink that writes a SimpleScanResult to disk.

    Typical usage:

        sink = FileSink.from_directory("out/scan1")
        result = run_simple_scan(driver, config=scan_cfg)
        run_dir = sink.write(result)

    The return value `run_dir` is the directory where files were written.
    """

    config: FileSinkConfig

    @classmethod
    def from_directory(
        cls,
        path: str | Path,
        *,
        use_timestamp_subdirs: bool = True,
        bundle_filename: str = "atlas_bundle.json",
        metadata_filename: str = "scan_metadata.json",
    ) -> "FileSink":
        cfg = FileSinkConfig(
            output_dir=Path(path),
            use_timestamp_subdirs=use_timestamp_subdirs,
            bundle_filename=bundle_filename,
            metadata_filename=metadata_filename,
        )
        return cls(config=cfg)

    def _make_run_dir(self) -> Path:
        """
        Determine and create the directory where this run will be stored.
        """
        base = self.config.output_dir
        base.mkdir(parents=True, exist_ok=True)

        if not self.config.use_timestamp_subdirs:
            return base

        ts = datetime.utcnow().replace(microsecond=0).isoformat().replace(":", "-") + "Z"
        run_dir = base / ts
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def write(self, result: SimpleScanResult) -> Path:
        """
        Write the given SimpleScanResult to disk.

        Files written:

            <run_dir>/<bundle_filename>   – full Atlas bundle (JSON)
            <run_dir>/<metadata_filename> – small metadata sidecar (JSON)

        Returns:
            Path to the run directory.
        """
        run_dir = self._make_run_dir()

        # Bundle
        bundle_path = run_dir / self.config.bundle_filename
        with bundle_path.open("w", encoding="utf-8") as f:
            json.dump(result.bundle, f, ensure_ascii=False, indent=2)

        # Metadata
        meta_path = run_dir / self.config.metadata_filename
        metadata: Dict[str, Any] = {
            "context": result.context.to_dict(),
            "transition_count": len(result.transitions),
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        with meta_path.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        LOG.info("Wrote bundle to %s", bundle_path)
        LOG.info("Wrote metadata to %s", meta_path)

        return run_dir


# --------------------------------------------------------------------------- #
# High-level helper
# --------------------------------------------------------------------------- #


def run_scan_to_disk(
    driver: ExplorationDriver,
    *,
    scan_config: SimpleScanConfig,
    output_dir: str | Path,
    use_timestamp_subdirs: bool = True,
) -> Path:
    """
    Convenience helper that:

        1) Runs a simple scan with the provided driver and config.
        2) Writes the resulting bundle + metadata to disk.
        3) Returns the directory where files were written.

    Args:
        driver:
            An object implementing the ExplorationDriver protocol.
        scan_config:
            Configuration for the scan (SimpleScanConfig).
        output_dir:
            Base directory where scan artifacts will be stored.
        use_timestamp_subdirs:
            If True, create a timestamped subdirectory for this run.
            If False, write directly into `output_dir`.

    Returns:
        Path to the directory containing the written files.
    """
    LOG.info("Running sandbox scan for app_id=%s", scan_config.app_id)

    result = run_simple_scan(driver, config=scan_config, tracker_config=None)

    sink = FileSink.from_directory(
        output_dir,
        use_timestamp_subdirs=use_timestamp_subdirs,
    )
    run_dir = sink.write(result)

    LOG.info("Sandbox scan completed; results in %s", run_dir)
    return run_dir
