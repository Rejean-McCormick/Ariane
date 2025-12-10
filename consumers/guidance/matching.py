"""
State matching logic for the Guidance Client.

This module provides utilities to match a *local UI snapshot* captured
by a GuidanceProbe against a set of known StateView objects obtained
from Atlas via the SDK.

The goal is to answer: “Which known state does this snapshot most
likely correspond to?” and provide a normalized confidence score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from consumers.guidance.models import (
    StateMatchDetails,
    StateMatchResult,
)
from consumers.guidance.probe_interface import LocalUISnapshot
from consumers.sdk.types import StateView, UIElementHint


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


@dataclass
class MatchingConfig:
    """
    Configuration for state matching.

    All scores are combined into a single value in [0.0, 1.0] using
    a weighted average of the individual components.

    The default configuration is intentionally simple and conservative.
    """

    # Relative weight of each score component.
    structural_weight: float = 0.6
    semantic_weight: float = 0.3
    visual_weight: float = 0.1

    # Minimum combined score for a match to be considered usable.
    # Callers may choose to apply their own thresholds as well.
    min_score: float = 0.0

    # When True, require at least one overlapping fingerprint key
    # between snapshot and candidate state to consider it at all.
    require_fingerprint_overlap: bool = False


# --------------------------------------------------------------------------- #
# Fingerprint similarity
# --------------------------------------------------------------------------- #


def _fingerprint_similarity(
    snapshot_fps: Dict[str, str],
    state_fps: Dict[str, str],
) -> Tuple[float, Dict[str, float]]:
    """
    Compute a simple similarity score between two fingerprint dictionaries.

    For now, this is intentionally conservative:
    - For each key present in both dictionaries, score is 1.0 if values
      are exactly equal, 0.0 otherwise.
    - The final score is the mean over all overlapping keys.

    Returns:
        (score, per_key_scores)
    """
    overlapping_keys = set(snapshot_fps.keys()) & set(state_fps.keys())
    if not overlapping_keys:
        return 0.0, {}

    per_key_scores: Dict[str, float] = {}
    total = 0.0
    for key in overlapping_keys:
        s_val = snapshot_fps.get(key)
        t_val = state_fps.get(key)
        score = 1.0 if s_val == t_val else 0.0
        per_key_scores[key] = score
        total += score

    return total / float(len(overlapping_keys)), per_key_scores


# --------------------------------------------------------------------------- #
# Semantic / element similarity
# --------------------------------------------------------------------------- #


def _collect_labels_from_elements(elements: Iterable[UIElementHint]) -> List[str]:
    labels: List[str] = []
    for el in elements:
        label = getattr(el, "label", None)
        if label:
            labels.append(label)
    return labels


def _collect_labels_from_snapshot(snapshot: LocalUISnapshot) -> List[str]:
    labels: List[str] = []
    for el in snapshot.elements:
        if el.label:
            labels.append(el.label)
    return labels


def _tokenize_labels(labels: Iterable[str]) -> List[str]:
    tokens: List[str] = []
    for label in labels:
        for part in label.lower().split():
            part = part.strip()
            if part:
                tokens.append(part)
    return tokens


def _jaccard_similarity(a: List[str], b: List[str]) -> float:
    """
    Basic Jaccard similarity on sets of tokens.

    Returns:
        A float in [0.0, 1.0].
    """
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / float(len(union))


def _semantic_similarity(snapshot: LocalUISnapshot, state: StateView) -> float:
    """
    Compute a crude semantic similarity based on element labels.

    This is a simple heuristic:
    - Collect labels from snapshot elements and state.interactive_elements.
    - Tokenize by whitespace.
    - Compute Jaccard similarity over token sets.
    """
    snapshot_labels = _collect_labels_from_snapshot(snapshot)
    state_labels = _collect_labels_from_elements(state.interactive_elements)

    tokens_snapshot = _tokenize_labels(snapshot_labels)
    tokens_state = _tokenize_labels(state_labels)

    return _jaccard_similarity(tokens_snapshot, tokens_state)


# --------------------------------------------------------------------------- #
# Visual similarity (placeholder)
# --------------------------------------------------------------------------- #


def _visual_similarity(snapshot_fps: Dict[str, str], state_fps: Dict[str, str]) -> float:
    """
    Placeholder visual similarity.

    If both snapshot and state expose a "visual" fingerprint and the
    values are exactly equal, returns 1.0; otherwise 0.0.

    A more sophisticated implementation could compute distance between
    perceptual hashes rather than direct equality.
    """
    snap_val = snapshot_fps.get("visual")
    state_val = state_fps.get("visual")
    if not snap_val or not state_val:
        return 0.0
    return 1.0 if snap_val == state_val else 0.0


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def score_state_match(
    snapshot: LocalUISnapshot,
    state: StateView,
    config: Optional[MatchingConfig] = None,
) -> Optional[StateMatchResult]:
    """
    Compute a StateMatchResult for a single candidate state.

    Returns:
        StateMatchResult if a score could be computed, or None if
        the candidate should be disregarded (e.g. no overlapping
        fingerprints and require_fingerprint_overlap is True).
    """
    if config is None:
        config = MatchingConfig()

    snap_fps = snapshot.fingerprints or {}
    state_fps = state.fingerprints or {}

    # Structural similarity (based on overlapping fingerprints).
    structural_score, per_key_scores = _fingerprint_similarity(snap_fps, state_fps)

    # Optionally discard candidate if there is no overlap at all.
    if config.require_fingerprint_overlap and not per_key_scores:
        return None

    # Semantic similarity based on element labels.
    semantic_score = _semantic_similarity(snapshot, state)

    # Visual similarity from "visual" fingerprint.
    visual_score = _visual_similarity(snap_fps, state_fps)

    # Weighted combination.
    total_weight = (
        config.structural_weight + config.semantic_weight + config.visual_weight
    )
    if total_weight <= 0.0:
        # Degenerate configuration; treat as no match.
        return None

    combined_score = (
        structural_score * config.structural_weight
        + semantic_score * config.semantic_weight
        + visual_score * config.visual_weight
    ) / total_weight

    if combined_score < config.min_score:
        return None

    details = StateMatchDetails(
        structural_score=structural_score,
        semantic_score=semantic_score,
        visual_score=visual_score,
        combined_score=combined_score,
        metadata={"per_fingerprint_scores": per_key_scores},
    )

    return StateMatchResult(state=state, score=combined_score, details=details)


def match_states(
    snapshot: LocalUISnapshot,
    candidates: Iterable[StateView],
    config: Optional[MatchingConfig] = None,
) -> List[StateMatchResult]:
    """
    Match a snapshot against multiple candidate states.

    Returns:
        A list of StateMatchResult objects sorted by descending score.
        Candidates that do not meet `config.min_score` or are filtered
        out by `require_fingerprint_overlap` are omitted.
    """
    if config is None:
        config = MatchingConfig()

    results: List[StateMatchResult] = []
    for state in candidates:
        match = score_state_match(snapshot, state, config=config)
        if match is not None:
            results.append(match)

    # Sort by score descending.
    results.sort(key=lambda r: r.score, reverse=True)
    return results


def best_match(
    snapshot: LocalUISnapshot,
    candidates: Iterable[StateView],
    config: Optional[MatchingConfig] = None,
    min_score: Optional[float] = None,
) -> Optional[StateMatchResult]:
    """
    Convenience helper to get the best match (highest score) for a snapshot.

    Args:
        snapshot: LocalUISnapshot from a GuidanceProbe.
        candidates: Iterable of StateView candidates.
        config: MatchingConfig (optional).
        min_score: Optional override for the minimum accepted score.
                   If provided, it supersedes config.min_score for this call.

    Returns:
        The best StateMatchResult, or None if no suitable match exists.
    """
    if config is None:
        config = MatchingConfig()

    effective_min = config.min_score if min_score is None else float(min_score)
    local_config = MatchingConfig(
        structural_weight=config.structural_weight,
        semantic_weight=config.semantic_weight,
        visual_weight=config.visual_weight,
        min_score=effective_min,
        require_fingerprint_overlap=config.require_fingerprint_overlap,
    )

    matches = match_states(snapshot, candidates, config=local_config)
    return matches[0] if matches else None


__all__ = [
    "MatchingConfig",
    "score_state_match",
    "match_states",
    "best_match",
]
