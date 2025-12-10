"""
Minimal HTTP server for Ariane Atlas.

This is a small, dependency-free JSON API built on Python's standard
library (http.server). It wires together:

- GraphStore
- IngestHandler
- QueryHandler
- HealthHandler
- Authenticator (optional)

It is intended for development, prototypes, and small deployments.
For production, you would typically reimplement the HTTP layer using
a more robust framework, keeping the same handlers/endpoints.
"""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from atlas.api.auth import AuthError, Authenticator, AuthConfig
from atlas.api.endpoints.health import HealthHandler
from atlas.api.endpoints.ingest import IngestError, IngestHandler
from atlas.api.endpoints.query import QueryError, QueryHandler
from atlas.schema.context import Context
from atlas.storage.graph_store import GraphStore, GraphStoreConfig


LOG = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Server wiring
# --------------------------------------------------------------------------- #


class AtlasApp:
    """
    Container for the core Atlas components used by the HTTP server.

    This keeps the creation of GraphStore, handlers, and auth logic in one
    place, and allows tests to instantiate a server programmatically.
    """

    def __init__(
        self,
        graph_config: Optional[GraphStoreConfig] = None,
        auth_config: Optional[AuthConfig] = None,
    ) -> None:
        store = GraphStore(config=graph_config)
        self.store = store

        self.ingest = IngestHandler(store=store)
        self.query = QueryHandler(store=store)
        self.health = HealthHandler(store=store)

        self.authenticator: Optional[Authenticator] = (
            Authenticator(auth_config) if auth_config is not None else None
        )


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #


class AtlasRequestHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for Atlas.

    Expected to be used with an AtlasApp attached to the server:

        app = AtlasApp(...)
        server = HTTPServer(("0.0.0.0", 8080), AtlasRequestHandler)
        server.app = app
        server.serve_forever()
    """

    # Silence default noisy logging; we use logging module instead.
    def log_message(self, format: str, *args: Any) -> None:  # type: ignore[override]
        LOG.info("%s - %s", self.address_string(), format % args)

    # --- helpers ------------------------------------------------------------ #

    @property
    def app(self) -> AtlasApp:
        srv = self.server  # type: ignore[attr-defined]
        return srv.app  # type: ignore[attr-defined]

    def _read_json_body(self) -> Dict[str, Any]:
        """
        Read and parse JSON request body into a dict or list.

        Raises:
            ValueError if the body is not valid JSON.
        """
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            return {}
        try:
            length = int(length_header)
        except ValueError:
            raise ValueError("Invalid Content-Length header")

        raw = self.rfile.read(length)
        if not raw:
            return {}

        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON payload: {exc}") from exc

        return payload

    def _send_json(
        self, status: int, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Send a JSON response with the given HTTP status and payload.
        """
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _auth(self) -> None:
        """
        Perform authentication if an Authenticator is configured.

        Raises:
            AuthError if authentication fails.
        """
        if self.app.authenticator is None:
            return  # no auth configured
        # Treat auth as required for all endpoints; adjust as needed.
        self.app.authenticator.require_auth(self.headers)

    # ------------------------------------------------------------------ #
    # HTTP verbs
    # ------------------------------------------------------------------ #

    def do_GET(self) -> None:  # type: ignore[override]
        try:
            self._auth()
            self._handle_get()
        except AuthError as exc:
            LOG.warning("Auth error: %s", exc)
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "unauthorized", "detail": str(exc)},
            )
        except QueryError as exc:
            LOG.warning("Query error: %s", exc)
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "query_error", "detail": str(exc)},
            )
        except Exception as exc:
            LOG.exception("Unhandled error in GET")
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error", "detail": str(exc)},
            )

    def do_POST(self) -> None:  # type: ignore[override]
        try:
            self._auth()
            self._handle_post()
        except AuthError as exc:
            LOG.warning("Auth error: %s", exc)
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "unauthorized", "detail": str(exc)},
            )
        except (IngestError, ValueError) as exc:
            LOG.warning("Ingest error: %s", exc)
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "ingest_error", "detail": str(exc)},
            )
        except Exception as exc:
            LOG.exception("Unhandled error in POST")
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "internal_error", "detail": str(exc)},
            )

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query_params = parse_qs(parsed.query)

        # /health
        if path == "/health":
            payload = self.app.health.health()
            self._send_json(HTTPStatus.OK, payload)
            return

        # /contexts
        if path == "/contexts":
            payload = self.app.query.list_contexts()
            self._send_json(HTTPStatus.OK, payload)
            return

        # Paths under /contexts/...
        if path.startswith("/contexts/"):
            self._handle_get_context_scoped(path, query_params)
            return

        # Not found
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"error": "not_found", "detail": f"Unknown GET path: {path}"},
        )

    def _handle_get_context_scoped(
        self, path: str, query_params: Dict[str, Any]
    ) -> None:
        """
        Handle GET requests under /contexts/{context_id}/...
        """
        # Split path like /contexts/{ctx}/states or /contexts/{ctx}/states/{state}
        parts = [p for p in path.split("/") if p]

        # Expected shapes:
        #  ["contexts", "{ctx}"]
        #  ["contexts", "{ctx}", "states"]
        #  ["contexts", "{ctx}", "states", "{state}"]
        #  ["contexts", "{ctx}", "states", "{state}", "outgoing"]
        #  ["contexts", "{ctx}", "states", "{state}", "incoming"]
        #  ["contexts", "{ctx}", "transitions"]
        #  ["contexts", "{ctx}", "transitions", "{transition}"]
        #  ["contexts", "{ctx}", "path"]

        if len(parts) < 2:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"error": "not_found", "detail": f"Invalid context path: {path}"},
            )
            return

        context_id = parts[1]

        if len(parts) == 2:
            # GET /contexts/{ctx}
            payload = self.app.query.get_context(context_id)
            self._send_json(HTTPStatus.OK, payload)
            return

        resource = parts[2]

        # /contexts/{ctx}/states...
        if resource == "states":
            if len(parts) == 3:
                # GET /contexts/{ctx}/states
                payload = self.app.query.list_states(context_id)
                self._send_json(HTTPStatus.OK, payload)
                return

            state_id = parts[3]

            if len(parts) == 4:
                # GET /contexts/{ctx}/states/{state}
                payload = self.app.query.get_state(context_id, state_id)
                self._send_json(HTTPStatus.OK, payload)
                return

            # /contexts/{ctx}/states/{state}/outgoing or incoming
            if len(parts) == 5:
                sub = parts[4]
                if sub == "outgoing":
                    payload = self.app.query.list_outgoing(context_id, state_id)
                    self._send_json(HTTPStatus.OK, payload)
                    return
                if sub == "incoming":
                    payload = self.app.query.list_incoming(context_id, state_id)
                    self._send_json(HTTPStatus.OK, payload)
                    return

        # /contexts/{ctx}/transitions...
        if resource == "transitions":
            if len(parts) == 3:
                # GET /contexts/{ctx}/transitions
                payload = self.app.query.list_transitions(context_id)
                self._send_json(HTTPStatus.OK, payload)
                return

            if len(parts) == 4:
                transition_id = parts[3]
                # GET /contexts/{ctx}/transitions/{transition}
                payload = self.app.query.get_transition(context_id, transition_id)
                self._send_json(HTTPStatus.OK, payload)
                return

        # /contexts/{ctx}/path?source=...&target=...&max_depth=...
        if resource == "path":
            source = self._get_single_query_param(query_params, "source")
            target = self._get_single_query_param(query_params, "target")
            max_depth_str = self._get_single_query_param(query_params, "max_depth")

            if source is None or target is None:
                raise QueryError("Missing 'source' or 'target' query parameter")

            max_depth = None
            if max_depth_str is not None:
                try:
                    max_depth = int(max_depth_str)
                except ValueError:
                    raise QueryError("Invalid 'max_depth' parameter; must be an integer")

            payload = self.app.query.shortest_path(
                context_id=context_id,
                source_state_id=source,
                target_state_id=target,
                max_depth=max_depth,
            )
            self._send_json(HTTPStatus.OK, payload)
            return

        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"error": "not_found", "detail": f"Unknown GET path: {path}"},
        )

    def _handle_post(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        payload = self._read_json_body()

        # Ingest endpoints:
        #  POST /ingest/context
        #  POST /ingest/state
        #  POST /ingest/states
        #  POST /ingest/transition
        #  POST /ingest/transitions
        #  POST /ingest/bundle

        if path == "/ingest/context":
            result = self.app.ingest.ingest_context(payload, overwrite=True)
            self._send_json(HTTPStatus.OK, result)
            return

        if path == "/ingest/state":
            result = self.app.ingest.ingest_state_record(payload)
            self._send_json(HTTPStatus.OK, result)
            return

        if path == "/ingest/states":
            if not isinstance(payload, list):
                raise ValueError("Payload for /ingest/states must be a JSON array")
            result = self.app.ingest.ingest_state_records(payload)
            self._send_json(HTTPStatus.OK, result)
            return

        if path == "/ingest/transition":
            result = self.app.ingest.ingest_transition_record(payload)
            self._send_json(HTTPStatus.OK, result)
            return

        if path == "/ingest/transitions":
            if not isinstance(payload, list):
                raise ValueError("Payload for /ingest/transitions must be a JSON array")
            result = self.app.ingest.ingest_transition_records(payload)
            self._send_json(HTTPStatus.OK, result)
            return

        if path == "/ingest/bundle":
            result = self.app.ingest.ingest_bundle(payload)
            self._send_json(HTTPStatus.OK, result)
            return

        # Not found
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"error": "not_found", "detail": f"Unknown POST path: {path}"},
        )

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_single_query_param(params: Dict[str, Any], name: str) -> Optional[str]:
        values = params.get(name)
        if not values:
            return None
        if isinstance(values, list):
            return values[0]
        return str(values)


# --------------------------------------------------------------------------- #
# Convenience entrypoint
# --------------------------------------------------------------------------- #


def run_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    graph_config: Optional[GraphStoreConfig] = None,
    auth_config: Optional[AuthConfig] = None,
) -> None:
    """
    Run a simple Atlas HTTP server.

    Example:

        from atlas.api.http_server import run_server

        if __name__ == "__main__":
            run_server(host="0.0.0.0", port=8080)
    """
    logging.basicConfig(level=logging.INFO)

    app = AtlasApp(graph_config=graph_config, auth_config=auth_config)

    server = HTTPServer((host, port), AtlasRequestHandler)
    # Attach the app so handlers can access it
    server.app = app  # type: ignore[attr-defined]

    LOG.info("Atlas HTTP server listening on http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Shutting down server...")
    finally:
        server.server_close()
