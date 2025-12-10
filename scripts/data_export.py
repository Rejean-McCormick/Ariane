#!/usr/bin/env python3
"""
Atlas data export utility.

This script exports Atlas data (contexts, states, transitions) to JSON
files using the HTTP API exposed by `atlas.api.http_server`.

It is built on top of the consumer SDK (AtlasClient) and uses only the
Python standard library otherwise.

Typical usage:

    # List contexts
    python scripts/data_export.py \
        --base-url http://localhost:8080 \
        list-contexts

    # Export a single context to a JSON file
    python scripts/data_export.py \
        --base-url http://localhost:8080 \
        export-context \
        --context-id YOUR_CONTEXT_ID \
        --output atlas_export.json

    # Export all contexts to individual files in a directory
    python scripts/data_export.py \
        --base-url http://localhost:8080 \
        export-all \
        --output-dir ./atlas_exports
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from consumers.sdk.client import AtlasClient, AtlasClientConfig, AtlasClientError
from consumers.sdk.types import ContextInfo


JSONDict = Dict[str, Any]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def context_to_dict(ctx: ContextInfo) -> JSONDict:
    """
    Convert a ContextInfo dataclass into a dict compatible with
    the Context.to_dict() shape used by the Atlas API.
    """
    return {
        "context_id": ctx.context_id,
        "app_id": ctx.app_id,
        "version": ctx.version,
        "platform": ctx.platform,
        "locale": ctx.locale,
        "schema_version": ctx.schema_version,
        "created_at": ctx.created_at,
        "environment": dict(ctx.environment or {}),
        "metadata": dict(ctx.metadata or {}),
    }


def sanitize_filename(s: str) -> str:
    """
    Sanitize a string for use as a filename.

    Replaces any non-alphanumeric character with '_'.
    """
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def export_single_context(
    client: AtlasClient,
    context_id: str,
    output_path: Path,
) -> None:
    """
    Export a single context to a JSON file.

    The bundle format matches the Theseus exporter and /ingest/bundle:

        {
          "context": { ... },
          "states": [ { ...state_record... }, ... ],
          "transitions": [ { ...transition_record... }, ... ]
        }
    """
    # Fetch context metadata via SDK
    ctx = client.get_context(context_id)
    ctx_dict = context_to_dict(ctx)

    # Use low-level request to obtain raw state/transition records
    status_states, states_payload, _ = client._request(  # type: ignore[attr-defined]
        "GET",
        f"/contexts/{context_id}/states",
    )
    status_trans, transitions_payload, _ = client._request(  # type: ignore[attr-defined]
        "GET",
        f"/contexts/{context_id}/transitions",
    )

    if status_states >= 400:
        raise AtlasClientError(f"Failed to fetch states for context {context_id}")
    if status_trans >= 400:
        raise AtlasClientError(f"Failed to fetch transitions for context {context_id}")

    states = states_payload.get("states") or []
    transitions = transitions_payload.get("transitions") or []

    bundle: JSONDict = {
        "context": ctx_dict,
        "states": states,
        "transitions": transitions,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)

    print(f"Exported context {context_id} → {output_path}")


# --------------------------------------------------------------------------- #
# Command handlers
# --------------------------------------------------------------------------- #


def cmd_list_contexts(client: AtlasClient, _args: argparse.Namespace) -> int:
    contexts = client.list_contexts()
    if not contexts:
        print("No contexts found.")
        return 0

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
    return 0


def cmd_export_context(client: AtlasClient, args: argparse.Namespace) -> int:
    ctx_id = args.context_id
    if not ctx_id:
        print("Error: --context-id is required for 'export-context'.", file=sys.stderr)
        return 1

    output = Path(args.output) if args.output else Path(
        f"atlas_export_{sanitize_filename(ctx_id)}.json"
    )

    try:
        export_single_context(client, ctx_id, output)
    except AtlasClientError as exc:
        print(f"AtlasClientError: {exc}", file=sys.stderr)
        if exc.raw_body:
            print("--- raw response body ---", file=sys.stderr)
            print(exc.raw_body, file=sys.stderr)
        return 2

    return 0


def cmd_export_all(client: AtlasClient, args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir)
    contexts = client.list_contexts()

    if not contexts:
        print("No contexts found to export.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)

    failures = 0
    for ctx in contexts:
        filename = f"atlas_export_{sanitize_filename(ctx.context_id)}.json"
        path = out_dir / filename
        try:
            export_single_context(client, ctx.context_id, path)
        except AtlasClientError as exc:
            failures += 1
            print(f"Failed to export {ctx.context_id}: {exc}", file=sys.stderr)
            if exc.raw_body:
                print("--- raw response body ---", file=sys.stderr)
                print(exc.raw_body, file=sys.stderr)

    if failures:
        print(f"Completed with {failures} failure(s).", file=sys.stderr)
        return 2
    return 0


# --------------------------------------------------------------------------- #
# CLI setup
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export data from an Ariane Atlas HTTP server.",
    )

    parser.add_argument(
        "--base-url",
        required=True,
        help="Base URL of the Atlas server (e.g. http://localhost:8080).",
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

    # list-contexts
    subparsers.add_parser(
        "list-contexts",
        help="List all contexts known to the Atlas server.",
    )

    # export-context
    p_export_ctx = subparsers.add_parser(
        "export-context",
        help="Export a single context (context + states + transitions) to JSON.",
    )
    p_export_ctx.add_argument(
        "--context-id",
        required=True,
        help="Context ID to export.",
    )
    p_export_ctx.add_argument(
        "--output",
        default=None,
        help=(
            "Output file path. If omitted, a default name like "
            "'atlas_export_<context>.json' is used in the current directory."
        ),
    )

    # export-all
    p_export_all = subparsers.add_parser(
        "export-all",
        help="Export all contexts to individual JSON files in a directory.",
    )
    p_export_all.add_argument(
        "--output-dir",
        default="./atlas_exports",
        help="Directory where export files will be written (default: ./atlas_exports).",
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
        if args.command == "list-contexts":
            return cmd_list_contexts(client, args)
        if args.command == "export-context":
            return cmd_export_context(client, args)
        if args.command == "export-all":
            return cmd_export_all(client, args)

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
