"""
Windows UIA Adapter for Theseus.

This module converts a tree of Windows UI Automation (UIA) elements into a
generic UIState.

It is designed to work with `pywinauto` using the "uia" backend. The driver
is expected to traverse the live application and produce a `WinNode` tree,
which this adapter then consumes to produce fingerprints and standard
Ariane elements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from common.models.ui_state import (
    BoundingBox,
    InteractiveElement,
    Platform,
    UIState,
)
from ...core.fingerprint_engine import FingerprintEngine


# --------------------------------------------------------------------------- #
# Windows Node Model
# --------------------------------------------------------------------------- #


@dataclass
class WinNode:
    """
    Intermediate representation of a Windows UIA element.

    The Windows driver should traverse the raw `pywinauto` wrappers and
    map them into this clean data structure. This avoids leaking COM objects
    or pywinauto internals into the core logic.
    """

    # Identification
    control_type: str  # e.g. "Button", "Edit", "Window", "Pane"
    class_name: str    # e.g. "Button", "TextBox"
    automation_id: str = ""
    name: str = ""     # Visible text or accessible name

    # State flags
    is_enabled: bool = True
    is_visible: bool = True
    is_keyboard_focusable: bool = False
    is_selected: bool = False
    
    # Geometry (Screen coordinates)
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    # Content
    value: Optional[str] = None  # Current text content if applicable

    # Structure
    children: List["WinNode"] = field(default_factory=list)
    
    # Metadata
    framework_id: str = ""  # e.g. "WPF", "Win32", "WinForm"
    metadata: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Adapter Configuration
# --------------------------------------------------------------------------- #


@dataclass
class WinAdapterConfig:
    """
    Configuration for UiaAdapter.
    """

    # Control types that are inherently interactive
    interactive_types: List[str] = field(
        default_factory=lambda: [
            "Button",
            "CheckBox",
            "RadioButton",
            "ComboBox",
            "Edit",
            "Document",
            "Hyperlink",
            "MenuItem",
            "TabItem",
            "ListItem",
            "TreeItem",
            "Slider",
            "Spinner",
            "SplitButton",
            "ToggleButton",
        ]
    )

    # Mapping UIA ControlType to generic Ariane roles
    role_mapping: Dict[str, str] = field(
        default_factory=lambda: {
            "Button": "button",
            "CheckBox": "checkbox",
            "RadioButton": "radio",
            "ComboBox": "combobox",
            "Edit": "textbox",
            "Document": "textbox",
            "Hyperlink": "link",
            "MenuItem": "menuitem",
            "TabItem": "tab",
            "ListItem": "listitem",
            "TreeItem": "treeitem",
            "Window": "window",
            "Group": "group",
            "Text": "text",
            "Image": "image",
            "Pane": "pane",
        }
    )


# --------------------------------------------------------------------------- #
# Adapter Implementation
# --------------------------------------------------------------------------- #


class UiaAdapter:
    """
    Adapter that converts a WinNode tree into a UIState.
    """

    def __init__(
        self,
        *,
        fingerprint_engine: Optional[FingerprintEngine] = None,
        config: Optional[WinAdapterConfig] = None,
    ) -> None:
        self._fingerprint_engine = fingerprint_engine
        self._config = config or WinAdapterConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def build_ui_state(
        self,
        *,
        root: WinNode,
        app_id: str,
        window_title: Optional[str] = None,
        screenshot_ref: Optional[str] = None,
        locale: Optional[str] = None,
        version: Optional[str] = None,
    ) -> UIState:
        """
        Build a UIState from a WinNode tree.

        Args:
            root: Root node of the window hierarchy.
            app_id: Logical application ID.
            window_title: Title of the main window.
            screenshot_ref: Reference to a captured screenshot.
            locale: Locale string.
            version: App version.

        Returns:
            UIState with populated interactive elements and fingerprints.
        """
        interactive_elements: List[InteractiveElement] = []

        # 1. Build structural tree dict for fingerprinting
        ui_tree_dict = self._node_to_dict(root)

        # 2. Collect text content
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
            platform=Platform.WINDOWS,
            locale=locale,
            fingerprints={},
            screenshot_ref=screenshot_ref,
            interactive_elements=interactive_elements,
            metadata={
                "window_title": window_title,
                "framework": root.framework_id,
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

    def _node_to_dict(self, node: WinNode) -> Dict[str, Any]:
        """
        Convert WinNode to a stable dictionary for structural hashing.
        """
        return {
            "type": node.control_type,
            "class": node.class_name,
            "id": node.automation_id,
            "name": node.name,  # Included as it's often the only stable identifier
            "flags": {
                "enabled": node.is_enabled,
                "focusable": node.is_keyboard_focusable,
            },
            "children": [self._node_to_dict(c) for c in node.children],
        }

    # ------------------------------------------------------------------ #
    # Text Collection
    # ------------------------------------------------------------------ #

    def _collect_text(self, node: WinNode) -> str:
        """
        Recursively collect visible text.
        """
        parts = []
        if node.is_visible:
            if node.name:
                parts.append(node.name.strip())
            if node.value:
                parts.append(node.value.strip())

        for child in node.children:
            parts.append(self._collect_text(child))

        return " ".join(filter(None, parts))

    # ------------------------------------------------------------------ #
    # Interactive Element Extraction
    # ------------------------------------------------------------------ #

    def _collect_interactive_elements(
        self,
        *,
        node: WinNode,
        elements: List[InteractiveElement],
        path_prefix: str,
        index: int,
    ) -> None:
        """
        Walk the tree and extract InteractiveElements.
        """
        path_here = f"{path_prefix}{node.control_type}[{index}]"

        if self._is_interactive(node):
            el_id = self._make_element_id(node, path_here)
            role = self._derive_role(node)
            label = self._derive_label(node)
            bbox = self._derive_bounds(node)

            elements.append(
                InteractiveElement(
                    id=el_id,
                    role=role,
                    label=label,
                    bounding_box=bbox,
                    path=path_here,
                    enabled=node.is_enabled,
                    visible=node.is_visible,
                    metadata={
                        "control_type": node.control_type,
                        "automation_id": node.automation_id,
                        "class_name": node.class_name,
                        "framework": node.framework_id,
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

    def _is_interactive(self, node: WinNode) -> bool:
        """
        Check if node is interactive based on type and state.
        """
        if not node.is_visible:
            return False

        # If it has a keyboard focus, it's almost certainly interactive
        if node.is_keyboard_focusable:
            return True

        # Check explicit interactive types
        if node.control_type in self._config.interactive_types:
            return True

        return False

    def _derive_role(self, node: WinNode) -> str:
        """Map UIA ControlType to generic Ariane role."""
        return self._config.role_mapping.get(node.control_type, "other")

    def _derive_label(self, node: WinNode) -> Optional[str]:
        """
        Derive label from name or value.
        """
        if node.name and node.name.strip():
            return node.name.strip()
        
        # For editable fields, the value might be the label if placeholder
        # but usually it's the content. We prioritize name.
        if node.value and node.value.strip():
            # Only use value as label if it's short (likely a label/placeholder)
            if len(node.value) < 50:
                return node.value.strip()
                
        return None

    def _derive_bounds(self, node: WinNode) -> Optional[BoundingBox]:
        """Convert node coordinates to BoundingBox."""
        if node.width > 0 and node.height > 0:
            return BoundingBox(
                x=node.x,
                y=node.y,
                width=node.width,
                height=node.height,
            )
        return None

    def _make_element_id(self, node: WinNode, path: str) -> str:
        """
        Construct a stable ID.
        Prefer AutomationId if present, otherwise fallback to name+type or path.
        """
        if node.automation_id:
            return f"id:{node.automation_id}"
            
        # Fallback: Name + ControlType is reasonably stable in Windows menus
        if node.name:
            sanitized_name = "".join(c for c in node.name if c.isalnum())
            return f"name:{node.control_type}_{sanitized_name}"
            
        return f"path:{path}"

    def _count_nodes(self, node: WinNode) -> int:
        count = 1
        for child in node.children:
            count += self._count_nodes(child)
        return count