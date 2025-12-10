"""
Models for the Guidance Client.

These are pure data structures used by the guidance engine and
presentation layers. They do not perform any network or UI work.

The models are designed as a thin layer on top of the existing SDK
types (StateView, TransitionView, UIElementHint, PathView).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from consumers.sdk.types import (
    StateView,
    TransitionView,
    UIElementHint,
    PathView,
)


# --------------------------------------------------------------------------- #
# Goal / intent representation
# --------------------------------------------------------------------------- #


class GoalType(str, Enum):
    """
    Describes how a guidance goal was specified.

    - INTENT:      “I want to do X” (intent_id).
    - TARGET_STATE: “I want to be on this specific state”.
    - WORKFLOW:    “Run a named workflow” (future extension).
    """

    INTENT = "intent"
    TARGET_STATE = "target_state"
    WORKFLOW = "workflow"


@dataclass
class GuidanceGoal:
    """
    High-level description of what the user is trying to achieve.

    Exactly one of (intent_id, target_state_id, workflow_id) should
    normally be set, depending on `goal_type`.
    """

    goal_type: GoalType

    # Optional identifiers, interpreted according to goal_type.
    intent_id: Optional[str] = None
    target_state_id: Optional[str] = None
    workflow_id: Optional[str] = None

    # Optional human-readable labels.
    label: Optional[str] = None
    description: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_type": self.goal_type.value,
            "intent_id": self.intent_id,
            "target_state_id": self.target_state_id,
            "workflow_id": self.workflow_id,
            "label": self.label,
            "description": self.description,
            "metadata": dict(self.metadata),
        }


# --------------------------------------------------------------------------- #
# Matching / state resolution
# --------------------------------------------------------------------------- #


@dataclass
class StateMatchDetails:
    """
    Optional diagnostic information for how a state match was computed.
    All fields are optional and for debugging / explainability only.
    """

    structural_score: Optional[float] = None
    semantic_score: Optional[float] = None
    visual_score: Optional[float] = None
    combined_score: Optional[float] = None

    # Arbitrary implementation-specific details.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "structural_score": self.structural_score,
            "semantic_score": self.semantic_score,
            "visual_score": self.visual_score,
            "combined_score": self.combined_score,
            "metadata": dict(self.metadata),
        }


@dataclass
class StateMatchResult:
    """
    Result of matching a local UI snapshot to a known StateView.

    The guidance engine will usually take the best-ranked match above a
    certain confidence threshold as the current state.
    """

    state: StateView
    score: float  # Normalized confidence in [0.0, 1.0]
    details: Optional[StateMatchDetails] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "score": float(self.score),
            "details": self.details.to_dict() if self.details else None,
        }


# --------------------------------------------------------------------------- #
# Guidance steps
# --------------------------------------------------------------------------- #


class GuidanceStepKind(str, Enum):
    """
    Type of guidance step.

    ACTION:
        A concrete action the user should perform (“click this button”).
    INFO:
        Informational / contextual message, no action required.
    COMPLETE:
        Indicates that the guidance goal has been reached.
    ERROR:
        Indicates that guidance cannot proceed (missing path, mismatch, etc.).
    """

    ACTION = "action"
    INFO = "info"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class GuidanceStep:
    """
    A single step in a guidance plan.

    The presentation layer can use `instruction` for text, and
    `element_hint` to optionally highlight the corresponding UI element.
    """

    step_index: int
    step_count: int

    kind: GuidanceStepKind

    # Human-readable instruction.
    instruction: str

    # Optional references into the Atlas graph.
    context_id: Optional[str] = None
    source_state_id: Optional[str] = None
    target_state_id: Optional[str] = None

    # Optional view of the underlying transition (if applicable).
    transition: Optional[TransitionView] = None

    # Optional element hint used for UI overlay and richer descriptions.
    element_hint: Optional[UIElementHint] = None

    # Additional notes or hints for the user.
    notes: Optional[str] = None

    # Whether the UI should prevent / discourage other actions
    # while this step is active (for guardrail-like behavior).
    blocking: bool = False

    # Free-form metadata for clients.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": int(self.step_index),
            "step_count": int(self.step_count),
            "kind": self.kind.value,
            "instruction": self.instruction,
            "context_id": self.context_id,
            "source_state_id": self.source_state_id,
            "target_state_id": self.target_state_id,
            "transition": self.transition.to_dict() if self.transition else None,
            "element_hint": self.element_hint.to_dict()
            if self.element_hint
            else None,
            "notes": self.notes,
            "blocking": bool(self.blocking),
            "metadata": dict(self.metadata),
        }


# --------------------------------------------------------------------------- #
# Guidance plans and sessions
# --------------------------------------------------------------------------- #


class GuidancePlanStatus(str, Enum):
    """
    Status of a computed guidance plan.

    READY:
        Plan is valid and can be executed step-by-step.
    FAILED:
        No usable path could be found or an error occurred.
    PARTIAL:
        A partial plan exists (e.g. mapped only part of the workflow).
    """

    READY = "ready"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class GuidancePlan:
    """
    A full plan from a current state towards a goal.

    This is typically built from a PathView and additional context, and
    then consumed by a presentation layer or a session controller.
    """

    context_id: str
    goal: GuidanceGoal

    # Starting and intended target states (may be equal for trivial goals).
    source_state_id: str
    target_state_id: str

    status: GuidancePlanStatus

    # Ordered list of guidance steps.
    steps: List[GuidanceStep] = field(default_factory=list)

    # Optional underlying path information for debugging.
    path_view: Optional[PathView] = None

    # Arbitrary metadata.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "goal": self.goal.to_dict(),
            "source_state_id": self.source_state_id,
            "target_state_id": self.target_state_id,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "path": self.path_view.to_dict() if self.path_view else None,
            "metadata": dict(self.metadata),
        }


class SessionStatus(str, Enum):
    """
    Overall status of an interactive guidance session.
    """

    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class GuidanceSessionState:
    """
    Lightweight state container for an ongoing guidance session.

    Typically owned by a session controller / engine. The session may be
    short-lived (a single CLI run) or long-lived (a GUI wizard).
    """

    context_id: str
    plan: GuidancePlan

    # Index of the current step in `plan.steps`, or -1 before start.
    current_step_index: int = -1

    # Last known state of the UI, if resolved.
    current_state: Optional[StateView] = None

    status: SessionStatus = SessionStatus.NOT_STARTED

    # Free-form metadata for consumers (timestamps, user IDs, etc.).
    metadata: Dict[str, Any] = field(default_factory=dict)

    def current_step(self) -> Optional[GuidanceStep]:
        """Return the current GuidanceStep, or None if index is out of range."""
        if 0 <= self.current_step_index < len(self.plan.steps):
            return self.plan.steps[self.current_step_index]
        return None

    def is_finished(self) -> bool:
        """Return True if the session is in a terminal status."""
        return self.status in {
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.CANCELLED,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "plan": self.plan.to_dict(),
            "current_step_index": int(self.current_step_index),
            "current_state": self.current_state.to_dict()
            if self.current_state
            else None,
            "status": self.status.value,
            "metadata": dict(self.metadata),
        }


__all__ = [
    "GoalType",
    "GuidanceGoal",
    "StateMatchDetails",
    "StateMatchResult",
    "GuidanceStepKind",
    "GuidanceStep",
    "GuidancePlanStatus",
    "GuidancePlan",
    "SessionStatus",
    "GuidanceSessionState",
]
