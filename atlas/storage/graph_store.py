"""
In-memory graph store for Ariane Atlas.

This module provides a minimal, dependency-free storage layer for:

- Context objects
- StateRecord objects (nodes)
- TransitionRecord objects (edges)

It is intentionally simple and in-memory only. It is meant as:

- A reference implementation of the graph API for Atlas.
- A useful backend for tests, prototypes, and small deployments.

A real deployment can replace this with a persistent implementation
(e.g. backed by a graph database) while preserving the same interface.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Set, Tuple

from atlas.schema.context import Context
from atlas.schema.state_schema import StateRecord
from atlas.schema.transition_schema import TransitionRecord


@dataclass
class GraphStoreConfig:
    """
    Configuration for the GraphStore.

    Currently minimal; included to make it easy to extend later with
    persistence options or limits.
    """

    # Maximum number of contexts (None = unlimited).
    max_contexts: Optional[int] = None

    # Maximum number of states/transitions per context (None = unlimited).
    max_states_per_context: Optional[int] = None
    max_transitions_per_context: Optional[int] = None


class GraphStore:
    """
    In-memory implementation of the Atlas graph store.

    The graph is partitioned by `context_id`. Each context has:

    - A mapping of state_id -> StateRecord
    - A mapping of transition_id -> TransitionRecord
    - An adjacency index for outgoing transitions
    - An adjacency index for incoming transitions
    """

    def __init__(self, config: Optional[GraphStoreConfig] = None) -> None:
        self._config = config or GraphStoreConfig()

        # context_id -> Context
        self._contexts: Dict[str, Context] = {}

        # context_id -> state_id -> StateRecord
        self._states: Dict[str, Dict[str, StateRecord]] = defaultdict(dict)

        # context_id -> transition_id -> TransitionRecord
        self._transitions: Dict[str, Dict[str, TransitionRecord]] = defaultdict(dict)

        # context_id -> source_state_id -> set(transition_id)
        self._outgoing: Dict[str, Dict[str, Set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )

        # context_id -> target_state_id -> set(transition_id)
        self._incoming: Dict[str, Dict[str, Set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )

        # Simple threading lock for in-memory operations
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ #
    # Context operations
    # ------------------------------------------------------------------ #

    def upsert_context(self, context: Context) -> None:
        """
        Insert or update a Context.

        If a context with the same id exists, it is replaced.

        Respects `max_contexts` if configured.
        """
        with self._lock:
            if (
                self._config.max_contexts is not None
                and context.context_id not in self._contexts
                and len(self._contexts) >= self._config.max_contexts
            ):
                raise RuntimeError(
                    f"GraphStore exceeded max_contexts={self._config.max_contexts}"
                )
            self._contexts[context.context_id] = context

    def add_context(self, context: Context, overwrite: bool = False) -> None:
        """
        DEPRECATED: use `upsert_context()` instead.

        Register a context.

        Args:
            context: Context to add.
            overwrite: If False, raises if the id already exists.
        """
        with self._lock:
            if not overwrite and context.context_id in self._contexts:
                raise ValueError(f"Context '{context.context_id}' already exists")
            # upsert_context handles max_contexts + assignment
            self.upsert_context(context)

    def get_context(self, context_id: str) -> Optional[Context]:
        """Return a Context by id, or None if not found."""
        with self._lock:
            return self._contexts.get(context_id)

    def list_contexts(self) -> List[Context]:
        """Return all known contexts."""
        with self._lock:
            return list(self._contexts.values())

    # ------------------------------------------------------------------ #
    # State operations
    # ------------------------------------------------------------------ #

    def upsert_state(self, record: StateRecord) -> None:
        """
        Insert or update a StateRecord.

        If a state with the same (context_id, state.id) exists, it is replaced.
        """
        ctx_id = record.context_id
        state_id = record.id

        with self._lock:
            if (
                self._config.max_states_per_context is not None
                and state_id not in self._states[ctx_id]
                and len(self._states[ctx_id]) >= self._config.max_states_per_context
            ):
                raise RuntimeError(
                    f"Context '{ctx_id}' exceeded max_states_per_context="
                    f"{self._config.max_states_per_context}"
                )

            self._states[ctx_id][state_id] = record

    def get_state(self, context_id: str, state_id: str) -> Optional[StateRecord]:
        """Return a StateRecord by context_id and state_id, or None if not found."""
        with self._lock:
            return self._states.get(context_id, {}).get(state_id)

    def iter_states(self, context_id: str) -> Iterable[StateRecord]:
        """
        Iterate over all StateRecords for a context.

        NOTE: prefer `list_states()` in new code; this returns a concrete list.
        """
        with self._lock:
            return list(self._states.get(context_id, {}).values())

    def list_states(self, context_id: str) -> List[StateRecord]:
        """Return all StateRecords for a given context as a list."""
        with self._lock:
            return list(self._states.get(context_id, {}).values())

    def find_states_by_tag(self, context_id: str, tag: str) -> List[StateRecord]:
        """Return all states in a context that have the given tag."""
        tag = tag.strip().lower()
        with self._lock:
            return [
                s
                for s in self._states.get(context_id, {}).values()
                if any(t.strip().lower() == tag for t in s.tags)
            ]

    # ------------------------------------------------------------------ #
    # Transition operations
    # ------------------------------------------------------------------ #

    def upsert_transition(
        self,
        record: TransitionRecord,
        increment_observed: bool = True,
    ) -> None:
        """
        Insert or update a TransitionRecord.

        If a transition with the same (context_id, transition.id) exists:
            - It is updated with the new transition data.
            - `times_observed` is incremented if `increment_observed` is True.

        Adjacency indexes (incoming/outgoing) are updated accordingly.
        """
        ctx_id = record.context_id
        tr_id = record.id
        src = record.source_state_id
        tgt = record.target_state_id

        with self._lock:
            ctx_transitions = self._transitions[ctx_id]

            if tr_id in ctx_transitions:
                existing = ctx_transitions[tr_id]
                # Remove old adjacency if source/target changed
                old_src = existing.source_state_id
                old_tgt = existing.target_state_id
                if old_src != src:
                    self._outgoing[ctx_id][old_src].discard(tr_id)
                if old_tgt != tgt:
                    self._incoming[ctx_id][old_tgt].discard(tr_id)

                # Merge times_observed
                if increment_observed:
                    record.times_observed = existing.times_observed + 1

            else:
                if (
                    self._config.max_transitions_per_context is not None
                    and len(ctx_transitions) >= self._config.max_transitions_per_context
                ):
                    raise RuntimeError(
                        f"Context '{ctx_id}' exceeded max_transitions_per_context="
                        f"{self._config.max_transitions_per_context}"
                    )

            # Store transition
            ctx_transitions[tr_id] = record

            # Update adjacency
            self._outgoing[ctx_id][src].add(tr_id)
            self._incoming[ctx_id][tgt].add(tr_id)

    def get_transition(
        self,
        context_id: str,
        transition_id: str,
    ) -> Optional[TransitionRecord]:
        """Return a TransitionRecord by context_id and transition_id, or None if not found."""
        with self._lock:
            return self._transitions.get(context_id, {}).get(transition_id)

    def iter_transitions(self, context_id: str) -> Iterable[TransitionRecord]:
        """
        Iterate over all TransitionRecords for a context.

        NOTE: prefer `list_transitions()` in new code; this returns a concrete list.
        """
        with self._lock:
            return list(self._transitions.get(context_id, {}).values())

    def list_transitions(self, context_id: str) -> List[TransitionRecord]:
        """Return all TransitionRecords for a given context as a list."""
        with self._lock:
            return list(self._transitions.get(context_id, {}).values())

    def get_outgoing_transitions(
        self,
        context_id: str,
        state_id: str,
    ) -> List[TransitionRecord]:
        """
        Return all outgoing transitions from a given state.

        NOTE: prefer `list_outgoing()` in new code; this name is kept for
        backwards compatibility.
        """
        with self._lock:
            transition_ids = self._outgoing.get(context_id, {}).get(state_id, set())
            ctx_transitions = self._transitions.get(context_id, {})
            return [
                ctx_transitions[tid]
                for tid in transition_ids
                if tid in ctx_transitions
            ]

    def get_incoming_transitions(
        self,
        context_id: str,
        state_id: str,
    ) -> List[TransitionRecord]:
        """
        Return all incoming transitions to a given state.

        NOTE: prefer `list_incoming()` in new code; this name is kept for
        backwards compatibility.
        """
        with self._lock:
            transition_ids = self._incoming.get(context_id, {}).get(state_id, set())
            ctx_transitions = self._transitions.get(context_id, {})
            return [
                ctx_transitions[tid]
                for tid in transition_ids
                if tid in ctx_transitions
            ]

    def list_outgoing(
        self,
        context_id: str,
        state_id: str,
    ) -> List[TransitionRecord]:
        """Return all outgoing transitions from a given state."""
        return self.get_outgoing_transitions(context_id, state_id)

    def list_incoming(
        self,
        context_id: str,
        state_id: str,
    ) -> List[TransitionRecord]:
        """Return all incoming transitions to a given state."""
        return self.get_incoming_transitions(context_id, state_id)

    # ------------------------------------------------------------------ #
    # Graph queries
    # ------------------------------------------------------------------ #

    def shortest_path(
        self,
        context_id: str,
        source_state_id: str,
        target_state_id: str,
        max_depth: Optional[int] = None,
    ) -> Optional[List[TransitionRecord]]:
        """
        Compute a shortest path (in number of transitions) between two states
        using BFS over the in-memory graph.

        Returns:
            List of TransitionRecord objects representing the path
            from source to target (exclusive of source state),
            or None if no path is found.

        Args:
            context_id: Graph context to search in.
            source_state_id: Start state.
            target_state_id: Goal state.
            max_depth: Optional depth limit; if provided, BFS will not expand
                       beyond this number of steps.
        """
        if source_state_id == target_state_id:
            return []

        with self._lock:
            ctx_transitions = self._transitions.get(context_id, {})
            outgoing = self._outgoing.get(context_id, {})

            if not ctx_transitions:
                return None

            queue: Deque[str] = deque()
            queue.append(source_state_id)

            visited: Set[str] = {source_state_id}
            # state_id -> (prev_state_id, transition_id)
            prev: Dict[str, Tuple[Optional[str], Optional[str]]] = {
                source_state_id: (None, None)
            }
            depth: Dict[str, int] = {source_state_id: 0}

            while queue:
                current = queue.popleft()
                current_depth = depth[current]

                if max_depth is not None and current_depth >= max_depth:
                    continue

                for tr_id in outgoing.get(current, []):
                    tr = ctx_transitions.get(tr_id)
                    if tr is None:
                        continue

                    nxt = tr.target_state_id
                    if nxt in visited:
                        continue

                    visited.add(nxt)
                    prev[nxt] = (current, tr_id)
                    depth[nxt] = current_depth + 1

                    if nxt == target_state_id:
                        # Reconstruct path
                        return self._reconstruct_path(context_id, prev, target_state_id)

                    queue.append(nxt)

            # No path found
            return None

    def _reconstruct_path(
        self,
        context_id: str,
        prev: Dict[str, Tuple[Optional[str], Optional[str]]],
        target_state_id: str,
    ) -> List[TransitionRecord]:
        """Internal helper to reconstruct a path after BFS."""
        ctx_transitions = self._transitions.get(context_id, {})

        path_transitions: List[TransitionRecord] = []
        current = target_state_id

        while True:
            prev_state, tr_id = prev.get(current, (None, None))
            if prev_state is None or tr_id is None:
                break
            tr = ctx_transitions.get(tr_id)
            if tr is not None:
                path_transitions.append(tr)
            current = prev_state

        path_transitions.reverse()
        return path_transitions
