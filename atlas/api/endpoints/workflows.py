"""
Workflow endpoint helpers for Ariane Atlas.

This module defines a small, framework-agnostic workflow layer that
sits alongside the GraphStore.

A *workflow* is a named, ordered sequence of transition ids inside a
single context, with associated metadata (label, description, tags,
intent_id, etc.). It does NOT duplicate the transitions themselves;
it only references existing TransitionRecord entries in the GraphStore.

It does NOT implement HTTP handling directly. Instead, it provides
pure Python classes/functions that accept JSON-like payloads (dicts)
and return JSON-serializable dicts.

Typical usage from an HTTP server:

    workflow_store = WorkflowStore()
    handler = WorkflowHandler(graph_store, workflow_store)

    def post_workflow(request_body: dict):
        try:
            result = handler.upsert_workflow(request_body)
            return 200, result
        except WorkflowError as e:
            return 400, {"error": str(e)}

    def get_workflow(workflow_id: str, expand: bool):
        try:
            result = handler.get_workflow(workflow_id, expand_transitions=expand)
            return 200, result
        except WorkflowError as e:
            return 404, {"error": str(e)}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from atlas.schema.transition_schema import TransitionRecord
from atlas.storage.graph_store import GraphStore


class WorkflowError(Exception):
    """
    Raised when workflow operations fail due to invalid parameters
    or missing data.

    HTTP servers should map this to a 4xx error, typically 400 or 404.
    """


@dataclass
class Workflow:
    """
    In-memory representation of a named workflow.

    A workflow is defined entirely in terms of existing transitions in a
    single context. It does not duplicate transition data; it stores only
    ids and metadata.
    """

    workflow_id: str
    context_id: str

    label: str
    description: str

    transition_ids: List[str]

    intent_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to a JSON-serializable dict.

        This shape is intended for both API responses and storage.
        """
        return {
            "workflow_id": self.workflow_id,
            "context_id": self.context_id,
            "label": self.label,
            "description": self.description,
            "transition_ids": list(self.transition_ids),
            "intent_id": self.intent_id,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "Workflow":
        """
        Construct a Workflow from a JSON-like dict.

        Expected payload shape:
            {
              "workflow_id": "...",
              "context_id": "...",
              "label": "...",
              "description": "...",
              "transition_ids": [ "...", ... ],
              "intent_id": "...",          # optional
              "tags": [ "...", ... ],      # optional
              "metadata": { ... }          # optional
            }
        """
        if not isinstance(payload, dict):
            raise WorkflowError("Workflow payload must be an object")

        try:
            workflow_id = str(payload["workflow_id"])
            context_id = str(payload["context_id"])
            label = str(payload["label"])
            description = str(payload["description"])
            transition_ids_raw = payload.get("transition_ids", [])
        except KeyError as exc:
            raise WorkflowError(f"Missing workflow field: {exc}") from exc

        if not isinstance(transition_ids_raw, list):
            raise WorkflowError("workflow.transition_ids must be a list")

        transition_ids: List[str] = [str(tid) for tid in transition_ids_raw]

        intent_id_raw = payload.get("intent_id")
        intent_id: Optional[str] = None
        if intent_id_raw is not None:
            intent_id = str(intent_id_raw)

        tags_raw = payload.get("tags", [])
        if not isinstance(tags_raw, list):
            raise WorkflowError("workflow.tags must be a list when provided")
        tags: List[str] = [str(tag) for tag in tags_raw]

        metadata_raw = payload.get("metadata", {})
        if metadata_raw is None:
            metadata_raw = {}
        if not isinstance(metadata_raw, dict):
            raise WorkflowError("workflow.metadata must be an object when provided")

        return Workflow(
            workflow_id=workflow_id,
            context_id=context_id,
            label=label,
            description=description,
            transition_ids=transition_ids,
            intent_id=intent_id,
            tags=tags,
            metadata=metadata_raw,
        )


@dataclass
class WorkflowStore:
    """
    In-memory storage for Workflow objects.

    This is intentionally simple and separate from GraphStore. It stores
    only workflow definitions (names, metadata, transition id lists).
    """

    # workflow_id -> Workflow
    _workflows: Dict[str, Workflow] = field(default_factory=dict)

    # context_id -> set(workflow_id)
    _by_context: Dict[str, Set[str]] = field(default_factory=dict)

    def upsert_workflow(self, workflow: Workflow) -> None:
        """
        Insert or update a workflow definition.
        """
        self._workflows[workflow.workflow_id] = workflow
        ctx_ids = self._by_context.setdefault(workflow.context_id, set())
        ctx_ids.add(workflow.workflow_id)

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        """
        Return a workflow by id, or None if not found.
        """
        return self._workflows.get(workflow_id)

    def list_workflows(
        self,
        context_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Workflow]:
        """
        List workflows, optionally filtered by context, intent_id, and tag.
        """
        if context_id is not None:
            ids = self._by_context.get(context_id, set())
            workflows = [self._workflows[w_id] for w_id in ids]
        else:
            workflows = list(self._workflows.values())

        if intent_id is not None:
            workflows = [
                wf for wf in workflows if wf.intent_id == intent_id
            ]

        if tag is not None:
            t_norm = tag.strip().lower()
            workflows = [
                wf
                for wf in workflows
                if any(tt.strip().lower() == t_norm for tt in wf.tags)
            ]

        return workflows

    def delete_workflow(self, workflow_id: str) -> bool:
        """
        Delete a workflow by id.

        Returns True if it existed and was removed, False otherwise.
        """
        wf = self._workflows.pop(workflow_id, None)
        if wf is None:
            return False

        ctx_set = self._by_context.get(wf.context_id)
        if ctx_set is not None:
            ctx_set.discard(workflow_id)
            if not ctx_set:
                self._by_context.pop(wf.context_id, None)
        return True


@dataclass
class WorkflowHandler:
    """
    High-level workflow query / management interface.

    This sits on top of:

    - GraphStore: used to validate context_id and referenced transitions.
    - WorkflowStore: used to store and retrieve workflow definitions.

    Methods return JSON-serializable dictionaries suitable for HTTP responses.
    """

    store: GraphStore
    workflow_store: WorkflowStore

    # ------------------------------------------------------------------ #
    # Creation / update
    # ------------------------------------------------------------------ #

    def upsert_workflow(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create or update a workflow.

        Payload shape (see Workflow.from_dict for details):
            {
              "workflow_id": "...",
              "context_id": "...",
              "label": "...",
              "description": "...",
              "transition_ids": [ "...", ... ],
              "intent_id": "...",        # optional
              "tags": [ "...", ... ],    # optional
              "metadata": { ... }        # optional
            }

        Validation performed:

        - Context must exist in GraphStore.
        - All transition_ids must exist in GraphStore under the same context_id.

        Response:
            {
              "status": "ok",
              "workflow": { ...workflow fields... }
            }
        """
        workflow = Workflow.from_dict(payload)

        # Validate context
        if self.store.get_context(workflow.context_id) is None:
            raise WorkflowError(f"Context '{workflow.context_id}' not found")

        # Validate that all referenced transitions exist in the given context
        missing: List[str] = []
        for tr_id in workflow.transition_ids:
            tr = self.store.get_transition(workflow.context_id, tr_id)
            if tr is None:
                missing.append(tr_id)

        if missing:
            missing_str = ", ".join(missing)
            raise WorkflowError(
                f"Transitions not found in context '{workflow.context_id}': {missing_str}"
            )

        # Store the workflow definition
        self.workflow_store.upsert_workflow(workflow)

        return {
            "status": "ok",
            "workflow": workflow.to_dict(),
        }

    # ------------------------------------------------------------------ #
    # Retrieval
    # ------------------------------------------------------------------ #

    def get_workflow(
        self,
        workflow_id: str,
        *,
        expand_transitions: bool = False,
    ) -> Dict[str, Any]:
        """
        Retrieve a single workflow by id.

        Args:
            workflow_id: Identifier of the workflow.
            expand_transitions: If True, the response will also include
                a `transitions` field with fully expanded TransitionRecord
                payloads (using the same shape as the query endpoints).

        Response if found:
            {
              "workflow": { ...workflow fields... },
              "transitions": [ { ...transition record... }, ... ]  # optional
            }

        Raises:
            WorkflowError if the workflow does not exist.
        """
        workflow = self.workflow_store.get_workflow(workflow_id)
        if workflow is None:
            raise WorkflowError(f"Workflow '{workflow_id}' not found")

        response: Dict[str, Any] = {
            "workflow": workflow.to_dict(),
        }

        if expand_transitions:
            # Resolve transitions via GraphStore
            records: List[TransitionRecord] = []
            for tr_id in workflow.transition_ids:
                tr = self.store.get_transition(workflow.context_id, tr_id)
                if tr is None:
                    # If a transition disappeared, we still return others,
                    # but flag the missing id in the response.
                    continue
                records.append(tr)

            response["transitions"] = [
                self._transition_record_to_dict(rec) for rec in records
            ]

        return response

    def list_workflows(
        self,
        *,
        context_id: Optional[str] = None,
        intent_id: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        List workflows, with optional filtering.

        Args:
            context_id: Restrict to a single context (optional).
            intent_id:  Restrict to workflows with this intent_id (optional).
            tag:        Restrict to workflows containing this tag
                        (case-insensitive, exact match after stripping).

        Response:
            {
              "context_id": "... or null ...",
              "workflows": [
                { ...workflow fields... },
                ...
              ]
            }
        """
        if context_id is not None and self.store.get_context(context_id) is None:
            raise WorkflowError(f"Context '{context_id}' not found")

        workflows = self.workflow_store.list_workflows(
            context_id=context_id,
            intent_id=intent_id,
            tag=tag,
        )

        return {
            "context_id": context_id,
            "workflows": [wf.to_dict() for wf in workflows],
        }

    # ------------------------------------------------------------------ #
    # Deletion
    # ------------------------------------------------------------------ #

    def delete_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """
        Delete a workflow by id.

        Response:
            {
              "status": "ok",
              "deleted": true/false
            }

        If the workflow does not exist, `deleted` is False.
        """
        deleted = self.workflow_store.delete_workflow(workflow_id)
        return {
            "status": "ok",
            "deleted": bool(deleted),
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _transition_record_to_dict(record: TransitionRecord) -> Dict[str, Any]:
        """
        Convert a TransitionRecord to a JSON-friendly dict.

        This matches the shape used by the query endpoints.
        """
        return {
            "context_id": record.context_id,
            "discovered_at": record.discovered_at,
            "times_observed": int(record.times_observed),
            "metadata": dict(record.metadata),
            "transition": record.transition.to_dict(),
        }
