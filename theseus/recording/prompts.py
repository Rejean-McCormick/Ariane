"""
Helper utilities for annotating human-recorded steps with intents.

This module is intentionally **I/O-free**:

- It does NOT read from stdin or write to stdout.
- It only provides pure helper functions and lightweight data structures.

Intended usage:

- A CLI / UI layer asks the human:
    "What were you trying to do?"
- The free-text answer is passed to these helpers to:
    - Resolve a concrete intent (if possible), or
    - Suggest a small set of likely intents to choose from.

These helpers are built on top of the global intent registry defined in
`common.models.intents`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from common.models.intents import (
    Intent,
    all_intents,
    find_intent_for_phrase,
)


def _normalize(text: str) -> str:
    """
    Lightweight normalization used for similarity checks.

    This intentionally mirrors the normalization strategy in
    `common.models.intents` but is kept local to avoid depending on
    private helpers.
    """
    return " ".join(text.strip().lower().split())


@dataclass(frozen=True)
class IntentSuggestion:
    """
    A ranked suggestion for a semantic intent.

    Attributes:
        intent:      The matched Intent object.
        score:       Relative match score (higher is better). This is
                     a simple heuristic, not a probability.
        match_hint:  Short explanation of why this intent was suggested
                     (e.g. "exact label match", "synonym/substring match").
    """

    intent: Intent
    score: float
    match_hint: str

    def to_dict(self) -> Dict[str, Any]:
        """
        JSON-serializable representation, convenient for logging or
        passing into a UI layer.
        """
        return {
            "intent_id": self.intent.id,
            "label": self.intent.label,
            "description": self.intent.description,
            "category": self.intent.category.value,
            "score": float(self.score),
            "match_hint": self.match_hint,
            "synonyms": list(self.intent.synonyms),
            "external_refs": dict(self.intent.external_refs),
        }


def resolve_intent_from_phrase(phrase: str) -> Optional[Intent]:
    """
    Resolve a free-text phrase directly to an Intent, if possible.

    This is a thin wrapper over `find_intent_for_phrase` and is intended
    for "quick path" usage where the caller only cares about one best
    match (or None).

    Example:
        user: "I clicked Save As"
        -> resolve_intent_from_phrase("save as") -> Intent(id="save_as", ...)
    """
    if not phrase:
        return None
    return find_intent_for_phrase(phrase)


def suggest_intents_for_phrase(
    phrase: str,
    *,
    limit: int = 5,
    min_score: float = 0.1,
) -> List[IntentSuggestion]:
    """
    Suggest a small ranked list of intents for a human description.

    This function is designed for UI/CLI flows like:

        # 1) Try direct resolution
        intent = resolve_intent_from_phrase(text)
        if intent is None:
            # 2) Fall back to a suggestion list
            suggestions = suggest_intents_for_phrase(text)

    Scoring heuristics (simple, deterministic):

        - +3.0 if the phrase exactly equals the intent label (normalized).
        - +2.0 if the phrase exactly equals an id or synonym (normalized).
        - +1.0 if the phrase appears as a substring in label/synonyms.
        - +0.5 if the phrase appears as a substring in the description.

    Results with score < min_score are filtered out.
    """
    phrase_norm = _normalize(phrase)
    if not phrase_norm:
        return []

    suggestions: List[IntentSuggestion] = []

    for intent in all_intents():
        score = 0.0
        hint_parts: List[str] = []

        label_norm = _normalize(intent.label)
        id_norm = _normalize(intent.id)
        syn_norms = [_normalize(s) for s in intent.synonyms]

        # Exact matches
        if phrase_norm == label_norm:
            score += 3.0
            hint_parts.append("exact label match")
        if phrase_norm == id_norm:
            score += 2.0
            hint_parts.append("exact id match")
        if phrase_norm in syn_norms:
            score += 2.0
            hint_parts.append("exact synonym match")

        # Substring matches
        if phrase_norm in label_norm and phrase_norm != label_norm:
            score += 1.0
            hint_parts.append("label substring")
        if any(phrase_norm in s for s in syn_norms) and phrase_norm not in syn_norms:
            score += 1.0
            hint_parts.append("synonym substring")

        desc_norm = _normalize(intent.description)
        if phrase_norm and phrase_norm in desc_norm:
            score += 0.5
            hint_parts.append("description substring")

        if score >= min_score:
            hint = ", ".join(hint_parts) if hint_parts else "weak match"
            suggestions.append(
                IntentSuggestion(intent=intent, score=score, match_hint=hint)
            )

    # Sort by score (descending), then by label for stability
    suggestions.sort(key=lambda s: (-s.score, s.intent.label.lower()))
    if limit is not None and limit > 0:
        suggestions = suggestions[:limit]

    return suggestions


def build_intent_annotation(
    *,
    primary_phrase: Optional[str],
    chosen_intent: Optional[Intent],
    freeform_note: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a small, consistent annotation payload for a recorded step.

    This does not modify any Ariane core models; it is intended to be
    merged into `Transition.metadata` or `StateRecord.metadata` by the
    caller.

    Args:
        primary_phrase:
            The original human answer, e.g. "I wanted to export to PDF".
        chosen_intent:
            The Intent chosen for this step, or None if no mapping was
            possible or the user chose "other".
        freeform_note:
            Optional additional text note; can be used when the human
            wants to add nuance beyond the chosen intent.

    Returns:
        A JSON-serializable dict such as:

            {
              "intent_annotation": {
                "primary_phrase": "...",
                "intent_id": "export_pdf",
                "intent_label": "Export to PDF",
                "note": "Used File > Export > PDF",
              }
            }

        Callers typically merge this into metadata:

            md = transition.metadata.copy()
            md.update(build_intent_annotation(...))
            transition.metadata = md
    """
    annotation: Dict[str, Any] = {
        "intent_annotation": {
            "primary_phrase": primary_phrase,
            "note": freeform_note,
        }
    }

    if chosen_intent is not None:
        annotation["intent_annotation"].update(
            {
                "intent_id": chosen_intent.id,
                "intent_label": chosen_intent.label,
                "intent_category": chosen_intent.category.value,
            }
        )

    return annotation
