#!/usr/bin/env python3
"""
CLI example: minimal "agent" on top of Ariane Atlas.

This example shows how a command-line tool (or an AI agent) might use the
Atlas HTTP API to:

- List available contexts.
- Inspect states and their interactive elements.
- Find a shortest path between two states.

It uses only:

- `consumers.sdk.client.AtlasClient`
- `consumers.sdk.types.*`
- The Python standard library

Usage examples:

    # Check server health
    python -m consumers.examples.cli-agent-example \
        --base-url http://localhost:8080 health

    # List contexts
    python -m consumers.examples.cli-agent-example \
        --base-url http://localhost:8080 contexts

    # List states for a context
    python -m consumers.examples.cli-agent-example \
        --base-url http://localhost:8080 states --context-id YOUR_CTX_ID

    # Find shortest path between two states
    python -m consumers.examples.cli-agent-example \
        --base-url http://localhost:8080 path \
        --context-id YOUR_CTX_ID \
        --source STATE_A \
        --target STATE_B
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from consumers.sdk.client import AtlasClient, AtlasClientConfig, AtlasClientError
from consumers.sdk.types import ContextInfo, PathView, StateView, TransitionView


# --------------------------------------------------------------------------- #
# Pretty printers
# --------------------------------------------------------------------------- #


def print_contexts(contexts: List[ContextInfo]) -> None:
    if not contexts:
        print("No contexts found.")
        return

    for ctx in contexts:
        print(f"* context_id: {ctx.context_id}")
        print(f"  app_id:     {ctx.app_id}")
        if ctx.version:
            print(f"  version:    {ctx.version}")
        if ctx.platform:
            print(f"  platform:   {ctx.platform}")
        if ctx.locale:
            print(f"  locale:     {ctx.locale}")
        print()


def print_states(states: List[StateView]) -> None:
    if not states:
        print("No states found.")
        return

    for s in states:
        entry_flag = " (entry)" if s.is_entry else ""
        term_flag = " (terminal)" if s.is_terminal else ""
        print(f"* state_id: {s.state_id}{entry_flag}{term_flag}")
        print(f"  discovered_at:  {s.discovered_at}")
        print(f"  app_id:         {s.app_id}")
        if s.version:
            print(f"  version:        {s.version}")
        if s.platform:
            print(f"  platform:       {s.platform}")
        if s.locale:
            print(f"  locale:         {s.locale}")
        print(f"  tags:           {', '.join(s.tags) if s.tags else '-'}")
        print(f"  elements:       {len(s.interactive_elements)}")

        # Show a few interactive elements as hints
        for el in s.interactive_elements[:5]:
            label = f" label='{el.label}'" if el.label else ""
            print(f"    - [{el.role}] {el.id}{label}")

        if len(s.interactive_elements) > 5:
            print(f"    ... +{len(s.interactive_elements) - 5} more element(s)")
        print()


def print_transitions(transitions: List[TransitionView]) -> None:
    if not transitions:
        print("No transitions found.")
        return

    for t in transitions:
        print(f"* transition_id: {t.transition_id}")
        print(f"  {t.source_state_id} -> {t.target_state_id}")
        print(f"  action.type:   {t.action.type}")
        if t.action.element_id:
            print(f"  element_id:    {t.action.element_id}")
        if t.intent_id:
            print(f"  intent_id:     {t.intent_id}")
        print(f"  confidence:    {t.confidence:.3f}")
        print(f"  times_observed:{t.times_observed}")
        print()


def print_path(path: PathView) -> None:
    print(f"context_id:     {path.context_id}")
    print(f"source_state_id:{path.source_state_id}")
    print(f"target_state_id:{path.target_state_id}")
    print()

    if path.transitions is None:
        print("No path found.")
        return

    if not path.transitions:
        print("Source and target are the same state (empty path).")
        return

    print(f"Path length: {len(path.transitions)} transition(s)")
    print()

    for i, t in enumerate(path.transitions, start=1):
        print(f"Step {i}:")
        print(f"  transition_id: {t.transition_id}")
        print(f"  from:          {t.source_state_id}")
        print(f"  to:            {t.target_state_id}")
        print(f"  action.type:   {t.action.type}")
        if t.action.element_id:
            print(f"  element_id:    {t.action.element_id}")
        if t.intent_id:
            print(f"  intent_id:     {t.intent_id}")
        print()


# --------------------------------------------------------------------------- #
# Command handlers
# --------------------------------------------------------------------------- #


def cmd_health(client: AtlasClient) -> int:
    data = client.health()
    print("Health:")
    print(data)
    return 0


def cmd_contexts(client: AtlasClient) -> int:
    contexts = client.list_contexts()
    print_contexts(contexts)
    return 0


def cmd_states(client: AtlasClient, args: argparse.Namespace) -> int:
    ctx_id = args.context_id
    if not ctx_id:
        print("Error: --context-id is required for 'states' command.", file=sys.stderr)
        return 1

    states = client.list_states(ctx_id)
    print_states(states)
    return 0


def cmd_transitions(client: AtlasClient, args: argparse.Namespace) -> int:
    ctx_id = args.context_id
    if not ctx_id:
        print("Error: --context-id is required for 'transitions' command.", file=sys.stderr)
        return 1

    transitions = client.list_transitions(ctx_id)
    print_transitions(transitions)
    return 0


def cmd_path(client: AtlasClient, args: argparse.Namespace) -> int:
    ctx_id = args.context_id
    src = args.source
    tgt = args.target
    max_depth = args.max_depth

    missing = []
    if not ctx_id:
        missing.append("--context-id")
    if not src:
        missing.append("--source")
    if not tgt:
        missing.append("--target")

    if missing:
        print(
            "Error: missing required argument(s): " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    path = client.shortest_path(
        context_id=ctx_id,
        source_state_id=src,
        target_state_id=tgt,
        max_depth=max_depth,
    )
    print_path(path)
    return 0


# --------------------------------------------------------------------------- #
# CLI setup
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI example for querying Ariane Atlas.",
    )

    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the Atlas HTTP server (e.g. http://localhost:8080)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key for authenticated requests.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="HTTP timeout in seconds (default: 10).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # health
    subparsers.add_parser("health", help="Check server health.")

    # contexts
    subparsers.add_parser("contexts", help="List known contexts.")

    # states
    p_states = subparsers.add_parser("states", help="List states in a context.")
    p_states.add_argument(
        "--context-id",
        required=True,
        help="Context ID whose states should be listed.",
    )

    # transitions
    p_transitions = subparsers.add_parser(
        "transitions",
        help="List transitions in a context.",
    )
    p_transitions.add_argument(
        "--context-id",
        required=True,
        help="Context ID whose transitions should be listed.",
    )

    # path
    p_path = subparsers.add_parser(
        "path",
        help="Compute shortest path between two states.",
    )
    p_path.add_argument(
        "--context-id",
        required=True,
        help="Context ID in which to search.",
    )
    p_path.add_argument(
        "--source",
        required=True,
        help="Source state ID.",
    )
    p_path.add_argument(
        "--target",
        required=True,
        help="Target state ID.",
    )
    p_path.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Optional depth limit for path search.",
    )

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = AtlasClientConfig(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    client = AtlasClient(cfg)

    try:
        if args.command == "health":
            return cmd_health(client)
        if args.command == "contexts":
            return cmd_contexts(client)
        if args.command == "states":
            return cmd_states(client, args)
        if args.command == "transitions":
            return cmd_transitions(client, args)
        if args.command == "path":
            return cmd_path(client, args)

        parser.print_help()
        return 1

    except AtlasClientError as exc:
        print(f"AtlasClientError: {exc}", file=sys.stderr)
        if exc.raw_body:
            print("--- raw response body ---", file=sys.stderr)
            print(exc.raw_body, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
