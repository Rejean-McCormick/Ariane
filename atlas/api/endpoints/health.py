"""
Health and diagnostics helpers for Ariane Atlas.

This module exposes a small, framework-agnostic "health" interface that
an HTTP layer can wrap as `/health` or `/status`.

It is intentionally simple and read-only:

- Does not mutate the store.
- Returns lightweight JSON-serializable dictionaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from atlas.storage.graph_store import GraphStore


@dataclass
class HealthHandler:
    """
    Health/status interface over a GraphStore.

    Typical HTTP usage:

        handler = HealthHandler(store)

        def get_health():
            body = handler.health()
            return 200, body
    """

    store: GraphStore

    def health(self) -> Dict[str, Any]:
        """
        Return a minimal health payload.

        This does not guarantee that all subsystems are perfect; it just
        verifies that the in-memory graph store is reachable and can be
        queried without error.

        Response format:
            {
              "status": "ok",
              "details": {
                "contexts": <int>,
                "states": <int>,
                "transitions": <int>
              }
            }
        """
        contexts = self.store.list_contexts()
        num_contexts = len(contexts)

        num_states = 0
        num_transitions = 0
        for ctx in contexts:
            num_states += len(list(self.store.iter_states(ctx.context_id)))
            num_transitions += len(list(self.store.iter_transitions(ctx.context_id)))

        return {
            "status": "ok",
            "details": {
                "contexts": num_contexts,
                "states": num_states,
                "transitions": num_transitions,
            },
        }

::contentReference[oaicite:0]{index=0}
