"""
Android Accessibility Adapter for Theseus.

This module converts a tree of Android accessibility nodes into a generic
UIState. It handles:

- Parsing Android-style bounds strings (e.g. "[0,0][1080,1920]").
- Mapping Android UI classes (android.widget.Button) to Ariane roles.
- Identifying interactive elements based on accessibility flags.
- Computing fingerprints via the FingerprintEngine.

This adapter is driver-agnostic; it expects a standardized `AndroidNode`
tree which the `device_session.py` is responsible for producing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from common.models.ui_state import (
    BoundingBox,
    InteractiveElement,
    Platform,
    UIState,
)
from ...core.fingerprint_engine import FingerprintEngine


# --------------------------------------------------------------------------- #
# Android Node Model
# --------------------------------------------------------------------------- #


@dataclass
class AndroidNode:
    """
    Intermediate representation of an Android AccessibilityNodeInfo.

    Drivers (uiautomator2, Appium, etc.) should map their native node
    format into this structure before passing it to the adapter.
    """

    class_name: str
    package_name: Optional[str] = None
    resource_id: Optional[str] = None
    content_desc: Optional[str] = None
    text: Optional[str] = None
    bounds: str = "[0,0][0,0]"  # Standard Android bounds string
    
    # Boolean flags from AccessibilityNodeInfo
    clickable: bool = False
    checked: bool = False
    checkable: bool = False
    editable: bool = False
    enabled: bool = True
    focusable: bool = False
    focused: bool = False
    scrollable: bool = False
    selected: bool = False
    visible_to_user: bool = True

    children: List["AndroidNode"] = field(default_factory=list)
    
    # Any extra raw attributes to preserve in metadata
    attributes: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Adapter Configuration
# --------------------------------------------------------------------------- #


@dataclass
class AndroidAdapterConfig:
    """
    Configuration for AccessibilityAdapter.
    """

    # Classes that are implicitly considered interactive even if flags say otherwise
    interactive_classes: List[str] = field(
        default_factory=lambda: [
            "android.widget.Button",
            "android.widget.ImageButton",
            "android.widget.EditText",
            "android.widget.CheckBox",
            "android.widget.RadioButton",
            "android.widget.Switch",
            "android.widget.SeekBar",
            "android.widget.Spinner",
        ]
    )

    # Specific mapping from Android class to generic UI role
    class_role_map: Dict[str, str] = field(
        default_factory=lambda: {
            "android.widget.Button": "button",
            "android.widget.ImageButton": "button",
            "android.widget.EditText": "textbox",
            "android.widget.CheckBox": "checkbox",
            "android.widget.RadioButton": "radio",
            "android.widget.Switch": "toggle",
            "android.widget.SeekBar": "slider",
            "android.widget.ImageView": "image",
            "android.widget.TextView": "text",
            "android.view.View": "generic",
        }
    )


# --------------------------------------------------------------------------- #
# Adapter Implementation
# --------------------------------------------------------------------------- #


class AccessibilityAdapter:
    """
    Adapter that converts an AndroidNode tree into a UIState.
    """

    def __init__(
        self,
        *,
        fingerprint_engine: Optional[FingerprintEngine] = None,
        config: Optional[AndroidAdapterConfig] = None,
    ) -> None:
        self._fingerprint_engine = fingerprint_engine
        self._config = config or AndroidAdapterConfig()
        
        # Regex for parsing bounds: [x1,y1][x2,y2]
        self._bounds_pattern = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def build_ui_state(
        self,
        *,
        root: AndroidNode,
        app_id: str,
        activity: Optional[str] = None,
        screenshot_ref: Optional[str] = None,
        locale: Optional[str] = None,
        version: Optional[str] = None,
    ) -> UIState:
        """
        Build a UIState from an AndroidNode tree.

        Args:
            root: Root node of the current window hierarchy.
            app_id: Logical application ID.
            activity: Current Android Activity name (e.g. .MainActivity),
                      stored in metadata.
            screenshot_ref: Reference to a captured screenshot.
            locale: Locale string.
            version: App version.

        Returns:
            UIState with populated interactive elements and fingerprints.
        """
        interactive_elements: List[InteractiveElement] = []
        
        # 1. Convert to dict tree for structural fingerprinting
        ui_tree_dict = self._node_to_dict(root)
        
        # 2. Collect text content for semantic fingerprinting
        text_content = self._collect_text(root)

        # 3. Flatten tree to find interactive elements
        self._collect_interactive_elements(
            node=root,
            elements=interactive_elements,
            path_prefix="/",
            index=0
        )

        state = UIState(
            id="",  # To be filled by StateTracker
            app_id=app_id,
            version=version,
            platform=Platform.ANDROID,
            locale=locale,
            fingerprints={},
            screenshot_ref=screenshot_ref,
            interactive_elements=interactive_elements,
            metadata={
                "activity": activity,
                "package": root.package_name,
                "node_count": self._count_nodes(root),
                "text_chars": len(text_content),
            },
        )

        # 4. Compute fingerprints
        if self._fingerprint_engine is not None:
            self._fingerprint_engine.fingerprint_state(
                ui_state=state,
                ui_tree=ui_tree_dict,
                screenshot_bytes=None,  # Bytes handled by driver if needed
                text_content=text_content or None,
            )

        return state

    # ------------------------------------------------------------------ #
    # Tree → Dict Conversion (Structural Hashing)
    # ------------------------------------------------------------------ #

    def _node_to_dict(self, node: AndroidNode) -> Dict[str, Any]:
        """
        Convert AndroidNode to a stable dictionary for hashing.
        We exclude volatile fields like 'focused' or 'selected' from
        the structural hash to ensure stability across interactions.
        """
        return {
            "class": node.class_name,
            "res_id": node.resource_id,
            "desc": node.content_desc,
            "flags": {
                "clickable": node.clickable,
                "scrollable": node.scrollable,
                "editable": node.editable,
            },
            "children": [self._node_to_dict(c) for c in node.children],
        }

    # ------------------------------------------------------------------ #
    # Text Collection (Semantic Hashing)
    # ------------------------------------------------------------------ #

    def _collect_text(self, node: AndroidNode) -> str:
        """
        Recursively collect visible text and content descriptions.
        """
        parts = []
        if node.text:
            parts.append(node.text.strip())
        if node.content_desc:
            parts.append(node.content_desc.strip())
        
        for child in node.children:
            parts.append(self._collect_text(child))
            
        return " ".join(filter(None, parts))

    # ------------------------------------------------------------------ #
    # Interactive Element Extraction
    # ------------------------------------------------------------------ #

    def _collect_interactive_elements(
        self,
        *,
        node: AndroidNode,
        elements: List[InteractiveElement],
        path_prefix: str,
        index: int,
    ) -> None:
        """
        Walk the tree and extract InteractiveElements.
        
        path is constructed as: /hierarchy/android.widget.FrameLayout[0]/...
        """
        # Simplify class name for path (remove package)
        simple_class = node.class_name.split('.')[-1]
        path_here = f"{path_prefix}{simple_class}[{index}]"

        if self._is_interactive(node):
            el_id = self._make_element_id(node, path_here)
            label = self._derive_label(node)
            role = self._derive_role(node)
            bbox = self._parse_bounds(node.bounds)

            elements.append(
                InteractiveElement(
                    id=el_id,
                    role=role,
                    label=label,
                    bounding_box=bbox,
                    path=path_here,
                    enabled=node.enabled,
                    visible=node.visible_to_user,
                    metadata={
                        "resource_id": node.resource_id,
                        "class": node.class_name,
                        "content_desc": node.content_desc,
                        "bounds_str": node.bounds,
                        "checked": node.checked,
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

    def _is_interactive(self, node: AndroidNode) -> bool:
        """
        Determine if a node is interactive based on flags and class.
        """
        if not node.visible_to_user:
            return False

        # If strict flags say yes
        if node.clickable or node.checkable or node.editable or node.scrollable:
            return True

        # If class implies interactivity (sometimes flags are missing/wrong in dumps)
        if node.class_name in self._config.interactive_classes:
            return True

        return False

    def _derive_role(self, node: AndroidNode) -> str:
        """Map Android class to Ariane role."""
        return self._config.class_role_map.get(node.class_name, "other")

    def _derive_label(self, node: AndroidNode) -> Optional[str]:
        """Prioritize text, then content-desc, then resource-id."""
        if node.text and node.text.strip():
            return node.text.strip()
        if node.content_desc and node.content_desc.strip():
            return node.content_desc.strip()
        if node.resource_id:
            # Fallback: use the ID name (e.g. "com.app:id/submit_btn" -> "submit_btn")
            if ":id/" in node.resource_id:
                return node.resource_id.split(":id/")[-1]
            return node.resource_id
        return None

    def _make_element_id(self, node: AndroidNode, path: str) -> str:
        """
        Create a stable ID.
        Prefer resource_id if available, otherwise fallback to tree path.
        """
        if node.resource_id:
            return f"id:{node.resource_id}"
        return f"path:{path}"

    def _parse_bounds(self, bounds_str: str) -> Optional[BoundingBox]:
        """
        Parse Android bounds string "[x1,y1][x2,y2]" into BoundingBox.
        """
        if not bounds_str:
            return None
            
        match = self._bounds_pattern.match(bounds_str)
        if not match:
            return None

        x1, y1, x2, y2 = map(int, match.groups())
        return BoundingBox(
            x=x1,
            y=y1,
            width=x2 - x1,
            height=y2 - y1,
        )

    def _count_nodes(self, node: AndroidNode) -> int:
        count = 1
        for child in node.children:
            count += self._count_nodes(child)
        return count