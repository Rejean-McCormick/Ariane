"""
Transition model for Ariane.

A transition represents a directed edge in the UI graph:
moving from one UI state to another via a concrete user action
(e.g., clicking a button, pressing a key, choosing a menu item).

Transitions can optionally be annotated with a semantic intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from .intents import Intent


class ActionType(str, Enum):
    """
    Low-level action type describing how the transition was triggered.

    This is intentionally coarse; drivers can extend via metadata.
    """

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    KEY_PRESS = "key_press"
    TEXT_INPUT = "text_input"
    FOCUS = "focus"
    HOVER = "hover"
    SCROLL = "scroll"
    TOUCH_TAP = "touch_tap"
    TOUCH_LONG_PRESS = "touch_long_press"
    GESTURE = "gesture"
    OTHER = "other"


@dataclass
class Action:
    """
    Concrete action that caused a transition.

    Attributes:
        type:
            Type of interaction (click, key press, etc.).
        element_id:
            ID of the InteractiveElement (within the source state) that was
            the primary target of the action, if applicable.
        raw_input:
            Optional raw input associated with the action, such as a key code
            or text snippet. This should be scrubbed of sensitive data by the
            driver before being set.
        metadata:
            Additional driver-specific details (e.g., mouse button, modifiers).
    """

    type: ActionType
    element_id: Optional[str] = None
    raw_input: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the action to a JSON-friendly dict."""
        return {
            "type": self.type.value,
            "element_id": self.element_id,
            "raw_input": self.raw_input,
            "metadata": dict(self.metadata),
        }


@dataclass
class Transition:
    """
    Directed transition from one UI state to another.

    Attributes:
        id:
            Stable identifier for this transition.
        source_state_id:
            ID of the source UIState.
        target_state_id:
            ID of the target UIState.
        action:
            Concrete action that caused the transition.
        intent_id:
            Optional ID of the semantic intent (e.g. "save", "export").
            This should correspond to Intent.id from common/models/intents.py
            and can be resolved by consumers; the Transition does not import
            the Intent object for serialization.
        confidence:
            Confidence score (0.0–1.0) that this transition correctly represents
            the observed behavior. Useful for noisy or inferred edges.
        metadata:
            Arbitrary additional metadata (driver/source specific).
    """

    id: str
    source_state_id: str
    target_state_id: str
    action: Action
    intent_id: Optional[str] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --- intent helpers -------------------------------------------------------

    def attach_intent(self, intent: Intent, overwrite: bool = True) -> None:
        """
        Attach a semantic intent to this transition.

        Args:
            intent: Intent instance to associate.
            overwrite: If False, existing intent_id will not be changed.
        """
        if self.intent_id is not None and not overwrite:
            return
        self.intent_id = intent.id

    # --- serialization --------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the transition to a JSON-friendly dict.

        This format is suitable for storage in Atlas or for export.
        """
        return {
            "id": self.id,
            "source_state_id": self.source_state_id,
            "target_state_id": self.target_state_id,
            "action": self.action.to_dict(),
            "intent_id": self.intent_id,
            "confidence": float(self.confidence),
            "metadata": dict(self.metadata),
        }

    # --- convenience constructors ---------------------------------------------

    @classmethod
    def from_click(
        cls,
        *,
        id: str,
        source_state_id: str,
        target_state_id: str,
        element_id: Optional[str] = None,
        intent: Optional[Intent] = None,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Transition":
        """
        Convenience constructor for click-like transitions.
        """
        act = Action(
            type=ActionType.CLICK,
            element_id=element_id,
            metadata=metadata or {},
        )
        intent_id = intent.id if intent is not None else None
        return cls(
            id=id,
            source_state_id=source_state_id,
            target_state_id=target_state_id,
            action=act,
            intent_id=intent_id,
            confidence=confidence,
            metadata={},
        )
