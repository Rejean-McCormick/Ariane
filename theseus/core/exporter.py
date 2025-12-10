"""
Exporter for Theseus → Atlas.

This module takes:

- The in-memory exploration results from Theseus:
    - StateTracker (UI states)
    - A list of Transition objects

and turns them into Atlas-ready objects:

- Context
- StateRecord[]
- TransitionRecord[]

It does NOT perform any I/O by itself. Callers can:

- Use `build_bundle()` and send the result to an HTTP API (/ingest/bundle).
- Or manually persist the objects with a custom backend.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set

from atlas.schema.context import Context
from atlas.schema.state_schema import StateRecord
from atlas.schema.transition_schema import TransitionRecord
from common.models.ui_state import Platform
from common.models.transition import Transition
from .state_tracker import StateTracker, TrackedState


@dataclass
class ExporterConfig:
    """
    Configuration for the Theseus → Atlas exporter.

    Attributes:
        context_id:
            Optional explicit context id. If not provided, a new one will be
            generated (app-based prefix + random suffix).
        app_id:
            Optional logical application id. If omitted, the exporter attempts
            to infer it from the first tracked state.
        version:
            Optional application version. If omitted, can be inferred from
            the first tracked state if available.
        platform:
            Logical platform for the context. If None, will be inferred
            from the first tracked state (falling back to Platform.OTHER).
        locale:
            Locale tag, e.g. "en-US". If None, can be inferred from
            the first tracked state if available.
        environment:
            Free-form description of the environment (OS version, device, etc.).
        metadata:
            Additional metadata to attach to the Context.
        explicit_entry_state_ids:
            Optional explicit set of state ids that should be marked as entry
            states. If None, the exporter will infer entry states as those
            that never appear as a transition target (or, if none, the
            earliest observed state).
        mark_terminal_states:
            If True, states with no outgoing transitions are marked as
            terminal in their StateRecord.
    """

    context_id: Optional[str] = None
    app_id: Optional[str] = None
    version: Optional[str] = None
    platform: Optional[Platform] = None
    locale: Optional[str] = None

    environment: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    explicit_entry_state_ids: Optional[List[str]] = None
    mark_terminal_states: bool = True


class Exporter:
    """
    Exporter from Theseus' in-memory exploration results to Atlas schema.

    Typical usage:

        tracker = StateTracker(...)
        transitions = engine.transitions  # list[Transition]
        exporter = Exporter(state_tracker=tracker, transitions=transitions, config=cfg)

        bundle = exporter.build_bundle()
        # POST bundle to /ingest/bundle, or persist as you like.
    """

    def __init__(
        self,
        *,
        state_tracker: StateTracker,
        transitions: List[Transition],
        config: Optional[ExporterConfig] = None,
    ) -> None:
        self.state_tracker = state_tracker
        self.transitions = transitions
        self.config = config or ExporterConfig()
        self._context: Optional[Context] = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def build_context(self) -> Context:
        """
        Build (and cache) the Context object for this export.

        Uses explicit configuration where provided, and falls back to
        inferred values from the first tracked state if necessary.
        """
        if self._context is not None:
            return self._context

        first_tracked = self._get_first_tracked_state()
        inferred_app_id = first_tracked.state.app_id if first_tracked else None
        inferred_version = first_tracked.state.version if first_tracked else None
        inferred_platform = first_tracked.state.platform if first_tracked else Platform.OTHER
        inferred_locale = first_tracked.state.locale if first_tracked else None

        app_id = self.config.app_id or inferred_app_id
        if not app_id:
            raise ValueError(
                "ExporterConfig.app_id is not set and could not be inferred "
                "from tracked states"
            )

        context_id = self.config.context_id or self._generate_context_id(app_id)

        ctx = Context(
            context_id=context_id,
            app_id=app_id,
            version=self.config.version or inferred_version,
            platform=self.config.platform or inferred_platform,
            locale=self.config.locale or inferred_locale,
            environment=dict(self.config.environment),
            metadata=dict(self.config.metadata),
        )

        self._context = ctx
        return ctx

    def build_state_records(self) -> List[StateRecord]:
        """
        Build StateRecord objects for all tracked states.

        Entry and terminal flags are derived based on transitions and
        configuration.
        """
        context = self.build_context()
        context_id = context.context_id

        tracked_states = list(self.state_tracker.all_tracked())
        outgoing_counts = self._compute_outgoing_counts()
        entry_ids = self._determine_entry_state_ids(tracked_states, outgoing_counts)

        records: List[StateRecord] = []
        for tracked in tracked_states:
            state_id = tracked.state.id

            is_entry = state_id in entry_ids
            is_terminal = False
            if self.config.mark_terminal_states:
                is_terminal = outgoing_counts.get(state_id, 0) == 0

            metadata = {
                "first_seen_at": tracked.first_seen_at,
                "last_seen_at": tracked.last_seen_at,
                "times_seen": tracked.times_seen,
            }

            record = StateRecord(
                context_id=context_id,
                state=tracked.state,
                discovered_at=tracked.first_seen_at,
                is_entry=is_entry,
                is_terminal=is_terminal,
                tags=[],
                metadata=metadata,
            )
            records.append(record)

        return records

    def build_transition_records(self) -> List[TransitionRecord]:
        """
        Build TransitionRecord objects for all observed transitions.

        Each Transition in `self.transitions` becomes a TransitionRecord
        with times_observed defaulting to 1. A downstream store (like
        GraphStore) can merge identical transitions and increase the
        observation count.
        """
        context = self.build_context()
        context_id = context.context_id

        records: List[TransitionRecord] = []
        for tr in self.transitions:
            record = TransitionRecord(
                context_id=context_id,
                transition=tr,
                # discovered_at default is "now". If you want to track precise
                # observation time per transition, you can extend Transition
                # metadata and override this here.
            )
            records.append(record)

        return records

    def build_bundle(self) -> Dict[str, Any]:
        """
        Build a single JSON-serializable bundle ready for /ingest/bundle.

        Returns:
            {
              "context": { ... },
              "states": [ { ...StateRecord.to_dict()... }, ... ],
              "transitions": [ { ...TransitionRecord.to_dict()... }, ... ]
            }
        """
        context = self.build_context()
        states = self.build_state_records()
        transitions = self.build_transition_records()

        return {
            "context": context.to_dict(),
            "states": [s.to_dict() for s in states],
            "transitions": [t.to_dict() for t in transitions],
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _get_first_tracked_state(self) -> Optional[TrackedState]:
        """
        Return the earliest tracked state by first_seen_at, or None if none.

        This is used for metadata inference (app_id, version, etc.).
        """
        all_tracked = list(self.state_tracker.all_tracked())
        if not all_tracked:
            return None

        # ISO 8601 strings compare lexicographically in chronological order
        # when all are in UTC with the same format, which we enforce.
        return min(all_tracked, key=lambda ts: ts.first_seen_at)

    @staticmethod
    def _generate_context_id(app_id: str) -> str:
        """
        Generate a simple context id using the app_id as a prefix.
        """
        prefix = app_id.replace(" ", "_").lower()
        return f"{prefix}-{uuid.uuid4().hex[:8]}"

    def _compute_outgoing_counts(self) -> Dict[str, int]:
        """
        Compute how many outgoing transitions each state has.

        Returns:
            dict: state_id -> outgoing_count
        """
        counts: Dict[str, int] = {}
        for tr in self.transitions:
            src = tr.source_state_id
            counts[src] = counts.get(src, 0) + 1
        return counts

    def _determine_entry_state_ids(
        self,
        tracked_states: List[TrackedState],
        outgoing_counts: Dict[str, int],
    ) -> Set[str]:
        """
        Determine which state ids should be marked as entry states.

        Strategy:

            1. If explicit_entry_state_ids is set in config, use that.
            2. Else, choose states that never appear as a transition target.
               (i.e. no incoming edges).
            3. If that set is empty, fall back to the earliest observed state.
        """
        # 1) Explicit configuration
        if self.config.explicit_entry_state_ids:
            return set(self.config.explicit_entry_state_ids)

        # 2) Candidates based on incoming edges
        all_ids = {ts.state.id for ts in tracked_states}
        targets = {tr.target_state_id for tr in self.transitions}
        entry_candidates = all_ids - targets

        if entry_candidates:
            return entry_candidates

        # 3) Fallback: earliest observed state
        first = self._get_first_tracked_state()
        return {first.state.id} if first is not None else set()
