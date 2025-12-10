"""
Probe interface for the Guidance Client.

This module defines an abstract interface for *local probes* that
capture information about the user's current UI state.

A probe is platform-specific (web, desktop, mobile, etc.) and runs
on the user's machine. It is responsible for:

- Inspecting the current UI (DOM, accessibility tree, etc.).
- Producing stable fingerprints compatible with the Atlas model.
- Optionally exposing visible UI elements and metadata.

The guidance engine consumes these snapshots and matches them against
Atlas/SDK views (StateView, UIElementHint, etc.). This module is
deliberately dependency-free and contains *no* platform-specific code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from abc import ABC, abstractmethod


class ProbingError(Exception):
    """
    Raised when the probe cannot capture the current UI snapshot.

    Probes should raise this when something goes wrong locally
    (e.g. accessibility APIs unavailable, permissions denied, etc.).
    """


# --------------------------------------------------------------------------- #
# Snapshot models
# --------------------------------------------------------------------------- #


@dataclass
class BoundingBoxSnapshot:
    """
    Lightweight bounding box representation for local elements.

    Coordinates are expressed in the coordinate system natural to the
    probe implementation (e.g. screen coordinates or window-relative
    coordinates). The guidance engine does not assume a specific
    coordinate space; it only forwards these values to presentation
    layers (overlay, etc.).
    """

    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> Dict[str, int]:
        return {
            "x": int(self.x),
            "y": int(self.y),
            "width": int(self.width),
            "height": int(self.height),
        }


@dataclass
class LocalElementSnapshot:
    """
    Representation of a UI element as seen by a local probe.

    This is intentionally similar to UIElementHint but is decoupled
    from the Atlas/SDK types so that probes can use whatever local
    identifiers and metadata they need.
    """

    # Local identifier (e.g. accessibility node ID, DOM node handle).
    local_id: Optional[str] = None

    # Role/type of the element (“button”, “link”, “textfield”, etc.).
    role: Optional[str] = None

    # Visible label or text associated with the element, if any.
    label: Optional[str] = None

    # Optional bounding box of the element on screen/window.
    bounding_box: Optional[BoundingBoxSnapshot] = None

    # Optional hierarchical path in the local tree (DOM path, AX path, etc.).
    path: Optional[str] = None

    # Whether the element is currently enabled and visible, if known.
    enabled: Optional[bool] = None
    visible: Optional[bool] = None

    # Arbitrary implementation-specific metadata.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "local_id": self.local_id,
            "role": self.role,
            "label": self.label,
            "bounding_box": (
                self.bounding_box.to_dict() if self.bounding_box else None
            ),
            "path": self.path,
            "enabled": self.enabled,
            "visible": self.visible,
            "metadata": dict(self.metadata),
        }


@dataclass
class LocalUISnapshot:
    """
    A snapshot of the current UI as seen by a probe.

    This is the primary input to the state matching logic. The guidance
    engine expects fingerprints to be compatible with the keys used in
    `UIState.fingerprints`, such as "structural", "semantic", "visual".
    """

    # Optional hint of which context this snapshot belongs to.
    # For many implementations this may be None; the engine or caller
    # chooses the Atlas context separately.
    context_hint: Optional[str] = None

    # Fingerprints describing the current UI configuration.
    # Typical keys: "structural", "semantic", "visual".
    fingerprints: Dict[str, str] = field(default_factory=dict)

    # Optional list of elements visible in the current UI.
    elements: List[LocalElementSnapshot] = field(default_factory=list)

    # Arbitrary metadata (probe name, timestamps, window title, etc.).
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_hint": self.context_hint,
            "fingerprints": dict(self.fingerprints),
            "elements": [el.to_dict() for el in self.elements],
            "metadata": dict(self.metadata),
        }


# --------------------------------------------------------------------------- #
# Probe interface
# --------------------------------------------------------------------------- #


class GuidanceProbe(ABC):
    """
    Abstract base class for guidance probes.

    A concrete implementation is responsible for connecting to a
    specific platform (browser, OS accessibility API, etc.) and
    returning LocalUISnapshot instances.

    Probes must be *side-effect free* with respect to the target app:
    they observe, but do not click or type.
    """

    @abstractmethod
    def capture_snapshot(self) -> LocalUISnapshot:
        """
        Capture the current UI snapshot.

        Returns:
            LocalUISnapshot with fingerprints and (optionally) elements.

        Raises:
            ProbingError if the snapshot cannot be captured.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Utility / default implementations
# --------------------------------------------------------------------------- #


@dataclass
class NullProbe(GuidanceProbe):
    """
    A trivial probe that returns an empty snapshot.

    This is useful for:

    - Testing the guidance engine without a real UI.
    - Scenarios where the current state_id is already known by some
      out-of-band mechanism and no local inspection is needed.

    By default, it returns a snapshot with empty fingerprints and
    elements. Callers may override `base_snapshot` to inject custom
    data.
    """

    base_snapshot: LocalUISnapshot = field(default_factory=LocalUISnapshot)

    def capture_snapshot(self) -> LocalUISnapshot:
        # Return a shallow copy so callers can modify it without
        # affecting the stored base_snapshot.
        return LocalUISnapshot(
            context_hint=self.base_snapshot.context_hint,
            fingerprints=dict(self.base_snapshot.fingerprints),
            elements=list(self.base_snapshot.elements),
            metadata=dict(self.base_snapshot.metadata),
        )


__all__ = [
    "ProbingError",
    "BoundingBoxSnapshot",
    "LocalElementSnapshot",
    "LocalUISnapshot",
    "GuidanceProbe",
    "NullProbe",
]
