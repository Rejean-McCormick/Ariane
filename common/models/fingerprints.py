"""
Fingerprint utilities for Ariane.

Fingerprints are stable identifiers that help recognize whether two UI
states are effectively the same, even if they come from different runs
or slightly different environments.

This module provides:

- A Fingerprints dataclass for bundling multiple hashes.
- Helpers to compute simple structural / visual / semantic hashes
  using only the standard library.

These are intentionally conservative, dependency-free implementations.
Callers can replace or extend them with more advanced hashing if needed
(e.g. perceptual image hashing, DOM-aware hashing).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def _sha256_hex(data: bytes) -> str:
    """Return SHA-256 hex digest for the given bytes."""
    return hashlib.sha256(data).hexdigest()


def _normalized_json_bytes(obj: Any) -> bytes:
    """
    Serialize an object to JSON with normalized formatting and key order.

    This helps ensure that structurally equivalent objects produce the
    same bytes and therefore the same hash.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@dataclass
class Fingerprints:
    """
    Collection of hashes for a UI state.

    Attributes:
        structural:
            Hash of the underlying UI tree / structure. Intended to be stable
            when purely visual details change (colors, fonts), but structural
            layout stays the same.
        visual:
            Hash of the rendered appearance (e.g., screenshot bytes).
            Intended to detect visual changes that a structural hash might miss.
        semantic:
            Hash of text content / semantics (labels, headings, etc.).
        extra:
            Additional named hashes or identifiers; callers may store
            driver-specific or experimental fingerprints here.
    """

    structural: Optional[str] = None
    visual: Optional[str] = None
    semantic: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, str]:
        """
        Serialize to a flat dictionary suitable for storage in UIState.fingerprints.

        Keys used:
            "structural", "visual", "semantic", plus everything in `extra`.
        """
        data: Dict[str, str] = {}
        if self.structural is not None:
            data["structural"] = self.structural
        if self.visual is not None:
            data["visual"] = self.visual
        if self.semantic is not None:
            data["semantic"] = self.semantic
        data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "Fingerprints":
        """
        Reconstruct a Fingerprints instance from a flat dictionary.

        Inverse of to_dict().
        """
        data = dict(data)  # shallow copy
        structural = data.pop("structural", None)
        visual = data.pop("visual", None)
        semantic = data.pop("semantic", None)
        return cls(structural=structural, visual=visual, semantic=semantic, extra=data)


# --- computation helpers ------------------------------------------------------


def compute_structural_fingerprint(ui_tree: Any) -> str:
    """
    Compute a structural hash for a UI tree-like object.

    `ui_tree` should be a JSON-serializable representation of the
    accessibility / DOM tree or an abstracted UI tree produced by a driver.

    This implementation:
        - Normalizes to JSON with sorted keys.
        - Computes SHA-256 over the resulting bytes.

    More advanced versions could:
        - Strip volatile attributes (timestamps, runtime IDs).
        - Normalize ordering of siblings where it doesn't matter.
    """
    return _sha256_hex(_normalized_json_bytes(ui_tree))


def compute_visual_fingerprint(image_bytes: bytes) -> str:
    """
    Compute a visual hash for screenshot bytes.

    This implementation uses a simple SHA-256 over the raw bytes as a
    stand-in for a perceptual hash. It is sensitive to minor pixel-level
    differences, but has no external dependencies.

    Callers may replace this with a real perceptual hashing implementation
    if they need robustness across minor rendering differences.
    """
    return _sha256_hex(image_bytes)


def compute_semantic_fingerprint(text: str) -> str:
    """
    Compute a semantic hash for textual content.

    This is intended for concatenated labels, headings, and other UI text.
    It normalizes whitespace and case before hashing.

    Example usage:
        text = " ".join(all_labels_in_tree)
        semantic_hash = compute_semantic_fingerprint(text)
    """
    normalized = " ".join(text.strip().lower().split())
    return _sha256_hex(normalized.encode("utf-8"))


def merge_fingerprints(
    *,
    structural_source: Optional[str] = None,
    visual_source: Optional[str] = None,
    semantic_source: Optional[str] = None,
    base: Optional[Fingerprints] = None,
    extra: Optional[Dict[str, str]] = None,
) -> Fingerprints:
    """
    Combine existing fingerprints with newly computed ones.

    Args:
        structural_source:
            New structural hash to set (if provided).
        visual_source:
            New visual hash to set (if provided).
        semantic_source:
            New semantic hash to set (if provided).
        base:
            Existing Fingerprints instance to start from. If None, a new
            one is created.
        extra:
            Additional extra hashes to merge into `extra`.

    Returns:
        A new Fingerprints instance with merged values.
    """
    fp = Fingerprints(
        structural=base.structural if base else None,
        visual=base.visual if base else None,
        semantic=base.semantic if base else None,
        extra=dict(base.extra) if base else {},
    )

    if structural_source is not None:
        fp.structural = structural_source
    if visual_source is not None:
        fp.visual = visual_source
    if semantic_source is not None:
        fp.semantic = semantic_source
    if extra:
        fp.extra.update(extra)

    return fp
