"""
Transition schema for Ariane Atlas.

This module defines the persistable schema for transitions (edges) as
stored in Atlas.

It wraps the in-memory Transition model with Atlas-specific fields such
as the context identifier and observation metadata, so that Atlas can
manage transitions as part of a graph belonging to a particular context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

from common.models.transition import Transition, Action, ActionType


@dataclass
class TransitionRecord:
    """
    Persistable representation of a Transition in Atlas.

    Attributes:
        context_id:
            Identifier of the Context this transition belongs to.
        transition:
            The Transition object (id, source/target, action, intent, etc.).
        discovered_at:
            ISO 8601 timestamp (UTC) when this transition was first recorded.
        times_observed:
            Number of times this transition has been seen in exploration or
            telemetry. This can help distinguish strong edges from rare ones.
        metadata:
            Arbitrary Atlas-/pipeline-specific metadata (e.g., scan id, source
            of observation, quality flags).
    """

    context_id: str
    transition: Transition

    discovered_at: str = field(
        default_factory=lambda: datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    )
    times_observed: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --------------------------------------------------------------------- #
    # Convenience accessors
    # --------------------------------------------------------------------- #

    @property
    def id(self) -> str:
        """Shortcut to the underlying transition's id."""
        return self.transition.id

    @property
    def source_state_id(self) -> str:
        """Shortcut to the underlying transition's source_state_id."""
        return self.transition.source_state_id

    @property
    def target_state_id(self) -> str:
        """Shortcut to the underlying transition's target_state_id."""
        return self.transition.target_state_id

    @property
    def intent_id(self) -> str | None:
        """Shortcut to the underlying transition's intent_id."""
        return self.transition.intent_id

    # --------------------------------------------------------------------- #
    # Serialization helpers
    # --------------------------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize this TransitionRecord to a JSON-friendly dictionary.

        The `transition` is nested under the "transition" key using
        Transition.to_dict().
        """
        return {
            "context_id": self.context_id,
            "discovered_at": self.discovered_at,
            "times_observed": int(self.times_observed),
            "metadata": dict(self.metadata),
            "transition": self.transition.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransitionRecord":
        """
        Reconstruct a TransitionRecord from a dictionary produced by to_dict().
        """
        if "context_id" not in data:
            raise ValueError("TransitionRecord.from_dict: missing 'context_id'")
        if "transition" not in data:
            raise ValueError("TransitionRecord.from_dict: missing 'transition' payload")

        tr_dict = data["transition"]

        # Rebuild Action
        action_dict = tr_dict.get("action") or {}
        action = Action(
            type=ActionType(action_dict.get("type", ActionType.OTHER.value)),
            element_id=action_dict.get("element_id"),
            raw_input=action_dict.get("raw_input"),
            metadata=dict(action_dict.get("metadata") or {}),
        )

        # Rebuild Transition
        transition = Transition(
            id=tr_dict["id"],
            source_state_id=tr_dict["source_state_id"],
            target_state_id=tr_dict["target_state_id"],
            action=action,
            intent_id=tr_dict.get("intent_id"),
            confidence=float(tr_dict.get("confidence", 1.0)),
            metadata=dict(tr_dict.get("metadata") or {}),
        )

        return cls(
            context_id=data["context_id"],
            transition=transition,
            discovered_at=data.get("discovered_at")
            or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            times_observed=int(data.get("times_observed", 1)),
            metadata=dict(data.get("metadata") or {}),
        )
