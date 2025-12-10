"""
Ontology schema for Ariane Atlas.

This module defines a minimal ontology vocabulary for UI concepts used
across Ariane:

- UI roles (e.g. button, menuitem, dialog)
- UI patterns (e.g. modal dialog, toast notification, hamburger menu)

It provides:

- Dataclasses for ontology terms.
- Simple in-memory registries.
- A small set of built-in terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional


# --------------------------------------------------------------------------- #
# Base ontology term
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class OntologyTerm:
    """
    Base type for ontology terms.

    Attributes:
        id:
            Stable identifier (e.g. "button", "toast_notification").
        label:
            Human-readable label.
        description:
            Short description of what the term represents.
        aliases:
            Alternative names or labels for the same concept.
        external_refs:
            Optional mapping to external vocabularies / IDs,
            e.g. {"aria-role": "button"} or {"uidl": "Button"}.
    """

    id: str
    label: str
    description: str
    aliases: List[str] = field(default_factory=list)
    external_refs: Dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Role and pattern-specific types
# --------------------------------------------------------------------------- #


class RoleCategory(str, Enum):
    """High-level categories for UI roles."""

    INTERACTIVE = "interactive"
    CONTAINER = "container"
    STRUCTURAL = "structural"
    FEEDBACK = "feedback"
    INPUT = "input"
    NAVIGATION = "navigation"
    OTHER = "other"


@dataclass(frozen=True)
class UIRole(OntologyTerm):
    """
    Role that can be assigned to an interactive element.

    Example: button, link, menuitem, textbox, dialog.
    """

    category: RoleCategory = RoleCategory.OTHER


@dataclass(frozen=True)
class UIPattern(OntologyTerm):
    """
    Higher-level UI pattern composed of roles and layout conventions.

    Example: modal dialog, toast notification, hamburger menu.
    """

    # Optionally list typical roles that participate in the pattern.
    typical_roles: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Registries
# --------------------------------------------------------------------------- #


_UI_ROLES: Dict[str, UIRole] = {}
_UI_PATTERNS: Dict[str, UIPattern] = {}


def _normalize_id(identifier: str) -> str:
    return identifier.strip().lower()


def register_role(role: UIRole) -> None:
    """
    Register a UI role in the global registry.

    Raises:
        ValueError if a different role with the same id already exists.
    """
    key = _normalize_id(role.id)
    existing = _UI_ROLES.get(key)
    if existing is not None and existing is not role:
        raise ValueError(f"Role with id '{role.id}' is already registered")
    _UI_ROLES[key] = role


def register_pattern(pattern: UIPattern) -> None:
    """
    Register a UI pattern in the global registry.

    Raises:
        ValueError if a different pattern with the same id already exists.
    """
    key = _normalize_id(pattern.id)
    existing = _UI_PATTERNS.get(key)
    if existing is not None and existing is not pattern:
        raise ValueError(f"Pattern with id '{pattern.id}' is already registered")
    _UI_PATTERNS[key] = pattern


def get_role(role_id: str) -> Optional[UIRole]:
    """Return a role by id, or None if not found."""
    return _UI_ROLES.get(_normalize_id(role_id))


def get_pattern(pattern_id: str) -> Optional[UIPattern]:
    """Return a pattern by id, or None if not found."""
    return _UI_PATTERNS.get(_normalize_id(pattern_id))


def all_roles() -> Iterable[UIRole]:
    """Iterate over all registered roles."""
    return _UI_ROLES.values()


def all_patterns() -> Iterable[UIPattern]:
    """Iterate over all registered patterns."""
    return _UI_PATTERNS.values()


# --------------------------------------------------------------------------- #
# Built-in vocabulary
# --------------------------------------------------------------------------- #


def _register_builtin_roles() -> None:
    roles = [
        UIRole(
            id="button",
            label="Button",
            description="Clickable control that triggers an action.",
            aliases=["push button", "btn"],
            external_refs={"aria-role": "button"},
            category=RoleCategory.INTERACTIVE,
        ),
        UIRole(
            id="link",
            label="Link",
            description="Navigational element that moves focus to another resource or view.",
            aliases=["hyperlink"],
            external_refs={"aria-role": "link"},
            category=RoleCategory.NAVIGATION,
        ),
        UIRole(
            id="menu",
            label="Menu",
            description="Container for a list of choices or commands.",
            aliases=["menu bar", "context menu"],
            external_refs={"aria-role": "menu"},
            category=RoleCategory.CONTAINER,
        ),
        UIRole(
            id="menuitem",
            label="Menu Item",
            description="Choice within a menu that can be activated.",
            aliases=["menu item"],
            external_refs={"aria-role": "menuitem"},
            category=RoleCategory.INTERACTIVE,
        ),
        UIRole(
            id="textbox",
            label="Text Box",
            description="Editable text input field.",
            aliases=["text field", "input"],
            external_refs={"aria-role": "textbox"},
            category=RoleCategory.INPUT,
        ),
        UIRole(
            id="checkbox",
            label="Checkbox",
            description="Binary on/off option, typically square with a check mark.",
            aliases=["check box"],
            external_refs={"aria-role": "checkbox"},
            category=RoleCategory.INPUT,
        ),
        UIRole(
            id="radiobutton",
            label="Radio Button",
            description="Single-choice option among a group of mutually exclusive options.",
            aliases=["radio button", "radio"],
            external_refs={"aria-role": "radio"},
            category=RoleCategory.INPUT,
        ),
        UIRole(
            id="dialog",
            label="Dialog",
            description="Top-level window used to prompt the user for interaction.",
            aliases=["dialog box"],
            external_refs={"aria-role": "dialog"},
            category=RoleCategory.CONTAINER,
        ),
        UIRole(
            id="alert",
            label="Alert",
            description="High-priority message that interrupts the user's workflow.",
            aliases=["alert dialog"],
            external_refs={"aria-role": "alert"},
            category=RoleCategory.FEEDBACK,
        ),
        UIRole(
            id="status",
            label="Status",
            description="Non-interruptive status or progress information.",
            aliases=["status bar"],
            external_refs={"aria-role": "status"},
            category=RoleCategory.FEEDBACK,
        ),
        UIRole(
            id="toolbar",
            label="Toolbar",
            description="Collection of commonly used controls grouped together.",
            aliases=["tool bar"],
            external_refs={"aria-role": "toolbar"},
            category=RoleCategory.CONTAINER,
        ),
        UIRole(
            id="tab",
            label="Tab",
            description="Control used to switch between views in a tabbed interface.",
            aliases=["tab header"],
            external_refs={"aria-role": "tab"},
            category=RoleCategory.NAVIGATION,
        ),
        UIRole(
            id="tabpanel",
            label="Tab Panel",
            description="Container for the content associated with a tab.",
            aliases=["tab panel"],
            external_refs={"aria-role": "tabpanel"},
            category=RoleCategory.CONTAINER,
        ),
        UIRole(
            id="list",
            label="List",
            description="Container for a linear list of items.",
            aliases=["listbox"],
            external_refs={"aria-role": "list"},
            category=RoleCategory.CONTAINER,
        ),
        UIRole(
            id="listitem",
            label="List Item",
            description="Item within a list.",
            aliases=["list item"],
            external_refs={"aria-role": "listitem"},
            category=RoleCategory.STRUCTURAL,
        ),
        UIRole(
            id="table",
            label="Table",
            description="Grid of rows and columns for displaying data.",
            aliases=["grid"],
            external_refs={"aria-role": "table"},
            category=RoleCategory.CONTAINER,
        ),
        UIRole(
            id="row",
            label="Row",
            description="Horizontal grouping of cells in a table.",
            aliases=["table row"],
            external_refs={"aria-role": "row"},
            category=RoleCategory.STRUCTURAL,
        ),
        UIRole(
            id="cell",
            label="Cell",
            description="Intersection of a row and column in a table.",
            aliases=["table cell"],
            external_refs={"aria-role": "cell"},
            category=RoleCategory.STRUCTURAL,
        ),
        UIRole(
            id="image",
            label="Image",
            description="Static image or icon.",
            aliases=["img", "icon"],
            external_refs={"aria-role": "img"},
            category=RoleCategory.OTHER,
        ),
        UIRole(
            id="slider",
            label="Slider",
            description="Input control for choosing a value from a continuous or discrete range.",
            aliases=["range slider"],
            external_refs={"aria-role": "slider"},
            category=RoleCategory.INPUT,
        ),
        UIRole(
            id="progressbar",
            label="Progress Bar",
            description="Visual indicator of task progress.",
            aliases=["progress"],
            external_refs={"aria-role": "progressbar"},
            category=RoleCategory.FEEDBACK,
        ),
    ]

    for role in roles:
        register_role(role)


def _register_builtin_patterns() -> None:
    patterns = [
        UIPattern(
            id="modal_dialog",
            label="Modal Dialog",
            description="Dialog that blocks interaction with the rest of the interface until dismissed.",
            aliases=["modal", "popup dialog"],
            typical_roles=["dialog", "button"],
        ),
        UIPattern(
            id="toast_notification",
            label="Toast Notification",
            description="Transient message overlay that appears and disappears automatically.",
            aliases=["toast", "snackbar"],
            typical_roles=["status"],
        ),
        UIPattern(
            id="hamburger_menu",
            label="Hamburger Menu",
            description="Collapsible navigation menu typically opened from an icon with three horizontal lines.",
            aliases=["nav drawer", "navigation drawer"],
            typical_roles=["menu", "button"],
        ),
        UIPattern(
            id="wizard_step",
            label="Wizard Step",
            description="Step in a multi-step guided workflow (wizard).",
            aliases=["step wizard", "setup wizard step"],
            typical_roles=["button", "progressbar"],
        ),
        UIPattern(
            id="toolbar_group",
            label="Toolbar Group",
            description="Cluster of related controls inside a toolbar.",
            aliases=["tool group"],
            typical_roles=["toolbar", "button"],
        ),
        UIPattern(
            id="navigation_bar",
            label="Navigation Bar",
            description="Primary navigation area, often at the top or side of an application.",
            aliases=["navbar", "app bar"],
            typical_roles=["link", "button"],
        ),
        UIPattern(
            id="sidebar",
            label="Sidebar",
            description="Secondary panel anchored to the left or right side of the main content.",
            aliases=["side panel", "drawer"],
            typical_roles=["list", "button"],
        ),
    ]

    for pattern in patterns:
        register_pattern(pattern)


# Initialize registry with built-in vocabulary on import
_register_builtin_roles()
_register_builtin_patterns()
