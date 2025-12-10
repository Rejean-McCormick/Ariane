"""
Context schema for Ariane Atlas.

This module defines the Context object: the metadata that anchors a UI
graph (states + transitions) to a specific piece of software and runtime
environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

from common.models.ui_state import Platform


SCHEMA_VERSION = "1.0.0"


@dataclass
class Context:
    """
    Context metadata for a group of UI states / transitions.

    A Context describes *which* application and environment a given
    UI graph applies to.

    Attributes:
        context_id:
            Identifier for this context instance. This can be used as a
            logical "graph id" if you want to group states and transitions.
        app_id:
            Logical identifier of the application, e.g. "photoshop",
            "libreoffice_writer", "custom_internal_tool".
        version:
            Application version string, e.g. "25.1.0". Optional but strongly
            recommended when available.
        platform:
            Logical platform (web, windows, linux, android, etc.).
        locale:
            Locale tag (e.g. "en-US") in which this mapping was generated.
        schema_version:
            Version of the Atlas schema used to encode this context and its
            associated states/transitions.
        created_at:
            ISO 8601 timestamp (UTC) when this context was created.
        environment:
            Free-form description of the environment in which the mapping
            was produced: OS version, device type, etc.
            Example: {"os_version": "...", "device": "..."}.
        metadata:
            Arbitrary extra metadata; can include tags, notes, or
            pipeline-specific fields.
    """

    context_id: str
    app_id: str
    version: Optional[str] = None
    platform: Platform = Platform.OTHER
    locale: Optional[str] = None

    schema_version: str = SCHEMA_VERSION
    created_at: str = field(
        default_factory=lambda: datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    )

    environment: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --------------------------------------------------------------------- #
    # Serialization helpers
    # --------------------------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize this Context to a JSON-friendly dictionary.

        This is intended to be stored alongside states/transitions in Atlas.
        """
        return {
            "context_id": self.context_id,
            "app_id": self.app_id,
            "version": self.version,
            "platform": self.platform.value,
            "locale": self.locale,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "environment": dict(self.environment),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Context":
        """
        Reconstruct a Context from a dictionary produced by to_dict().
        """
        return cls(
            context_id=data["context_id"],
            app_id=data["app_id"],
            version=data.get("version"),
            platform=Platform(data.get("platform", Platform.OTHER.value)),
            locale=data.get("locale"),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            created_at=data.get("created_at")
            or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            environment=dict(data.get("environment") or {}),
            metadata=dict(data.get("metadata") or {}),
        )
