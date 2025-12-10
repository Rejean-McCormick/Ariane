"""
Consumer-side types for Ariane Atlas.

These are small, dependency-free dataclasses that wrap the JSON
shapes returned by the Atlas HTTP API (see `atlas.api.http_server`
and `atlas.api.endpoints.*`).

They are designed for convenience when writing clients and AI
agents that:

- Query contexts, states, and transitions.
- Ask for shortest paths between UI states.
- Work with lightweight, Pythonic objects instead of raw dicts.

All types below use only standard-library types (str, dict, list, etc.)
so they can be safely used in any environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


JSONDict = Dict[str, Any]


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #


@dataclass
class ContextInfo:
    """
    High-level representation of an Atlas context.

    This corresponds roughly to the `Context.to_dict()` format:

        {
          "context_id": "...",
          "app_id": "...",
          "version": "...",
          "platform": "...",
          "locale": "...",
          "schema_version": "...",
          "created_at": "...",
          "environment": { ... },
          "metadata": { ... }
        }
    """

    context_id: str
    app_id: str
    version: Optional[str] = None
    platform: Optional[str] = None
    locale: Optional[str] = None
    schema_version: Optional[str] = None
    created_at: Optional[str] = None
    environment: JSONDict = field(default_factory=dict)
    metadata: JSONDict = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: JSONDict) -> "ContextInfo":
        """
        Create a ContextInfo from a dict returned by the Atlas API.
        """
        return cls(
            context_id=payload["context_id"],
            app_id=payload["app_id"],
            version=payload.get("version"),
            platform=payload.get("platform"),
            locale=payload.get("locale"),
            schema_version=payload.get("schema_version"),
            created_at=payload.get("created_at"),
            environment=dict(payload.get("environment") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )


# --------------------------------------------------------------------------- #
# UI elements & states
# --------------------------------------------------------------------------- #


@dataclass
class UIElementHint:
    """
    Lightweight representation of an interactive UI element.

    This mirrors the structure of entries in `UIState.interactive_elements`
    but uses only primitive types.

    Expected source (from Atlas UIState dict):

        {
          "id": "el_btn_create",
          "role": "button",
          "label": "Create",
          "bounding_box": {"x": 100, "y": 200, "width": 80, "height": 24},
          "path": "/Window[1]/Pane[2]/Button[4]",
          "enabled": true,
          "visible": true,
          "metadata": { ... }
        }
    """

    id: str
    role: str
    label: Optional[str] = None
    bounding_box: Optional[JSONDict] = None
    path: Optional[str] = None
    enabled: bool = True
    visible: bool = True
    metadata: JSONDict = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: JSONDict) -> "UIElementHint":
        return cls(
            id=payload["id"],
            role=payload["role"],
            label=payload.get("label"),
            bounding_box=payload.get("bounding_box"),
            path=payload.get("path"),
            enabled=bool(payload.get("enabled", True)),
            visible=bool(payload.get("visible", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class StateView:
    """
    Consumer-friendly view of a single UI state in a context.

    This corresponds to a single entry from `QueryHandler.list_states`
    or `get_state`, where the API returns a "state record" shape:

        {
          "context_id": "...",
          "discovered_at": "...",
          "is_entry": false,
          "is_terminal": false,
          "tags": [ ... ],
          "metadata": { ... },  # tracker-level metadata
          "state": {
            "id": "...",
            "app_id": "...",
            "version": "...",
            "platform": "...",
            "locale": "...",
            "fingerprints": { ... },
            "screenshot_ref": "...",
            "interactive_elements": [ ... ],
            "metadata": { ... }  # state-level metadata
          }
        }
    """

    # Record-level
    context_id: str
    state_id: str
    discovered_at: Optional[str] = None
    is_entry: bool = False
    is_terminal: bool = False
    tags: List[str] = field(default_factory=list)
    tracker_metadata: JSONDict = field(default_factory=dict)

    # State-level
    app_id: str = ""
    version: Optional[str] = None
    platform: Optional[str] = None
    locale: Optional[str] = None
    fingerprints: JSONDict = field(default_factory=dict)
    screenshot_ref: Optional[str] = None
    interactive_elements: List[UIElementHint] = field(default_factory=list)
    state_metadata: JSONDict = field(default_factory=dict)

    @classmethod
    def from_state_record(cls, payload: JSONDict) -> "StateView":
        """
        Build a StateView from a state record dict as returned by
        `QueryHandler._state_record_to_dict` (used in list/get states).
        """
        ctx_id = payload["context_id"]
        discovered_at = payload.get("discovered_at")
        is_entry = bool(payload.get("is_entry", False))
        is_terminal = bool(payload.get("is_terminal", False))
        tags = list(payload.get("tags") or [])
        tracker_meta = dict(payload.get("metadata") or {})

        state_dict = payload["state"]
        state_id = state_dict["id"]
        app_id = state_dict["app_id"]

        interactive_raw = state_dict.get("interactive_elements") or []
        elements = [UIElementHint.from_api(e) for e in interactive_raw]

        return cls(
            context_id=ctx_id,
            state_id=state_id,
            discovered_at=discovered_at,
            is_entry=is_entry,
            is_terminal=is_terminal,
            tags=tags,
            tracker_metadata=tracker_meta,
            app_id=app_id,
            version=state_dict.get("version"),
            platform=state_dict.get("platform"),
            locale=state_dict.get("locale"),
            fingerprints=dict(state_dict.get("fingerprints") or {}),
            screenshot_ref=state_dict.get("screenshot_ref"),
            interactive_elements=elements,
            state_metadata=dict(state_dict.get("metadata") or {}),
        )


# --------------------------------------------------------------------------- #
# Actions & transitions
# --------------------------------------------------------------------------- #


@dataclass
class ActionView:
    """
    Lightweight representation of a user action causing a transition.

    Expected source (from Transition.to_dict()):

        "action": {
          "type": "click",
          "element_id": "el_btn_create",
          "raw_input": null,
          "metadata": { ... }
        }
    """

    type: str
    element_id: Optional[str] = None
    raw_input: Optional[str] = None
    metadata: JSONDict = field(default_factory=dict)

    @classmethod
    def from_api(cls, payload: JSONDict) -> "ActionView":
        return cls(
            type=payload.get("type", "other"),
            element_id=payload.get("element_id"),
            raw_input=payload.get("raw_input"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass
class TransitionView:
    """
    Consumer-friendly view of a transition between two states.

    This corresponds to a transition record as returned by the API:

        {
          "context_id": "...",
          "discovered_at": "...",
          "times_observed": 3,
          "metadata": { ... },  # store-level metadata
          "transition": {
            "id": "...",
            "source_state_id": "...",
            "target_state_id": "...",
            "action": { ... },
            "intent_id": "save-file",
            "confidence": 0.93,
            "metadata": { ... }  # transition-level metadata
          }
        }
    """

    # Record-level
    context_id: str
    transition_id: str
    discovered_at: Optional[str] = None
    times_observed: int = 1
    store_metadata: JSONDict = field(default_factory=dict)

    # Transition-level
    source_state_id: str = ""
    target_state_id: str = ""
    action: ActionView = field(default_factory=lambda: ActionView(type="other"))
    intent_id: Optional[str] = None
    confidence: float = 1.0
    transition_metadata: JSONDict = field(default_factory=dict)

    @classmethod
    def from_transition_record(cls, payload: JSONDict) -> "TransitionView":
        """
        Build a TransitionView from a transition record dict as returned by
        `QueryHandler._transition_record_to_dict`.
        """
        ctx_id = payload["context_id"]
        discovered_at = payload.get("discovered_at")
        times_observed = int(payload.get("times_observed", 1))
        store_meta = dict(payload.get("metadata") or {})

        tr_dict = payload["transition"]
        tr_id = tr_dict["id"]
        src = tr_dict["source_state_id"]
        tgt = tr_dict["target_state_id"]
        act = ActionView.from_api(tr_dict.get("action") or {})
        intent_id = tr_dict.get("intent_id")
        confidence = float(tr_dict.get("confidence", 1.0))
        tr_meta = dict(tr_dict.get("metadata") or {})

        return cls(
            context_id=ctx_id,
            transition_id=tr_id,
            discovered_at=discovered_at,
            times_observed=times_observed,
            store_metadata=store_meta,
            source_state_id=src,
            target_state_id=tgt,
            action=act,
            intent_id=intent_id,
            confidence=confidence,
            transition_metadata=tr_meta,
        )


# --------------------------------------------------------------------------- #
# Path results
# --------------------------------------------------------------------------- #


@dataclass
class PathView:
    """
    Representation of a shortest-path query between two states.

    This corresponds to the payload from the `/contexts/{ctx}/path`
    endpoint:

        {
          "context_id": "...",
          "source_state_id": "...",
          "target_state_id": "...",
          "path": [
            { ...transition record... },
            ...
          ]  # or null if no path
        }
    """

    context_id: str
    source_state_id: str
    target_state_id: str
    transitions: Optional[List[TransitionView]]  # None = no path found

    @classmethod
    def from_api(cls, payload: JSONDict) -> "PathView":
        ctx_id = payload["context_id"]
        src = payload["source_state_id"]
        tgt = payload["target_state_id"]
        raw_path = payload.get("path")

        if raw_path is None:
            transitions: Optional[List[TransitionView]] = None
        else:
            transitions = [
                TransitionView.from_transition_record(tr_record) for tr_record in raw_path
            ]

        return cls(
            context_id=ctx_id,
            source_state_id=src,
            target_state_id=tgt,
            transitions=transitions,
        )

    def is_empty(self) -> bool:
        """
        Return True if there is either no path or the path contains no steps.
        """
        return not self.transitions


# --------------------------------------------------------------------------- #
# Generic API error type (for client-side usage)
# --------------------------------------------------------------------------- #


@dataclass
class APIErrorDetail:
    """
    Structured representation of an error response from the Atlas API.

    Many endpoints return error bodies like:

        {
          "error": "ingest_error",
          "detail": "Context 'foo' does not exist"
        }

    This type is independent of HTTP status codes; a client is expected
    to pair it with status as needed.
    """

    code: str
    detail: Optional[str] = None

    @classmethod
    def from_api(cls, payload: JSONDict) -> "APIErrorDetail":
        return cls(
            code=payload.get("error", "unknown_error"),
            detail=payload.get("detail"),
        )
