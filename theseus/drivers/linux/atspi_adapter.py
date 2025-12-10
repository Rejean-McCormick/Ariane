"""
Linux AT-SPI Adapter for Theseus.

This module converts a tree of AT-SPI (Assistive Technology Service Provider 
Interface) nodes into a generic UIState.

It is designed to work with drivers using `pyatspi2`. The driver is expected
to traverse the live application and produce an `AtspiNode` tree, which this
adapter then consumes to produce fingerprints and standard Ariane elements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from common.models.ui_state import (
    BoundingBox,
    InteractiveElement,
    Platform,
    UIState,
)
from ...core.fingerprint_engine import FingerprintEngine


# --------------------------------------------------------------------------- #
# AT-SPI Node Model
# --------------------------------------------------------------------------- #


@dataclass
class AtspiNode:
    """
    Intermediate representation of a Linux AT-SPI object.

    The Linux driver should traverse the raw `pyatspi` accessible objects
    and map them into this clean data structure. This avoids passing complex
    COM/DBus objects into the core logic and allows for easier testing.
    """

    # Identification
    role_name: str  # e.g. "push button", "frame", "menu"
    name: str       # Accessible name/label
    description: str = ""
    
    # State flags (converted from pyatspi.StateType sets)
    states: Set[str] = field(default_factory=set)
    # e.g. {"enabled", "visible", "showing", "focusable", "focused", "checked"}

    # Geometry (Screen coordinates)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    # Content
    text_content: Optional[str] = None  # Text interface content
    value: Optional[str] = None         # Value interface content

    # Structure
    children: List["AtspiNode"] = field(default_factory=list)
    
    # Metadata
    toolkit_name: Optional[str] = None
    app_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Adapter Configuration
# --------------------------------------------------------------------------- #


@dataclass
class AtspiAdapterConfig:
    """
    Configuration for AtspiAdapter.
    """

    # Roles that are inherently interactive
    interactive_roles: List[str] = field(
        default_factory=lambda: [
            "push button",
            "toggle button",
            "check box",
            "radio button",
            "menu item",
            "check menu item",
            "radio menu item",
            "text",
            "entry",
            "password text",
            "combo box",
            "list item",
            "page tab",
            "slider",
            "spin button",
            "link",
        ]
    )

    # Mapping AT-SPI role names to generic Ariane roles
    role_mapping: Dict[str, str] = field(
        default_factory=lambda: {
            "push button": "button",
            "toggle button": "toggle",
            "check box": "checkbox",
            "radio button": "radio",
            "menu item": "menuitem",
            "text": "textbox",
            "entry": "textbox",
            "password text": "textbox",
            "page tab": "tab",
            "combo box": "combobox",
            "list item": "listitem",
            "label": "text",
            "frame": "window",
            "dialog": "dialog",
        }
    )


# --------------------------------------------------------------------------- #
# Adapter Implementation
# --------------------------------------------------------------------------- #


class AtspiAdapter:
    """
    Adapter that converts an AtspiNode tree into a UIState.
    """

    def __init__(
        self,
        *,
        fingerprint_engine: Optional[FingerprintEngine] = None,
        config: Optional[AtspiAdapterConfig] = None,
    ) -> None:
        self._fingerprint_engine = fingerprint_engine
        self._config = config or AtspiAdapterConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def build_ui_state(
        self,
        *,
        root: AtspiNode,
        app_id: str,
        window_title: Optional[str] = None,
        screenshot_ref: Optional[str] = None,
        locale: Optional[str] = None,
        version: Optional[str] = None,
    ) -> UIState:
        """
        Build a UIState from an AtspiNode tree.

        Args:
            root: Root node of the accessibility tree (usually the Application or Window).
            app_id: Logical application ID.
            window_title: Title of the main window (metadata).
            screenshot_ref: Reference to a captured screenshot.
            locale: Locale string.
            version: App version.

        Returns:
            UIState with populated interactive elements and fingerprints.
        """
        interactive_elements: List[InteractiveElement] = []

        # 1. Build structural tree dict for fingerprinting
        ui_tree_dict = self._node_to_dict(root)

        # 2. Collect semantic text
        text_content = self._collect_text(root)

        # 3. Extract elements
        self._collect_interactive_elements(
            node=root,
            elements=interactive_elements,
            path_prefix="/",
            index=0
        )

        state = UIState(
            id="",  # To be populated by StateTracker
            app_id=app_id,
            version=version,
            platform=Platform.LINUX,
            locale=locale,
            fingerprints={},
            screenshot_ref=screenshot_ref,
            interactive_elements=interactive_elements,
            metadata={
                "window_title": window_title,
                "toolkit": root.toolkit_name,
                "node_count": self._count_nodes(root),
                "text_chars": len(text_content),
            },
        )

        # 4. Compute fingerprints
        if self._fingerprint_engine is not None:
            self._fingerprint_engine.fingerprint_state(
                ui_state=state,
                ui_tree=ui_tree_dict,
                screenshot_bytes=None,
                text_content=text_content or None,
            )

        return state

    # ------------------------------------------------------------------ #
    # Tree → Dict Conversion
    # ------------------------------------------------------------------ #

    def _node_to_dict(self, node: AtspiNode) -> Dict[str, Any]:
        """
        Convert AtspiNode to a stable dictionary for structural hashing.
        """
        # We only include stable attributes. 
        # Coordinate geometry is intentionally excluded to allow
        # for window resizing without breaking the structural hash.
        return {
            "role": node.role_name,
            "name": node.name,
            "states": sorted(list(node.states)),  # Sorted list for stability
            "children": [self._node_to_dict(c) for c in node.children],
        }

    # ------------------------------------------------------------------ #
    # Text Collection
    # ------------------------------------------------------------------ #

    def _collect_text(self, node: AtspiNode) -> str:
        """
        Recursively collect visible text for semantic hashing.
        """
        parts = []
        
        # Consider visible text
        if "visible" in node.states or "showing" in node.states:
            if node.name:
                parts.append(node.name.strip())
            if node.text_content:
                parts.append(node.text_content.strip())
            if node.description:
                parts.append(node.description.strip())

        for child in node.children:
            parts.append(self._collect_text(child))

        return " ".join(filter(None, parts))

    # ------------------------------------------------------------------ #
    # Interactive Element Extraction
    # ------------------------------------------------------------------ #

    def _collect_interactive_elements(
        self,
        *,
        node: AtspiNode,
        elements: List[InteractiveElement],
        path_prefix: str,
        index: int,
    ) -> None:
        """
        Walk the tree and extract InteractiveElements.
        """
        # Sanitize role name for path
        safe_role = node.role_name.replace(" ", "_")
        path_here = f"{path_prefix}{safe_role}[{index}]"

        if self._is_interactive(node):
            el_id = self._make_element_id(node, path_here)
            role = self._derive_role(node)
            label = self._derive_label(node)
            bbox = self._derive_bounds(node)
            
            # Determine flags
            enabled = "enabled" in node.states and "sensitive" in node.states
            visible = "visible" in node.states or "showing" in node.states

            elements.append(
                InteractiveElement(
                    id=el_id,
                    role=role,
                    label=label,
                    bounding_box=bbox,
                    path=path_here,
                    enabled=enabled,
                    visible=visible,
                    metadata={
                        "atspi_role": node.role_name,
                        "description": node.description,
                        "states": list(node.states),
                    },
                )
            )

        # Recurse
        for i, child in enumerate(node.children):
            self._collect_interactive_elements(
                node=child,
                elements=elements,
                path_prefix=path_here + "/",
                index=i,
            )

    # ------------------------------------------------------------------ #
    # Heuristics & Helpers
    # ------------------------------------------------------------------ #

    def _is_interactive(self, node: AtspiNode) -> bool:
        """
        Check if node is interactive based on role and states.
        """
        # Must be visible to be interactive
        if "visible" not in node.states and "showing" not in node.states:
            return False

        # Check explicit interactive roles
        if node.role_name in self._config.interactive_roles:
            return True

        # Check 'focusable' state (common indicator of interactivity)
        if "focusable" in node.states:
            return True

        return False

    def _derive_role(self, node: AtspiNode) -> str:
        """Map AT-SPI role to generic Ariane role."""
        return self._config.role_mapping.get(node.role_name, "other")

    def _derive_label(self, node: AtspiNode) -> Optional[str]:
        """
        Derive label from name, text interface, or description.
        """
        if node.name and node.name.strip():
            return node.name.strip()
        
        if node.text_content and node.text_content.strip():
            # For small text content, use it as label
            if len(node.text_content) < 50:
                return node.text_content.strip()
                
        if node.description and node.description.strip():
            return node.description.strip()
            
        return None

    def _derive_bounds(self, node: AtspiNode) -> Optional[BoundingBox]:
        """Convert node coordinates to BoundingBox."""
        if node.width > 0 and node.height > 0:
            return BoundingBox(
                x=node.x,
                y=node.y,
                width=node.width,
                height=node.height,
            )
        return None

    def _make_element_id(self, node: AtspiNode, path: str) -> str:
        """
        Construct a stable ID. 
        Linux AT-SPI doesn't always have a stable 'resource-id' equivalent,
        so we often rely on the path or a combination of Name+Role.
        """
        # If the element has a specific name/label, we use that to make it
        # resilient to reordering.
        if node.name:
            sanitized_name = "".join(c for c in node.name if c.isalnum())
            safe_role = node.role_name.replace(" ", "_")
            return f"name:{safe_role}_{sanitized_name}"
            
        return f"path:{path}"

    def _count_nodes(self, node: AtspiNode) -> int:
        count = 1
        for child in node.children:
            count += self._count_nodes(child)
        return count