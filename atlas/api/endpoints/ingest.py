"""
Ingest endpoint helpers for Ariane Atlas.

This module defines a small, framework-agnostic ingest layer that sits
on top of the GraphStore.

It does NOT implement HTTP handling directly. Instead, it provides
pure Python functions/classes that accept JSON-like payloads (dicts)
and return JSON-serializable dicts.

Typical usage from an HTTP server:

    handler = IngestHandler(store)

    def post_bundle(request_body: dict):
        try:
            result = handler.ingest_bundle(request_body)
            return 200, result
        except IngestError as e:
            return 400, {"error": str(e)}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from atlas.schema.context import Context
from atlas.schema.state_schema import StateRecord
from atlas.schema.transition_schema import TransitionRecord
from atlas.storage.graph_store import GraphStore


class IngestError(Exception):
    """
    Raised when ingest payloads are invalid or incomplete.

    HTTP servers should usually map this to a 4xx error (e.g. 400).
    """


@dataclass
class IngestHandler:
    """
    High-level ingest interface over a GraphStore.

    Methods accept JSON-like payloads (dicts/lists) and:

    - Validate required fields.
    - Convert to Context / StateRecord / TransitionRecord instances.
    - Store them in the GraphStore.
    - Return JSON-serializable summaries.

    All methods assume that payloads follow the same shapes produced by
    the corresponding `to_dict()` methods on schema classes.
    """

    store: GraphStore

    # ------------------------------------------------------------------ #
    # Context ingest
    # ------------------------------------------------------------------ #

    def ingest_context(self, payload: Dict[str, Any], overwrite: bool = True) -> Dict[str, Any]:
        """
        Ingest a single context.

        Payload format (as produced by Context.to_dict()):
            {
              "context_id": "...",
              "app_id": "...",
              "version": "...",
              "platform": "...",
              "locale": "...",
              "schema_version": "...",
              "created_at": "...",
              "environment": { ... },
              "metadata": { ... }
            }

        Args:
            payload: JSON-like dict.
            overwrite: If False and the context already exists, raise IngestError.

        Returns:
            {
              "status": "ok",
              "context_id": "..."
            }
        """
        if not isinstance(payload, dict):
            raise IngestError("Context payload must be an object")

        try:
            ctx = Context.from_dict(payload)
        except KeyError as exc:
            raise IngestError(f"Missing context field: {exc}") from exc
        except Exception as exc:  # broad but explicit
            raise IngestError(f"Invalid context payload: {exc}") from exc

        existing = self.store.get_context(ctx.context_id)
        if existing is not None and not overwrite:
            raise IngestError(f"Context '{ctx.context_id}' already exists")

        # Use the canonical upsert API on the store.
        self.store.upsert_context(ctx)

        return {"status": "ok", "context_id": ctx.context_id}

    # ------------------------------------------------------------------ #
    # State ingest
    # ------------------------------------------------------------------ #

    def ingest_state_record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ingest a single state record.

        Payload format (as produced by StateRecord.to_dict()):
            {
              "context_id": "...",
              "discovered_at": "...",
              "is_entry": true/false,
              "is_terminal": true/false,
              "tags": [...],
              "metadata": { ... },
              "state": {
                "id": "...",
                "app_id": "...",
                "version": "...",
                "platform": "...",
                "locale": "...",
                "fingerprints": { ... },
                "screenshot_ref": "...",
                "interactive_elements": [ ... ],
                "metadata": { ... }
              }
            }

        Returns:
            {
              "status": "ok",
              "context_id": "...",
              "state_id": "..."
            }
        """
        if not isinstance(payload, dict):
            raise IngestError("StateRecord payload must be an object")

        try:
            record = StateRecord.from_dict(payload)
        except KeyError as exc:
            raise IngestError(f"Missing state record field: {exc}") from exc
        except Exception as exc:
            raise IngestError(f"Invalid state record payload: {exc}") from exc

        if self.store.get_context(record.context_id) is None:
            raise IngestError(f"Context '{record.context_id}' does not exist")

        self.store.upsert_state(record)
        return {
            "status": "ok",
            "context_id": record.context_id,
            "state_id": record.id,
        }

    def ingest_state_records(self, payload: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Ingest multiple state records in a batch.

        Payload format:
            [
              { ...state record... },
              { ...state record... },
              ...
            ]

        Returns:
            {
              "status": "ok",
              "count": <number_of_states>,
              "state_ids": [ "state1", "state2", ... ],
              "context_ids": [ "ctx1", "ctx2", ... ]   # unique set
            }
        """
        if not isinstance(payload, list):
            raise IngestError("StateRecords payload must be a list")

        state_ids: List[str] = []
        ctx_ids_set = set()

        for item in payload:
            result = self.ingest_state_record(item)
            state_ids.append(result["state_id"])
            ctx_ids_set.add(result["context_id"])

        return {
            "status": "ok",
            "count": len(state_ids),
            "state_ids": state_ids,
            "context_ids": sorted(ctx_ids_set),
        }

    # ------------------------------------------------------------------ #
    # Transition ingest
    # ------------------------------------------------------------------ #

    def ingest_transition_record(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ingest a single transition record.

        Payload format (as produced by TransitionRecord.to_dict()):
            {
              "context_id": "...",
              "discovered_at": "...",
              "times_observed": 1,
              "metadata": { ... },
              "transition": {
                "id": "...",
                "source_state_id": "...",
                "target_state_id": "...",
                "action": { ... },
                "intent_id": "...",
                "confidence": 1.0,
                "metadata": { ... }
              }
            }

        Returns:
            {
              "status": "ok",
              "context_id": "...",
              "transition_id": "..."
            }
        """
        if not isinstance(payload, dict):
            raise IngestError("TransitionRecord payload must be an object")

        try:
            record = TransitionRecord.from_dict(payload)
        except KeyError as exc:
            raise IngestError(f"Missing transition record field: {exc}") from exc
        except Exception as exc:
            raise IngestError(f"Invalid transition record payload: {exc}") from exc

        if self.store.get_context(record.context_id) is None:
            raise IngestError(f"Context '{record.context_id}' does not exist")

        # Optionally, ensure states exist before inserting the transition
        if self.store.get_state(record.context_id, record.source_state_id) is None:
            raise IngestError(
                f"Source state '{record.source_state_id}' not found "
                f"in context '{record.context_id}'"
            )
        if self.store.get_state(record.context_id, record.target_state_id) is None:
            raise IngestError(
                f"Target state '{record.target_state_id}' not found "
                f"in context '{record.context_id}'"
            )

        self.store.upsert_transition(record, increment_observed=True)
        return {
            "status": "ok",
            "context_id": record.context_id,
            "transition_id": record.id,
        }

    def ingest_transition_records(self, payload: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Ingest multiple transition records in a batch.

        Payload format:
            [
              { ...transition record... },
              { ...transition record... },
              ...
            ]

        Returns:
            {
              "status": "ok",
              "count": <number_of_transitions>,
              "transition_ids": [ "tr1", "tr2", ... ],
              "context_ids": [ "ctx1", "ctx2", ... ]  # unique set
            }
        """
        if not isinstance(payload, list):
            raise IngestError("TransitionRecords payload must be a list")

        tr_ids: List[str] = []
        ctx_ids_set = set()

        for item in payload:
            result = self.ingest_transition_record(item)
            tr_ids.append(result["transition_id"])
            ctx_ids_set.add(result["context_id"])

        return {
            "status": "ok",
            "count": len(tr_ids),
            "transition_ids": tr_ids,
            "context_ids": sorted(ctx_ids_set),
        }

    # ------------------------------------------------------------------ #
    # Bundle ingest
    # ------------------------------------------------------------------ #

    def ingest_bundle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ingest a bundle containing an optional context, states, and transitions.

        Payload format:
            {
              "context": { ...context... },            # optional
              "states": [ { ...state record... } ],    # optional
              "transitions": [ { ...transition record... } ]  # optional
            }

        The order of operations is:

            1) If "context" is present, ingest the context.
            2) If "states" is present, ingest all states.
            3) If "transitions" is present, ingest all transitions.

        Returns:
            {
              "status": "ok",
              "context": { "ingested": true/false, "context_id": "..." or null },
              "states": { "count": N },
              "transitions": { "count": M }
            }
        """
        if not isinstance(payload, dict):
            raise IngestError("Bundle payload must be an object")

        context_info: Dict[str, Any] = {"ingested": False, "context_id": None}
        states_info: Dict[str, Any] = {"count": 0}
        transitions_info: Dict[str, Any] = {"count": 0}

        # 1) Context
        if "context" in payload and payload["context"] is not None:
            ctx_result = self.ingest_context(payload["context"], overwrite=True)
            context_info["ingested"] = True
            context_info["context_id"] = ctx_result["context_id"]

        # 2) States
        if "states" in payload and payload["states"] is not None:
            states_result = self.ingest_state_records(payload["states"])
            states_info["count"] = states_result["count"]

        # 3) Transitions
        if "transitions" in payload and payload["transitions"] is not None:
            tr_result = self.ingest_transition_records(payload["transitions"])
            transitions_info["count"] = tr_result["count"]

        return {
            "status": "ok",
            "context": context_info,
            "states": states_info,
            "transitions": transitions_info,
        }
