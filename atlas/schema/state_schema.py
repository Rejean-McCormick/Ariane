"""
State schema for Ariane Atlas.

This module defines the persistable schema for UI states as stored in Atlas.

It wraps the in-memory UIState model with Atlas-specific fields such as
the context identifier and simple flags (entry/terminal), so that Atlas
can manage states as part of a graph belonging to a particular context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from common.models.ui_state import UIState, Platform


@dataclass
class StateRecord:
    """
    Persistable representation of a UIState in Atlas.

    Attributes:
        context_id:
            Identifier of the Context this state belongs to.
        state:
            The UIState object (id, app_id, platform, fingerprints, elements, etc.).
        discovered_at:
            ISO 8601 timestamp (UTC) when this state was first recorded.
        is_entry:
            Whether this state is considered an entry/root state for the context
            (e.g., an application's home or start screen).
        is_terminal:
            Whether this state has been observed as terminal in exploration
            (no outgoing transitions discovered).
        tags:
            Free-form tags that Atlas or pipelines can attach (e.g., "menu",
            "error-screen", "wizard-step").
        metadata:
            Arbitrary additional Atlas-/pipeline-specific metadata.
    """

    context_id: str
    state: UIState

    discovered_at: str = field(
        default_factory=lambda: datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    )
    is_entry: bool = False
    is_terminal: bool = False
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --------------------------------------------------------------------- #
    # Convenience accessors
    # --------------------------------------------------------------------- #

    @property
    def id(self) -> str:
        """Shortcut to the underlying state's id."""
        return self.state.id

    @property
    def app_id(self) -> str:
        """Shortcut to the underlying state's app_id."""
        return self.state.app_id

    @property
    def platform(self) -> Platform:
        """Shortcut to the underlying state's platform."""
        return self.state.platform

    # --------------------------------------------------------------------- #
    # Serialization helpers
    # --------------------------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize this StateRecord to a JSON-friendly dictionary.

        The `state` is nested under the "state" key using UIState.to_dict().
        """
        return {
            "context_id": self.context_id,
            "discovered_at": self.discovered_at,
            "is_entry": self.is_entry,
            "is_terminal": self.is_terminal,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "state": self.state.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StateRecord":
        """
        Reconstruct a StateRecord from a dictionary produced by to_dict().
        """
        if "context_id" not in data:
            raise ValueError("StateRecord.from_dict: missing 'context_id'")
        if "state" not in data:
            raise ValueError("StateRecord.from_dict: missing 'state' payload")

        state_dict = data["state"]
        state = UIState(
            id=state_dict["id"],
            app_id=state_dict["app_id"],
            version=state_dict.get("version"),
            platform=Platform(state_dict.get("platform", Platform.OTHER.value)),
            locale=state_dict.get("locale"),
            fingerprints=dict(state_dict.get("fingerprints") or {}),
            screenshot_ref=state_dict.get("screenshot_ref"),
            interactive_elements=[],  # will be populated below
            metadata=dict(state_dict.get("metadata") or {}),
        )

        # Rebuild interactive elements if present
        from common.models.ui_state import InteractiveElement, BoundingBox  # local import to avoid cycles

        elements_data = state_dict.get("interactive_elements") or []
        for el in elements_data:
            bbox_data = el.get("bounding_box")
            bbox = None
            if bbox_data is not None:
                bbox = BoundingBox(
                    x=int(bbox_data["x"]),
                    y=int(bbox_data["y"]),
                    width=int(bbox_data["width"]),
                    height=int(bbox_data["height"]),
                )
            state.interactive_elements.append(
                InteractiveElement(
                    id=el["id"],
                    role=el["role"],
                    label=el.get("label"),
                    bounding_box=bbox,
                    path=el.get("path"),
                    enabled=bool(el.get("enabled", True)),
                    visible=bool(el.get("visible", True)),
                    metadata=dict(el.get("metadata") or {}),
                )
            )

        return cls(
            context_id=data["context_id"],
            state=state,
            discovered_at=data.get("discovered_at")
            or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            is_entry=bool(data.get("is_entry", False)),
            is_terminal=bool(data.get("is_terminal", False)),
            tags=list(data.get("tags") or []),
            metadata=dict(data.get("metadata") or {}),
        )
