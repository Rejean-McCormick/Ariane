"""
Simple scan pipeline for Theseus.

This module wires together:

- An ExplorationDriver (web, desktop, etc.).
- The ExplorationEngine (DFS exploration).
- The Theseus → Atlas Exporter.

It runs a single exploration session and returns an Atlas-ready bundle
that can be POSTed to the Atlas HTTP API at `/ingest/bundle`, or written
to disk as JSON.

This module deliberately has no external dependencies beyond the core
Theseus/Atlas packages and the Python standard library.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from atlas.schema.context import Context
from common.models.ui_state import Platform
from common.models.transition import Transition
from ..core.exploration_engine import (
    ExplorationConfig,
    ExplorationDriver,
    ExplorationEngine,
)
from ..core.state_tracker import StateTracker, StateTrackerConfig
from ..core.exporter import Exporter, ExporterConfig


LOG = logging.getLogger(__name__)


@dataclass
class SimpleScanConfig:
    """
    Configuration for a simple scan run.

    Attributes:
        app_id:
            Logical identifier for the application being scanned.
            This is required; it becomes Context.app_id in Atlas.
        version:
            Optional application version string.
        platform:
            Logical platform (web, windows, linux, android, etc.).
            If not set, the exporter will try to infer it from states.
        locale:
            Optional locale tag (e.g. "en-US").
        # Exploration limits
        max_depth:
            Maximum depth of DFS exploration (number of actions from root).
            None = unlimited.
        max_states:
            Maximum number of distinct states to discover.
            None = unlimited.
        max_transitions:
            Maximum number of transitions to record.
            None = unlimited.
        # Behaviour flags
        skip_on_error:
            If True, log driver/action errors and continue.
            If False, errors abort the scan.
        log_actions:
            If True, log each action as it is performed.
    """

    app_id: str
    version: Optional[str] = None
    platform: Optional[Platform] = None
    locale: Optional[str] = None

    max_depth: Optional[int] = 10
    max_states: Optional[int] = 1_000
    max_transitions: Optional[int] = 10_000

    skip_on_error: bool = True
    log_actions: bool = True

    # Optional free-form metadata to attach to Context
    environment: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimpleScanResult:
    """
    Result of a simple scan.

    Attributes:
        context:
            The Context object created for this scan.
        transitions:
            List of Transition objects discovered by Theseus.
        bundle:
            JSON-serializable bundle (context + states + transitions)
            ready for ingestion by Atlas (/ingest/bundle).
    """

    context: Context
    transitions: list[Transition]
    bundle: Dict[str, Any]

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        """
        Serialize the bundle to a JSON string.

        Args:
            indent: Indent level for pretty-printing, or None for compact.
        """
        return json.dumps(self.bundle, ensure_ascii=False, indent=indent)


def run_simple_scan(
    driver: ExplorationDriver,
    *,
    config: SimpleScanConfig,
    tracker_config: Optional[StateTrackerConfig] = None,
) -> SimpleScanResult:
    """
    Run a single Theseus exploration session and export results to an
    Atlas-ready bundle.

    Args:
        driver:
            An object implementing the ExplorationDriver protocol
            (see theseus.core.exploration_engine).
        config:
            SimpleScanConfig describing the app and exploration limits.
        tracker_config:
            Optional StateTrackerConfig. If None, defaults are used.

    Returns:
        SimpleScanResult containing:
            - Context
            - List[Transition]
            - Atlas ingest bundle (dict)
    """
    LOG.info("Starting simple scan for app_id=%s", config.app_id)

    # 1) Wire up StateTracker and ExplorationEngine
    state_tracker = StateTracker(config=tracker_config)
    exploration_cfg = ExplorationConfig(
        max_depth=config.max_depth,
        max_states=config.max_states,
        max_transitions=config.max_transitions,
        skip_on_error=config.skip_on_error,
        log_actions=config.log_actions,
    )
    engine = ExplorationEngine(
        driver=driver,
        state_tracker=state_tracker,
        config=exploration_cfg,
    )

    # 2) Explore
    transitions = engine.explore()

    LOG.info(
        "Exploration completed: %d states, %d transitions",
        len(state_tracker),
        len(transitions),
    )

    # 3) Export to Atlas schema
    exporter_cfg = ExporterConfig(
        app_id=config.app_id,
        version=config.version,
        platform=config.platform,
        locale=config.locale,
        environment=dict(config.environment),
        metadata=dict(config.metadata),
    )

    exporter = Exporter(
        state_tracker=state_tracker,
        transitions=transitions,
        config=exporter_cfg,
    )

    context = exporter.build_context()
    bundle = exporter.build_bundle()

    LOG.info(
        "Export completed: context_id=%s, states=%d, transitions=%d",
        context.context_id,
        len(bundle.get("states", [])),
        len(bundle.get("transitions", [])),
    )

    return SimpleScanResult(
        context=context,
        transitions=list(transitions),
        bundle=bundle,
    )
