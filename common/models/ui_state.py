"""
UI state model for Ariane.

This module defines the in-memory representation of a single UI state
(a specific screen or configuration) and its interactive elements.

A UI state is what Theseus discovers and what Atlas stores as a node
in the UI graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class Platform(str, Enum):
    """Logical platform identifier for the state."""

    WEB = "web"
    WINDOWS = "windows"
    LINUX = "linux"
    ANDROID = "android"
    MACOS = "macos"
    OTHER = "other"


@dataclass(frozen=True)
class BoundingBox:
    """
    Screen-space bounding box for a UI element.

    Coordinates are relative to the top-left corner of the window/screen
    used by the driver, in logical pixels.
    """

    x: int
    y: int
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        """Return (x, y, width, height)."""
        return self.x, self.y, self.width, self.height


@dataclass
class InteractiveElement:
    """
    An interactive element within a UI state.

    This represents things like buttons, links, inputs, menu items, etc.
    """

    id: str
    role: str  # e.g. "button", "menuitem", "textbox", "checkbox"
    label: Optional[str] = None
    bounding_box: Optional[BoundingBox] = None
    path: Optional[str] = None  # platform-specific accessibility path
    enabled: bool = True
    visible: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the element to a JSON-friendly dict."""
        data = asdict(self)
        if self.bounding_box is not None:
            data["bounding_box"] = {
                "x": self.bounding_box.x,
                "y": self.bounding_box.y,
                "width": self.bounding_box.width,
                "height": self.bounding_box.height,
            }
        return data


@dataclass
class UIState:
    """
    Representation of a single UI state.

    Attributes:
        id:
            Stable identifier for the state (typically derived from hashes).
        app_id:
            Identifier for the application (e.g. "photoshop", "firefox").
        version:
            Optional application version string.
        platform:
            Logical platform (web, windows, linux, android, etc.).
        locale:
            Optional locale tag, e.g. "en-US".
        fingerprints:
            A collection of hashes/identifiers for this state, such as
            {"visual_hash": "...", "dom_hash": "..."}.
        screenshot_ref:
            Optional reference to a screenshot (path, URL, or opaque ID).
        interactive_elements:
            List of interactive elements discovered in this state.
        metadata:
            Arbitrary additional metadata (driver-specific details, tags, etc.).
    """

    id: str
    app_id: str
    version: Optional[str] = None
    platform: Platform = Platform.OTHER
    locale: Optional[str] = None

    fingerprints: Dict[str, str] = field(default_factory=dict)
    screenshot_ref: Optional[str] = None

    interactive_elements: List[InteractiveElement] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --- element lookup helpers ------------------------------------------------

    def get_element(self, element_id: str) -> Optional[InteractiveElement]:
        """Return the element with the given id, or None if not found."""
        for el in self.interactive_elements:
            if el.id == element_id:
                return el
        return None

    def find_elements_by_role(self, role: str) -> List[InteractiveElement]:
        """Return all elements whose role matches (case-insensitive)."""
        role_lower = role.lower()
        return [el for el in self.interactive_elements if el.role.lower() == role_lower]

    def find_elements_by_label(self, label: str) -> List[InteractiveElement]:
        """
        Return all elements whose label matches the given label
        (case-insensitive, trimmed).
        """
        key = _normalize(label)
        result: List[InteractiveElement] = []
        for el in self.interactive_elements:
            if el.label is None:
                continue
            if _normalize(el.label) == key:
                result.append(el)
        return result

    # --- serialization ---------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the state to a JSON-friendly dict.

        This is intended as a low-level representation that Atlas can
        persist directly, or that can be further transformed into JSON-LD.
        """
        return {
            "id": self.id,
            "app_id": self.app_id,
            "version": self.version,
            "platform": self.platform.value,
            "locale": self.locale,
            "fingerprints": dict(self.fingerprints),
            "screenshot_ref": self.screenshot_ref,
            "interactive_elements": [el.to_dict() for el in self.interactive_elements],
            "metadata": dict(self.metadata),
        }


def _normalize(s: str) -> str:
    return " ".join(s.strip().lower().split())
