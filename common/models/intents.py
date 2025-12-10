"""
Common intent model for Ariane.

This module defines the semantic "intents" that transitions/actions
in the UI graph can be associated with. An intent is an abstract action
(e.g. "save", "export", "create new") that can be mapped to many
concrete UI interactions across different applications and platforms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional


class IntentCategory(str, Enum):
    """High-level buckets for intents, useful for grouping and analytics."""

    FILE = "file"
    EDIT = "edit"
    VIEW = "view"
    NAVIGATION = "navigation"
    EXPORT = "export"
    IMPORT = "import"
    FORMAT = "format"
    INSERT = "insert"
    HELP = "help"
    SETTINGS = "settings"
    ACCOUNT = "account"
    DATA = "data"
    OTHER = "other"


@dataclass(frozen=True)
class Intent:
    """
    A semantic intent that can be attached to transitions.

    Attributes:
        id: Stable, lowercase identifier (e.g. "save", "export_pdf").
        category: Broad category for the intent.
        label: Human-readable label.
        description: Short explanation of what the intent means.
        synonyms: Alternative phrases often used in UIs for this intent.
        external_refs:
            Optional mapping to external vocabularies / knowledge bases
            (e.g. {"wd": "Q22676"} for a knowledge graph ID).
    """

    id: str
    category: IntentCategory
    label: str
    description: str
    synonyms: List[str] = field(default_factory=list)
    external_refs: Dict[str, str] = field(default_factory=dict)

    def matches_phrase(self, phrase: str) -> bool:
        """Return True if the phrase looks like this intent or one of its synonyms."""
        key = _normalize(phrase)
        if key == _normalize(self.label):
            return True
        if key == _normalize(self.id):
            return True
        return key in (_normalize(s) for s in self.synonyms)


# --- Internal registry --------------------------------------------------------

_INTENTS_BY_ID: Dict[str, Intent] = {}
_INTENTS_BY_SYNONYM: Dict[str, Intent] = {}
_INTENTS_BY_EXTERNAL: Dict[str, Intent] = {}


def _normalize(s: str) -> str:
    return " ".join(s.strip().lower().split())


def register_intent(intent: Intent) -> None:
    """
    Register an intent in the global registry.

    Intended to be called during module import for built-in intents.
    You can also call it at runtime to add custom intents.
    """
    key = _normalize(intent.id)
    if key in _INTENTS_BY_ID and _INTENTS_BY_ID[key] is not intent:
        raise ValueError(f"Intent with id '{intent.id}' is already registered")

    _INTENTS_BY_ID[key] = intent

    for syn in _iter_all_names(intent):
        syn_key = _normalize(syn)
        # Do not overwrite existing synonym mappings silently
        if syn_key not in _INTENTS_BY_SYNONYM:
            _INTENTS_BY_SYNONYM[syn_key] = intent

    for namespace, ref_id in intent.external_refs.items():
        ext_key = f"{namespace}:{ref_id}"
        if ext_key not in _INTENTS_BY_EXTERNAL:
            _INTENTS_BY_EXTERNAL[ext_key] = intent


def _iter_all_names(intent: Intent) -> Iterable[str]:
    yield intent.id
    yield intent.label
    for s in intent.synonyms:
        yield s


# --- Lookup helpers -----------------------------------------------------------


def get_intent(intent_id: str) -> Optional[Intent]:
    """
    Find an intent by its stable id.

    Returns:
        The Intent instance, or None if not registered.
    """
    return _INTENTS_BY_ID.get(_normalize(intent_id))


def find_intent_for_phrase(phrase: str) -> Optional[Intent]:
    """
    Resolve a natural language phrase (e.g. a button label) to an intent.

    This uses a simple synonym lookup; more advanced matching can be built
    on top by callers if needed.
    """
    key = _normalize(phrase)
    return _INTENTS_BY_SYNONYM.get(key)


def find_intent_by_external_ref(namespace: str, ref_id: str) -> Optional[Intent]:
    """
    Find an intent by an external reference.

    Example:
        find_intent_by_external_ref("wd", "Q22676")
    """
    return _INTENTS_BY_EXTERNAL.get(f"{namespace}:{ref_id}")


def all_intents() -> List[Intent]:
    """
    Return all registered intents.

    The order is not guaranteed; callers should sort if they need stability.
    """
    return list(_INTENTS_BY_ID.values())


# --- Built-in intents ---------------------------------------------------------

# These built-ins are intentionally minimal. You can extend or override them
# in project-specific code as needed.

def _register_builtin_intents() -> None:
    builtin = [
        Intent(
            id="create_new",
            category=IntentCategory.FILE,
            label="Create New",
            description="Create a new document, file, project, or equivalent entity.",
            synonyms=["new", "new file", "new document", "create", "add new"],
        ),
        Intent(
            id="open",
            category=IntentCategory.FILE,
            label="Open",
            description="Open an existing document, file, project, or resource.",
            synonyms=["open file", "open project", "load", "browse..."],
        ),
        Intent(
            id="save",
            category=IntentCategory.FILE,
            label="Save",
            description="Save the current state of the document or project.",
            synonyms=["save file", "save changes"],
        ),
        Intent(
            id="save_as",
            category=IntentCategory.FILE,
            label="Save As",
            description="Save the current document or project under a new name or location.",
            synonyms=["save copy", "duplicate", "export copy"],
        ),
        Intent(
            id="export",
            category=IntentCategory.EXPORT,
            label="Export",
            description="Export the current content to another format or target.",
            synonyms=["export as", "export file", "render", "publish"],
        ),
        Intent(
            id="import",
            category=IntentCategory.IMPORT,
            label="Import",
            description="Import external data or files into the current project.",
            synonyms=["load data", "add from file", "bring in"],
        ),
        Intent(
            id="undo",
            category=IntentCategory.EDIT,
            label="Undo",
            description="Revert the last action.",
            synonyms=["undo last action"],
        ),
        Intent(
            id="redo",
            category=IntentCategory.EDIT,
            label="Redo",
            description="Re-apply the last undone action.",
            synonyms=["redo last action"],
        ),
        Intent(
            id="delete",
            category=IntentCategory.EDIT,
            label="Delete",
            description="Remove the selected item or content.",
            synonyms=["remove", "erase", "trash"],
        ),
        Intent(
            id="search",
            category=IntentCategory.NAVIGATION,
            label="Search",
            description="Search within the current context or data set.",
            synonyms=["find", "find and replace", "lookup"],
        ),
        Intent(
            id="print",
            category=IntentCategory.FILE,
            label="Print",
            description="Print or generate a print-ready representation.",
            synonyms=["print document", "print file"],
        ),
        Intent(
            id="settings",
            category=IntentCategory.SETTINGS,
            label="Settings",
            description="Open settings, preferences, or configuration.",
            synonyms=["preferences", "options", "configuration"],
        ),
        Intent(
            id="help",
            category=IntentCategory.HELP,
            label="Help",
            description="Open help, documentation, or support resources.",
            synonyms=["documentation", "support", "help center"],
        ),
    ]

    for intent in builtin:
        register_intent(intent)


# Initialize registry with built-ins on import
_register_builtin_intents()
