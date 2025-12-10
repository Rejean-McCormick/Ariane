"""
State tracker for Theseus.

This module provides an in-memory registry for UI states discovered by
Theseus during exploration. Its responsibilities are:

- Deduplicate states based on fingerprints (structural / visual / semantic).
- Assign stable state IDs when needed.
- Track basic observation statistics (first seen, last seen, times seen).
- Provide simple query methods for the exploration engine.

This module is intentionally independent of Atlas; exporting to Atlas
(StateRecord, etc.) is handled by the exporter layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from common.models.ui_state import UIState


@dataclass
class TrackedState:
    """
    Internal representation of a tracked UI state.

    Attributes:
        state:
            The UIState instance (with id, app_id, fingerprints, etc.).
        first_seen_at:
            ISO 8601 timestamp (UTC) of the first observation.
        last_seen_at:
            ISO 8601 timestamp (UTC) of the most recent observation.
        times_seen:
            Number of times this state has been observed.
    """

    state: UIState
    first_seen_at: str = field(
        default_factory=lambda: datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    )
    last_seen_at: str = field(
        default_factory=lambda: datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    )
    times_seen: int = 1

    def touch(self) -> None:
        """Record another observation of this state."""
        self.times_seen += 1
        self.last_seen_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class StateTrackerConfig:
    """
    Configuration for StateTracker.

    Attributes:
        prefer_fingerprint_keys:
            Ordered list of fingerprint keys to consider for deduplication.
            By default, tries "structural", then "visual", then "semantic".
        allow_id_fallback:
            If True and no configured fingerprints are present, the tracker
            will fall back to using `UIState.id` for deduplication.
        auto_generate_ids:
            If True and `UIState.id` is empty, the tracker will generate a
            new random ID and assign it to the state.
    """

    prefer_fingerprint_keys: List[str] = field(
        default_factory=lambda: ["structural", "visual", "semantic"]
    )
    allow_id_fallback: bool = True
    auto_generate_ids: bool = True


class StateTracker:
    """
    In-memory tracker for UI states discovered by Theseus.

    Typical usage:

        tracker = StateTracker()

        # each time a new UIState is observed:
        state_id, is_new = tracker.observe_state(ui_state)

        if is_new:
            # e.g., schedule this state for expansion by the explorer
            ...

    The tracker does not care where UIState instances come from; it only
    uses their fingerprints and ids for deduplication.
    """

    def __init__(self, config: Optional[StateTrackerConfig] = None) -> None:
        self._config = config or StateTrackerConfig()

        # state_id -> TrackedState
        self._states_by_id: Dict[str, TrackedState] = {}

        # dedup_key -> state_id
        self._index_by_key: Dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def observe_state(self, state: UIState) -> Tuple[str, bool]:
        """
        Register an observation of a UIState.

        Deduplication is based on fingerprints (structural/visual/semantic)
        according to the configured preference order. If no suitable
        fingerprint is available and allow_id_fallback is True, the state's
        id is used as the deduplication key.

        Args:
            state:
                UIState instance produced by a driver or exploration step.

        Returns:
            (state_id, is_new)
                state_id:
                    The canonical ID for this logical state.
                is_new:
                    True if this observation resulted in a newly tracked
                    state, False if it was merged with an existing one.
        """
        # Ensure state.id exists if we may need it
        if (not state.id) and self._config.auto_generate_ids:
            state.id = self._generate_state_id()

        dedup_key = self._make_dedup_key(state)
        state_id: str

        if dedup_key is not None and dedup_key in self._index_by_key:
            # Known state; update stats
            state_id = self._index_by_key[dedup_key]
            tracked = self._states_by_id[state_id]
            tracked.touch()
            # Optionally, we could also update stored state metadata here.
            return state_id, False

        # New logical state
        state_id = state.id
        tracked = TrackedState(state=state)
        self._states_by_id[state_id] = tracked

        if dedup_key is not None:
            self._index_by_key[dedup_key] = state_id

        return state_id, True

    def get_tracked(self, state_id: str) -> Optional[TrackedState]:
        """Return the TrackedState for a given state_id, or None if unknown."""
        return self._states_by_id.get(state_id)

    def get_state(self, state_id: str) -> Optional[UIState]:
        """Shortcut to get only the UIState for a given state_id."""
        tracked = self._states_by_id.get(state_id)
        return tracked.state if tracked is not None else None

    def all_tracked(self) -> Iterable[TrackedState]:
        """Iterate over all tracked states."""
        return list(self._states_by_id.values())

    def all_states(self) -> List[UIState]:
        """Return a list of all UIState instances currently tracked."""
        return [ts.state for ts in self._states_by_id.values()]

    def __len__(self) -> int:
        """Return the number of distinct logical states tracked."""
        return len(self._states_by_id)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _make_dedup_key(self, state: UIState) -> Optional[str]:
        """
        Compute a deduplication key for a UIState.

        Priority:
            1. First configured fingerprint key found in state.fingerprints.
            2. (Optional) Fallback to state.id if allow_id_fallback is True.
            3. Otherwise, return None.

        Returns:
            A string key, or None if no suitable key can be constructed.
        """
        fingerprint_map = state.fingerprints or {}

        for key in self._config.prefer_fingerprint_keys:
            value = fingerprint_map.get(key)
            if value:
                return f"{key}:{value}"

        if self._config.allow_id_fallback and state.id:
            return f"id:{state.id}"

        return None

    @staticmethod
    def _generate_state_id() -> str:
        """Generate a new random state ID."""
        return uuid.uuid4().hex
