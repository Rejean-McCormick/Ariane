"""
DOM adapter for Theseus (web driver).

This module provides a small, dependency-free abstraction for turning a
web DOM snapshot into a generic UIState plus a structural tree suitable
for fingerprinting.

It does **not** talk to a browser directly. Another layer (e.g.
browser_session.py) is responsible for:

    - Driving the browser (Selenium/Playwright/etc.).
    - Building a DOMSnapshotNode tree from the live DOM.
    - Optionally capturing screenshots.

The DOMAdapter then:

    - Walks the DOMSnapshotNode tree.
    - Extracts interactive elements.
    - Builds a UIState instance.
    - Optionally uses FingerprintEngine to compute fingerprints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from common.models.ui_state import (
    BoundingBox,
    InteractiveElement,
    Platform,
    UIState,
)

# Relative import assuming package structure:
# theseus/
#   core/fingerprint_engine.py
#   drivers/web/dom_adapter.py
from ...core.fingerprint_engine import FingerprintEngine


# --------------------------------------------------------------------------- #
# DOM snapshot model
# --------------------------------------------------------------------------- #


@dataclass
class DOMSnapshotNode:
    """
    Minimal, framework-agnostic DOM snapshot node.

    This is a lightweight representation that browser-specific code can
    populate from Selenium, Playwright, or any other source.

    Attributes:
        tag:
            Lowercase tag name (e.g. "button", "a", "input").
        attributes:
            Mapping of attribute name -> value (e.g. {"id": "submit-btn"}).
        text:
            Text content directly associated with this node (no children).
        children:
            Child nodes in DOM order.
    """

    tag: str
    attributes: Dict[str, str] = field(default_factory=dict)
    text: str = ""
    children: List["DOMSnapshotNode"] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# DOM adapter
# --------------------------------------------------------------------------- #


@dataclass
class DOMAdapterConfig:
    """
    Configuration for DOMAdapter.

    Attributes:
        interactive_tags:
            Tag names that are treated as inherently interactive.
        role_interactive_values:
            ARIA role values that are treated as interactive.
        include_non_interactive_labels:
            If True, non-interactive nodes with useful text may contribute
            to semantic fingerprints, even if they are not exported as
            InteractiveElements.
    """

    interactive_tags: List[str] = field(
        default_factory=lambda: [
            "a",
            "button",
            "input",
            "textarea",
            "select",
            "option",
            "label",
            "summary",
        ]
    )
    role_interactive_values: List[str] = field(
        default_factory=lambda: [
            "button",
            "link",
            "menuitem",
            "checkbox",
            "radio",
            "tab",
            "switch",
        ]
    )
    include_non_interactive_labels: bool = True


class DOMAdapter:
    """
    Adapter that converts a DOMSnapshotNode tree into a UIState.

    Typical usage by a web driver:

        snapshot_root = build_snapshot_from_dom(...)
        adapter = DOMAdapter(fingerprint_engine=my_fingerprint_engine)

        ui_state = adapter.build_ui_state(
            root=snapshot_root,
            app_id="my-web-app",
            url=current_url,
            screenshot_ref="screenshot_123.png",
            locale="en-US",
        )

    After this call:

        - ui_state.interactive_elements is populated.
        - ui_state.metadata contains URL and simple stats.
        - ui_state.fingerprints is populated if a FingerprintEngine
          was provided.
    """

    def __init__(
        self,
        *,
        fingerprint_engine: Optional[FingerprintEngine] = None,
        config: Optional[DOMAdapterConfig] = None,
    ) -> None:
        self._fingerprint_engine = fingerprint_engine
        self._config = config or DOMAdapterConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def build_ui_state(
        self,
        *,
        root: DOMSnapshotNode,
        app_id: str,
        url: Optional[str] = None,
        screenshot_ref: Optional[str] = None,
        locale: Optional[str] = None,
        version: Optional[str] = None,
    ) -> UIState:
        """
        Build a UIState from a DOMSnapshotNode tree.

        Args:
            root:
                Root DOMSnapshotNode (typically the <html> element).
            app_id:
                Logical application id (e.g. "my-product-app").
            url:
                Current page URL, stored in state metadata.
            screenshot_ref:
                Optional screenshot reference, stored in UIState.screenshot_ref.
            locale:
                Optional locale string (e.g. "en-US").
            version:
                Optional application version.

        Returns:
            UIState instance with interactive elements and fingerprints populated.
        """
        interactive_elements: List[InteractiveElement] = []
        ui_tree_dict = self._dom_to_tree_dict(root)
        text_content = self._collect_text(root)

        # Populate interactive elements
        self._collect_interactive_elements(
            node=root,
            elements=interactive_elements,
            path_prefix="/",
            index=0,
        )

        state = UIState(
            id="",  # will be filled/generated by StateTracker if needed
            app_id=app_id,
            version=version,
            platform=Platform.WEB,
            locale=locale,
            fingerprints={},
            screenshot_ref=screenshot_ref,
            interactive_elements=interactive_elements,
            metadata={
                "url": url,
                "node_count": self._count_nodes(root),
                "text_chars": len(text_content),
            },
        )

        # Attach fingerprints if engine is available
        if self._fingerprint_engine is not None:
            self._fingerprint_engine.fingerprint_state(
                ui_state=state,
                ui_tree=ui_tree_dict,
                screenshot_bytes=None,
                text_content=text_content or None,
            )

        return state

    # ------------------------------------------------------------------ #
    # Tree → dict conversion (for fingerprints)
    # ------------------------------------------------------------------ #

    def _dom_to_tree_dict(self, node: DOMSnapshotNode) -> Dict[str, Any]:
        """
        Convert DOMSnapshotNode to a JSON-serializable dict suitable
        for structural hashing.

        Only stable attributes are included. Volatile attributes such
        as dynamic IDs can be filtered by caller when building the
        DOMSnapshotNode.
        """
        attrs = dict(node.attributes or {})
        # Optionally drop obviously volatile attributes; keep this conservative
        for volatile in ("data-reactid", "data-vueid"):
            attrs.pop(volatile, None)

        return {
            "tag": node.tag.lower(),
            "attributes": attrs,
            "text": node.text.strip() if node.text else "",
            "children": [self._dom_to_tree_dict(c) for c in node.children],
        }

    # ------------------------------------------------------------------ #
    # Text collection (for semantic fingerprints)
    # ------------------------------------------------------------------ #

    def _collect_text(self, node: DOMSnapshotNode) -> str:
        """
        Collect all text content from the subtree, joined with spaces.

        Non-interactive nodes are included if `include_non_interactive_labels`
        is True. This is meant for a coarse semantic fingerprint, not for
        precise layout.
        """
        pieces: List[str] = []

        def visit(n: DOMSnapshotNode) -> None:
            if n.text:
                pieces.append(n.text.strip())
            for child in n.children:
                visit(child)

        visit(node)
        return " ".join(pieces).strip()

    # ------------------------------------------------------------------ #
    # Interactive element extraction
    # ------------------------------------------------------------------ #

    def _collect_interactive_elements(
        self,
        *,
        node: DOMSnapshotNode,
        elements: List[InteractiveElement],
        path_prefix: str,
        index: int,
    ) -> None:
        """
        Recursively traverse the DOM and collect interactive elements.

        `path_prefix` is a simple logical path (not XPath), purely for
        debugging and relative identification:
            /html/body/div[0]/button[2]
        """
        path_here = f"{path_prefix}{node.tag}[{index}]"

        if self._is_interactive(node):
            el_id = self._make_element_id(node, path_here)
            label = self._derive_label(node)
            role = self._derive_role(node)

            elements.append(
                InteractiveElement(
                    id=el_id,
                    role=role,
                    label=label,
                    bounding_box=None,  # can be filled by browser_session if available
                    path=path_here,
                    enabled=self._is_enabled(node),
                    visible=self._is_visible(node),
                    metadata={"tag": node.tag.lower(), "attributes": dict(node.attributes)},
                )
            )

        # Recurse into children
        for i, child in enumerate(node.children):
            self._collect_interactive_elements(
                node=child,
                elements=elements,
                path_prefix=path_here + "/",
                index=i,
            )

    def _is_interactive(self, node: DOMSnapshotNode) -> bool:
        """
        Heuristic to decide if a node is interactive.

        Rules:
            - Tag in interactive_tags → interactive.
            - role attribute in role_interactive_values → interactive.
            - input type=button/submit/reset → interactive.
        """
        tag = node.tag.lower()
        attrs = node.attributes or {}
        role = (attrs.get("role") or "").lower().strip()

        if tag in self._config.interactive_tags:
            return True

        if role and role in self._config.role_interactive_values:
            return True

        if tag == "input":
            input_type = (attrs.get("type") or "").lower().strip()
            if input_type in {"button", "submit", "reset", "checkbox", "radio"}:
                return True

        return False

    @staticmethod
    def _is_enabled(node: DOMSnapshotNode) -> bool:
        """
        Basic heuristic for enabled state.

        Disabled if:
            - 'disabled' attribute present (any value).
        """
        attrs = node.attributes or {}
        return "disabled" not in {k.lower() for k in attrs.keys()}

    @staticmethod
    def _is_visible(node: DOMSnapshotNode) -> bool:
        """
        Basic heuristic for visibility.

        This relies on attributes only; real visibility should be computed
        using layout/styles in a browser. Here we simply check:
            - style="display:none" or style="visibility:hidden" → not visible
        """
        style = (node.attributes.get("style") or "").lower()
        if "display:none" in style or "visibility:hidden" in style:
            return False
        return True

    @staticmethod
    def _derive_role(node: DOMSnapshotNode) -> str:
        """
        Derive a generic role for an element.

        Preference:
            - role attribute, if present.
            - tag name as fallback (e.g. "button", "a").
        """
        attrs = node.attributes or {}
        role_attr = attrs.get("role")
        if role_attr:
            return role_attr.strip().lower()
        return node.tag.lower()

    @staticmethod
    def _derive_label(node: DOMSnapshotNode) -> Optional[str]:
        """
        Derive a label for an interactive element.

        Preference:
            - 'aria-label' attribute.
            - 'title' attribute.
            - 'alt' attribute (for images).
            - node.text content.
        """
        attrs = node.attributes or {}
        for key in ("aria-label", "title", "alt"):
            val = attrs.get(key)
            if val and val.strip():
                return val.strip()
        if node.text and node.text.strip():
            return node.text.strip()
        return None

    @staticmethod
    def _make_element_id(node: DOMSnapshotNode, path: str) -> str:
        """
        Construct a stable-ish element id based on DOM attributes and path.

        Uses:
            - 'id' attribute if present.
            - otherwise, the logical path.
        """
        attrs = node.attributes or {}
        node_id = attrs.get("id")
        if node_id:
            return f"id:{node_id}"
        return f"path:{path}"

    def _count_nodes(self, root: DOMSnapshotNode) -> int:
        """Return total number of nodes in the snapshot tree."""
        count = 0

        def visit(n: DOMSnapshotNode) -> None:
            nonlocal count
            count += 1
            for c in n.children:
                visit(c)

        visit(root)
        return count
