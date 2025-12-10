"""
Human-guided recording utilities for Theseus.

`SessionRecorder` wraps an `ExplorationDriver` and a `StateTracker` to
capture human-performed UI interactions as a sequence of:

    (state_before, action, state_after)

For each step, it:

- Captures the current UIState from the driver.
- Registers states with the StateTracker to obtain canonical ids.
- Constructs a Transition object linking the two states.
- Tags states and transitions with metadata such as:
    - source = "human"
    - session_id
    - author

The resulting UIState and Transition objects can be exported to Atlas
using the existing exporter / ingest pipeline, and will be compatible
with data produced by automated exploration.

This module does not perform any user interaction (no CLI prompts, no I/O);
it is intended to be driven by higher-level tools such as a CLI recorder.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from common.models.transition import Action, Transition
from common.models.ui_state import UIState
from theseus.core.exploration_engine import ExplorationDriver
from theseus.core.state_tracker import StateTracker


@dataclass
class RecordingStep:
    """
    Single recorded human interaction step.

    This is a lightweight view over the underlying states and transition.
    """

    index: int
    session_id: str

    source_state_id: str
    target_state_id: str
    transition_id: str

    action: Action
    intent_id: Optional[str] = None

    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """
        JSON-serializable representation of the step.

        This is intended for logging / debugging; Atlas ingest should
        generally use the underlying Transition / UIState objects.
        """
        return {
            "index": self.index,
            "session_id": self.session_id,
            "source_state_id": self.source_state_id,
            "target_state_id": self.target_state_id,
            "transition_id": self.transition_id,
            "intent_id": self.intent_id,
            "timestamp": self.timestamp,
            "action": {
                "type": self.action.type.value,
                "element_id": self.action.element_id,
                "raw_input": self.action.raw_input,
                "metadata": dict(self.action.metadata),
            },
        }


class SessionRecorder:
    """
    Record a human-guided workflow using an ExplorationDriver.

    Typical usage pattern (simplified):

        driver = WebBrowserSession(...)
        tracker = StateTracker(config=...)
        recorder = SessionRecorder(driver, tracker, author="assistant-1")

        # Capture initial state
        initial_state = recorder.begin()

        # For each human step:
        #   1. Human performs an action in the UI.
        #   2. Recorder captures the new state and links it to the previous one.
        step = recorder.record_step(action, intent_id="export_pdf")

        # After the session:
        states = recorder.get_states()
        transitions = recorder.get_transitions()
        # -> wrap in StateRecord / TransitionRecord and ingest into Atlas.

    The recorder does not drive the UI itself. The calling code is
    responsible for instructing the human operator and/or invoking driver
    methods; the recorder only captures the before/after states and builds
    transitions.
    """

    def __init__(
        self,
        driver: ExplorationDriver,
        state_tracker: StateTracker,
        *,
        session_id: Optional[str] = None,
        author: Optional[str] = None,
        default_intent_id: Optional[str] = None,
        base_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Args:
            driver: ExplorationDriver implementation (web/desktop/etc.).
            state_tracker: StateTracker used to deduplicate states and
                track canonical ids.
            session_id: Optional explicit session id; if omitted, a UUID4
                string is generated.
            author: Optional identifier for the human operator (stored in
                metadata on states/transitions).
            default_intent_id: Optional intent id to use for steps that do
                not specify an intent explicitly.
            base_metadata: Optional metadata dict that will be merged into
                every state/transition metadata (keys from per-step metadata
                take precedence).
        """
        self._driver = driver
        self._tracker = state_tracker

        self._session_id: str = session_id or str(uuid.uuid4())
        self._author: Optional[str] = author
        self._default_intent_id: Optional[str] = default_intent_id
        self._base_metadata: Dict[str, Any] = dict(base_metadata or {})

        # Canonical states and transitions observed in this session
        self._states: Dict[str, UIState] = {}
        self._transitions: List[Transition] = []

        # Ordered list of steps for convenience
        self._steps: List[RecordingStep] = []

        # Current canonical state id (after begin() or last recorded step)
        self._current_state_id: Optional[str] = None

    # ------------------------------------------------------------------ #
    # Session lifecycle
    # ------------------------------------------------------------------ #

    @property
    def session_id(self) -> str:
        """Identifier for this recording session."""
        return self._session_id

    @property
    def author(self) -> Optional[str]:
        """Author / operator identifier, if provided."""
        return self._author

    def begin(self, initial_state: Optional[UIState] = None) -> UIState:
        """
        Capture and register the initial state for the session.

        If `initial_state` is None, the recorder will call
        `driver.capture_state()` to obtain it.

        Returns:
            The canonical UIState (possibly modified by the StateTracker).
        """
        if initial_state is None:
            initial_state = self._driver.capture_state()

        state = self._tag_state_metadata(initial_state)
        canonical_state = self._tracker.register_state(state)
        self._states[canonical_state.id] = canonical_state
        self._current_state_id = canonical_state.id
        return canonical_state

    # ------------------------------------------------------------------ #
    # Step recording
    # ------------------------------------------------------------------ #

    def record_step(
        self,
        action: Action,
        *,
        intent_id: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        next_state: Optional[UIState] = None,
    ) -> RecordingStep:
        """
        Record a single human step.

        Args:
            action:
                The Action describing what the human operator just did.
                The caller is responsible for constructing it (e.g., based
                on a selected UI element or keypress).
            intent_id:
                Optional intent id for this step; if omitted, the recorder's
                `default_intent_id` (if any) is used.
            extra_metadata:
                Optional additional metadata to attach to the Transition
                (merged with session-level metadata, per-step keys win).
            next_state:
                Optional UIState representing the "after" state. If omitted,
                the recorder will call `driver.capture_state()`.

        Returns:
            RecordingStep describing the recorded interaction.

        Raises:
            RuntimeError if `begin()` has not been called.
        """
        if self._current_state_id is None:
            raise RuntimeError(
                "SessionRecorder.begin() must be called before record_step()."
            )

        source_state_id = self._current_state_id
        source_state = self._states.get(source_state_id)
        if source_state is None:
            # As a fallback, ask the tracker (it should have the state)
            source_state = self._tracker.get_state(source_state_id)  # type: ignore[attr-defined]
        if source_state is None:
            raise RuntimeError(
                f"Current source state '{source_state_id}' not found in recorder."
            )

        # Capture the new state, if not provided by caller
        if next_state is None:
            next_state = self._driver.capture_state()

        next_state = self._tag_state_metadata(next_state)
        canonical_target = self._tracker.register_state(next_state)
        self._states[canonical_target.id] = canonical_target

        # Construct transition id (session-scoped and deterministic)
        step_index = len(self._steps)
        transition_id = self._make_transition_id(
            source_state_id, canonical_target.id, step_index
        )

        # Prepare transition metadata
        transition_metadata: Dict[str, Any] = {}
        transition_metadata.update(self._base_metadata)
        if extra_metadata:
            transition_metadata.update(extra_metadata)
        transition_metadata.setdefault("source", "human")
        transition_metadata.setdefault("session_id", self._session_id)
        if self._author is not None:
            transition_metadata.setdefault("author", self._author)

        effective_intent_id = intent_id or self._default_intent_id

        transition = Transition(
            id=transition_id,
            source_state_id=source_state_id,
            target_state_id=canonical_target.id,
            action=action,
            intent_id=effective_intent_id,
            confidence=1.0,
            metadata=transition_metadata,
        )

        # Let the tracker know about the new transition
        self._tracker.add_transition(transition)

        # Store in local collections
        self._transitions.append(transition)
        self._current_state_id = canonical_target.id

        step = RecordingStep(
            index=step_index,
            session_id=self._session_id,
            source_state_id=source_state_id,
            target_state_id=canonical_target.id,
            transition_id=transition.id,
            action=action,
            intent_id=effective_intent_id,
        )
        self._steps.append(step)
        return step

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #

    def get_states(self) -> List[UIState]:
        """
        Return all unique states observed in this session.

        The order is undefined but stable within the lifetime of the recorder.
        """
        return list(self._states.values())

    def get_transitions(self) -> List[Transition]:
        """
        Return all transitions recorded in this session, in chronological order.
        """
        return list(self._transitions)

    def get_steps(self) -> List[RecordingStep]:
        """
        Return a chronological list of RecordingStep objects.
        """
        return list(self._steps)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _tag_state_metadata(self, state: UIState) -> UIState:
        """
        Attach session-level metadata to a UIState.

        This mutates the state's metadata in-place and returns it.
        """
        md = state.metadata or {}
        # Merge base metadata first
        merged: Dict[str, Any] = dict(self._base_metadata)
        merged.update(md)

        merged.setdefault("source", "human")
        merged.setdefault("session_id", self._session_id)
        if self._author is not None:
            merged.setdefault("author", self._author)

        state.metadata = merged
        return state

    @staticmethod
    def _make_transition_id(
        source_state_id: str,
        target_state_id: str,
        index: int,
    ) -> str:
        """
        Build a session-scoped transition id.

        This is a simple deterministic helper; persistent deployments may
        override or replace id generation at a higher level if needed.
        """
        return f"{source_state_id}__{index}__{target_state_id}"
