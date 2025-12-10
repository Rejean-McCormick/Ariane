"""
CLI example: inspect Atlas workflows from the command line.

This script demonstrates how to:

- List workflows for a given context.
- Show a single workflow, optionally expanding its transitions.
- Delete a workflow by id.

It talks directly to the Atlas HTTP API workflow endpoints exposed by
`atlas/api/endpoints/workflows.py` and the HTTP server.

Endpoints used:

- GET  /workflows?context_id=...&intent_id=...&tag=...
- GET  /workflows/{workflow_id}?expand_transitions=true|false
- DELETE /workflows/{workflow_id}

This is a read/write utility for debugging and inspection, not a
production-quality tool.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

import requests

from consumers.sdk.client import AtlasClientConfig


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #


def build_headers(cfg: AtlasClientConfig) -> Dict[str, str]:
    headers: Dict[str, str] = {
        "Accept": "application/json",
    }
    if cfg.api_key:
        headers[cfg.api_key_header] = cfg.api_key
    return headers


def request_json(
    cfg: AtlasClientConfig,
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = cfg.base_url.rstrip("/") + path
    headers = build_headers(cfg)

    try:
        resp = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            params=params,
            json=body,
            timeout=cfg.timeout,
        )
    except requests.RequestException as exc:
        raise SystemExit(f"HTTP request failed: {exc}") from exc

    if resp.status_code >= 400:
        # Try to extract error body
        try:
            payload = resp.json()
        except Exception:
            payload = resp.text
        raise SystemExit(
            f"HTTP {resp.status_code} error for {method} {path}: {payload}"
        )

    try:
        return resp.json()
    except ValueError as exc:
        raise SystemExit(f"Non-JSON response from {url}: {exc}") from exc


def pretty_print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_list(cfg: AtlasClientConfig, args: argparse.Namespace) -> None:
    params: Dict[str, Any] = {}
    if args.context_id:
        params["context_id"] = args.context_id
    if args.intent_id:
        params["intent_id"] = args.intent_id
    if args.tag:
        params["tag"] = args.tag

    data = request_json(cfg, "GET", "/workflows", params=params or None)
    pretty_print(data)


def cmd_show(cfg: AtlasClientConfig, args: argparse.Namespace) -> None:
    path = f"/workflows/{args.workflow_id}"
    params = {"expand_transitions": "true" if args.expand_transitions else "false"}
    data = request_json(cfg, "GET", path, params=params)
    pretty_print(data)


def cmd_delete(cfg: AtlasClientConfig, args: argparse.Namespace) -> None:
    path = f"/workflows/{args.workflow_id}"
    data = request_json(cfg, "DELETE", path)
    pretty_print(data)


# --------------------------------------------------------------------------- #
# Argument parsing / entry point
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI example: inspect Ariane Atlas workflows."
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        help="Base URL of the Atlas API (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Optional API key for Atlas (sent via X-API-Key header)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="HTTP timeout in seconds (default: 10)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser(
        "list", help="List workflows (optionally filtered by context/intent/tag)"
    )
    p_list.add_argument(
        "--context-id",
        help="Filter workflows by context_id",
    )
    p_list.add_argument(
        "--intent-id",
        help="Filter workflows by intent_id",
    )
    p_list.add_argument(
        "--tag",
        help="Filter workflows by tag (case-insensitive exact match)",
    )
    p_list.set_defaults(func=cmd_list)

    # show
    p_show = subparsers.add_parser(
        "show", help="Show a single workflow by id"
    )
    p_show.add_argument(
        "workflow_id",
        help="Workflow identifier",
    )
    p_show.add_argument(
        "--expand-transitions",
        action="store_true",
        help="Also fetch and include full TransitionRecord payloads",
    )
    p_show.set_defaults(func=cmd_show)

    # delete
    p_delete = subparsers.add_parser(
        "delete", help="Delete a workflow by id"
    )
    p_delete.add_argument(
        "workflow_id",
        help="Workflow identifier",
    )
    p_delete.set_defaults(func=cmd_delete)

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = AtlasClientConfig(
        base_url=args.base_url,
        api_key=args.api_key,
        api_key_header="X-API-Key",
        timeout=args.timeout,
    )

    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        raise SystemExit(1)

    func(cfg, args)


if __name__ == "__main__":
    main()
