"""
Query endpoint helpers for Ariane Atlas.

This module defines a small, framework-agnostic query layer that sits
on top of the GraphStore.

It does NOT implement HTTP handling directly. Instead, it provides
pure Python functions/classes that return JSON-serializable dicts.

The HTTP server (see http_server.py) is expected to:

    - Parse HTTP requests.
    - Call these helpers with validated parameters.
    - Serialize the returned dicts as JSON.
    - Map QueryError to appropriate HTTP status codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from atlas.schema.context import Context
from atlas.schema.state_schema import StateRecord
from atlas.schema.transition_schema import TransitionRecord
from atlas.storage.graph_store import GraphStore


class QueryError(Exception):
    """
    Raised when a query cannot be satisfied due to invalid parameters
    or missing data.

    HTTP servers should map this to a 4xx error, typically 400 or 404,
    depending on the cause.
    """


@dataclass
class QueryHandler:
    """
    High-level query interface over a GraphStore.

    Methods return JSON-serializable dictionaries that can be used as
    HTTP responses.
    """

    store: GraphStore

    # ------------------------------------------------------------------ #
    # Context queries
    # ------------------------------------------------------------------ #

    def list_contexts(self) -> Dict[str, Any]:
        """
        Return all known contexts.

        Response format:
            {
              "contexts": [
                { ...context fields... },
                ...
              ]
            }
        """
        contexts: List[Context] = self.store.list_contexts()
        return {
            "contexts": [ctx.to_dict() for ctx in contexts],
        }

    def get_context(self, context_id: str) -> Dict[str, Any]:
        """
        Return a single context by id.

        Raises:
            QueryError if the context does not exist.

        Response format:
            {
              "context": { ...context fields... }
            }
        """
        ctx = self.store.get_context(context_id)
        if ctx is None:
            raise QueryError(f"Context '{context_id}' not found")

        return {"context": ctx.to_dict()}

    # ------------------------------------------------------------------ #
    # State queries
    # ------------------------------------------------------------------ #

    def get_state(self, context_id: str, state_id: str) -> Dict[str, Any]:
        """
        Return a single state by id.

        Raises:
            QueryError if the context or state does not exist.

        Response format:
            {
              "context_id": "...",
              "state": { ...state record... }
            }
        """
        self._require_context(context_id)

        record = self.store.get_state(context_id, state_id)
        if record is None:
            raise QueryError(f"State '{state_id}' not found in context '{context_id}'")

        return {"context_id": context_id, "state": self._state_record_to_dict(record)}

    def list_states(
        self,
        context_id: str,
        *,
        tag: Optional[str] = None,
        source: Optional[str] = None,
        review_status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all states for a context, with optional filtering.

        Raises:
            QueryError if the context does not exist.

        Optional filters (all exact string matches, case-sensitive):
            - tag:           match a tag in StateRecord.tags (case-insensitive).
            - source:        match StateRecord.metadata["source"] (e.g. "auto", "human").
            - review_status: match StateRecord.metadata["review_status"]
                             (e.g. "pending", "verified", "rejected").

        Response format:
            {
              "context_id": "...",
              "states": [ { ...state record... }, ... ]
            }
        """
        self._require_context(context_id)

        # Base set
        if tag and not (source or review_status):
            # Use store's optimized tag lookup if only tagging is requested
            records: List[StateRecord] = self.store.find_states_by_tag(context_id, tag)
        else:
            records = list(self.store.list_states(context_id))

        # Apply metadata filters
        if source is not None:
            records = [
                r for r in records if r.metadata.get("source") == source
            ]
        if review_status is not None:
            records = [
                r
                for r in records
                if r.metadata.get("review_status") == review_status
            ]
        if tag:
            t_norm = tag.strip().lower()
            records = [
                r
                for r in records
                if any(tt.strip().lower() == t_norm for tt in r.tags)
            ]

        return {
            "context_id": context_id,
            "states": [self._state_record_to_dict(s) for s in records],
        }

    # ------------------------------------------------------------------ #
    # Transition queries
    # ------------------------------------------------------------------ #

    def get_transition(
        self,
        context_id: str,
        transition_id: str,
    ) -> Dict[str, Any]:
        """
        Return a single transition by id.

        Raises:
            QueryError if the context or transition does not exist.

        Response format:
            {
              "context_id": "...",
              "transition": { ...transition record... }
            }
        """
        self._require_context(context_id)

        record = self.store.get_transition(context_id, transition_id)
        if record is None:
            raise QueryError(
                f"Transition '{transition_id}' not found in context '{context_id}'"
            )

        return {
            "context_id": context_id,
            "transition": self._transition_record_to_dict(record),
        }

    def list_transitions(
        self,
        context_id: str,
        *,
        source: Optional[str] = None,
        review_status: Optional[str] = None,
        intent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all transitions for a context, with optional filtering.

        Raises:
            QueryError if the context does not exist.

        Optional filters (all exact string matches, case-sensitive):
            - source:        match TransitionRecord.metadata["source"].
            - review_status: match TransitionRecord.metadata["review_status"].
            - intent_id:     match Transition.intent_id.

        Response format:
            {
              "context_id": "...",
              "transitions": [ { ...transition record... }, ... ]
            }
        """
        self._require_context(context_id)

        records = list(self.store.list_transitions(context_id))

        if source is not None:
            records = [
                r for r in records if r.metadata.get("source") == source
            ]
        if review_status is not None:
            records = [
                r
                for r in records
                if r.metadata.get("review_status") == review_status
            ]
        if intent_id is not None:
            records = [
                r
                for r in records
                if r.transition.intent_id == intent_id
            ]

        return {
            "context_id": context_id,
            "transitions": [
                self._transition_record_to_dict(t) for t in records
            ],
        }

    def list_outgoing(
        self,
        context_id: str,
        state_id: str,
        *,
        source: Optional[str] = None,
        review_status: Optional[str] = None,
        intent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all outgoing transitions from a given state, with optional filters.

        Raises:
            QueryError if the context or state does not exist.

        Optional filters:
            - source:        TransitionRecord.metadata["source"].
            - review_status: TransitionRecord.metadata["review_status"].
            - intent_id:     Transition.intent_id.

        Response format:
            {
              "context_id": "...",
              "state_id": "...",
              "outgoing": [ { ...transition record... }, ... ]
            }
        """
        self._require_context(context_id)
        self._require_state(context_id, state_id)

        records = list(self.store.list_outgoing(context_id, state_id))

        if source is not None:
            records = [
                r for r in records if r.metadata.get("source") == source
            ]
        if review_status is not None:
            records = [
                r
                for r in records
                if r.metadata.get("review_status") == review_status
            ]
        if intent_id is not None:
            records = [
                r
                for r in records
                if r.transition.intent_id == intent_id
            ]

        return {
            "context_id": context_id,
            "state_id": state_id,
            "outgoing": [self._transition_record_to_dict(t) for t in records],
        }

    def list_incoming(
        self,
        context_id: str,
        state_id: str,
        *,
        source: Optional[str] = None,
        review_status: Optional[str] = None,
        intent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List all incoming transitions to a given state, with optional filters.

        Raises:
            QueryError if the context or state does not exist.

        Optional filters:
            - source:        TransitionRecord.metadata["source"].
            - review_status: TransitionRecord.metadata["review_status"].
            - intent_id:     Transition.intent_id.

        Response format:
            {
              "context_id": "...",
              "state_id": "...",
              "incoming": [ { ...transition record... }, ... ]
            }
        """
        self._require_context(context_id)
        self._require_state(context_id, state_id)

        records = list(self.store.list_incoming(context_id, state_id))

        if source is not None:
            records = [
                r for r in records if r.metadata.get("source") == source
            ]
        if review_status is not None:
            records = [
                r
                for r in records
                if r.metadata.get("review_status") == review_status
            ]
        if intent_id is not None:
            records = [
                r
                for r in records
                if r.transition.intent_id == intent_id
            ]

        return {
            "context_id": context_id,
            "state_id": state_id,
            "incoming": [self._transition_record_to_dict(t) for t in records],
        }

    # ------------------------------------------------------------------ #
    # Path queries
    # ------------------------------------------------------------------ #

    def shortest_path(
        self,
        context_id: str,
        source_state_id: str,
        target_state_id: str,
        max_depth: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Compute a shortest path between two states (in number of transitions).

        Raises:
            QueryError if the context or either state does not exist.

        Response format:
            {
              "context_id": "...",
              "source_state_id": "...",
              "target_state_id": "...",
              "path": [ { ...transition record... }, ... ]
            }

        If source == target, the path is an empty list.

        If no path exists, `path` is null.
        """
        self._require_context(context_id)
        self._require_state(context_id, source_state_id)
        self._require_state(context_id, target_state_id)

        transitions = self.store.shortest_path(
            context_id=context_id,
            source_state_id=source_state_id,
            target_state_id=target_state_id,
            max_depth=max_depth,
        )

        if transitions is None:
            path_payload: Optional[List[Dict[str, Any]]] = None
        else:
            path_payload = [
                self._transition_record_to_dict(t) for t in transitions
            ]

        return {
            "context_id": context_id,
            "source_state_id": source_state_id,
            "target_state_id": target_state_id,
            "path": path_payload,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _require_context(self, context_id: str) -> None:
        if self.store.get_context(context_id) is None:
            raise QueryError(f"Context '{context_id}' not found")

    def _require_state(self, context_id: str, state_id: str) -> None:
        if self.store.get_state(context_id, state_id) is None:
            raise QueryError(
                f"State '{state_id}' not found in context '{context_id}'"
            )

    @staticmethod
    def _state_record_to_dict(record: StateRecord) -> Dict[str, Any]:
        """
        Convert a StateRecord to a JSON-friendly dict.

        We do not use dataclasses.asdict for the nested UIState because
        UIState already has its own to_dict() format.
        """
        return {
            "context_id": record.context_id,
            "discovered_at": record.discovered_at,
            "is_entry": record.is_entry,
            "is_terminal": record.is_terminal,
            "tags": list(record.tags),
            "metadata": dict(record.metadata),
            "state": record.state.to_dict(),
        }

    @staticmethod
    def _transition_record_to_dict(
        record: TransitionRecord,
    ) -> Dict[str, Any]:
        """
        Convert a TransitionRecord to a JSON-friendly dict.

        Transition.to_dict() already returns a JSON-friendly structure,
        so we simply wrap it with TransitionRecord fields.
        """
        return {
            "context_id": record.context_id,
            "discovered_at": record.discovered_at,
            "times_observed": int(record.times_observed),
            "metadata": dict(record.metadata),
            "transition": record.transition.to_dict(),
        }
