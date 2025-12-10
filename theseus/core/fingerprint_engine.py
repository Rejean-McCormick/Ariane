"""
Fingerprint engine for Theseus.

This module bridges between raw driver outputs and the generic fingerprint
utilities in `common.models.fingerprints`.

Responsibilities:

- Take driver-level data (UI tree, screenshot bytes, text content).
- Compute structural / visual / semantic fingerprints where configured.
- Merge them with any existing fingerprints on the UIState.
- Write the resulting fingerprint map back to the UIState.

The underlying hash functions are defined in `common.models.fingerprints`,
so this engine stays as a thin coordination layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from common.models.fingerprints import (
    Fingerprints,
    compute_semantic_fingerprint,
    compute_structural_fingerprint,
    compute_visual_fingerprint,
    merge_fingerprints,
)
from common.models.ui_state import UIState


@dataclass
class FingerprintEngineConfig:
    """
    Configuration for the FingerprintEngine.

    Attributes:
        enable_structural:
            Whether to compute structural fingerprints from a UI tree.
        enable_visual:
            Whether to compute visual fingerprints from screenshot bytes.
        enable_semantic:
            Whether to compute semantic fingerprints from text content.
        structural_key:
            Key under which the structural fingerprint will be stored
            in UIState.fingerprints (default: "structural").
        visual_key:
            Key under which the visual fingerprint will be stored
            in UIState.fingerprints (default: "visual").
        semantic_key:
            Key under which the semantic fingerprint will be stored
            in UIState.fingerprints (default: "semantic").
    """

    enable_structural: bool = True
    enable_visual: bool = True
    enable_semantic: bool = True

    structural_key: str = "structural"
    visual_key: str = "visual"
    semantic_key: str = "semantic"


class FingerprintEngine:
    """
    Engine for computing and attaching fingerprints to UIState objects.

    Typical usage by a driver:

        engine = FingerprintEngine()

        ui_state = UIState(...)
        ui_tree = driver.build_ui_tree(...)
        screenshot_bytes = driver.capture_screenshot(...)
        text = driver.collect_text_content(...)

        fingerprints = engine.fingerprint_state(
            ui_state=ui_state,
            ui_tree=ui_tree,
            screenshot_bytes=screenshot_bytes,
            text_content=text,
        )

        # ui_state.fingerprints is now populated with hashes.

    All inputs are optional; only the configured and provided ones will be
    computed.
    """

    def __init__(self, config: Optional[FingerprintEngineConfig] = None) -> None:
        self._config = config or FingerprintEngineConfig()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def fingerprint_state(
        self,
        *,
        ui_state: UIState,
        ui_tree: Optional[Any] = None,
        screenshot_bytes: Optional[bytes] = None,
        text_content: Optional[str] = None,
    ) -> Fingerprints:
        """
        Compute fingerprints for a UIState and update its `fingerprints` map.

        Args:
            ui_state:
                UIState instance whose fingerprints will be updated.
            ui_tree:
                JSON-serializable representation of the UI tree / accessibility
                tree. Used for structural hashing when enabled.
            screenshot_bytes:
                Raw screenshot bytes. Used for visual hashing when enabled.
            text_content:
                Aggregated textual content (labels, headings, etc.). Used for
                semantic hashing when enabled.

        Returns:
            Fingerprints instance representing the merged fingerprints.
        """
        existing_fp = Fingerprints.from_dict(ui_state.fingerprints or {})

        structural_hash: Optional[str] = None
        visual_hash: Optional[str] = None
        semantic_hash: Optional[str] = None
        extra: Dict[str, str] = {}

        # Structural
        if self._config.enable_structural and ui_tree is not None:
            structural_hash = compute_structural_fingerprint(ui_tree)
            if self._config.structural_key != "structural":
                extra[self._config.structural_key] = structural_hash
                structural_hash = None  # store via extra, not standard field

        # Visual
        if self._config.enable_visual and screenshot_bytes is not None:
            visual_hash = compute_visual_fingerprint(screenshot_bytes)
            if self._config.visual_key != "visual":
                extra[self._config.visual_key] = visual_hash
                visual_hash = None

        # Semantic
        if self._config.enable_semantic and text_content is not None:
            semantic_hash = compute_semantic_fingerprint(text_content)
            if self._config.semantic_key != "semantic":
                extra[self._config.semantic_key] = semantic_hash
                semantic_hash = None

        merged = merge_fingerprints(
            structural_source=structural_hash,
            visual_source=visual_hash,
            semantic_source=semantic_hash,
            base=existing_fp,
            extra=extra,
        )

        ui_state.fingerprints = merged.to_dict()
        return merged

    def fingerprint_structural(
        self, ui_state: UIState, ui_tree: Any
    ) -> str:
        """
        Compute and store only the structural fingerprint for a state.

        Returns:
            The structural hash string (or the configured key's value).
        """
        structural_hash = compute_structural_fingerprint(ui_tree)
        key = self._config.structural_key or "structural"
        ui_state.fingerprints = dict(ui_state.fingerprints or {})
        ui_state.fingerprints[key] = structural_hash
        return structural_hash

    def fingerprint_visual(
        self, ui_state: UIState, screenshot_bytes: bytes
    ) -> str:
        """
        Compute and store only the visual fingerprint for a state.

        Returns:
            The visual hash string (or the configured key's value).
        """
        visual_hash = compute_visual_fingerprint(screenshot_bytes)
        key = self._config.visual_key or "visual"
        ui_state.fingerprints = dict(ui_state.fingerprints or {})
        ui_state.fingerprints[key] = visual_hash
        return visual_hash

    def fingerprint_semantic(
        self, ui_state: UIState, text_content: str
    ) -> str:
        """
        Compute and store only the semantic fingerprint for a state.

        Returns:
            The semantic hash string (or the configured key's value).
        """
        semantic_hash = compute_semantic_fingerprint(text_content)
        key = self._config.semantic_key or "semantic"
        ui_state.fingerprints = dict(ui_state.fingerprints or {})
        ui_state.fingerprints[key] = semantic_hash
        return semantic_hash
