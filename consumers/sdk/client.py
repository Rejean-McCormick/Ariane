"""
Lightweight Python client SDK for Ariane Atlas.

This module provides a small, dependency-free wrapper around the Atlas
HTTP API exposed by `atlas.api.http_server`.

It uses only the Python standard library (urllib + json) and the
dataclasses in `consumers.sdk.types`.

Typical usage:

    from consumers.sdk.client import AtlasClient, AtlasClientConfig

    client = AtlasClient(
        AtlasClientConfig(
            base_url="http://localhost:8080",
            api_key="YOUR_API_KEY",  # or None if auth disabled
        )
    )

    # List contexts
    contexts = client.list_contexts()

    # Get states for a context
    states = client.list_states(contexts[0].context_id)

    # Compute shortest path
    path = client.shortest_path(
        context_id=contexts[0].context_id,
        source_state_id=states[0].state_id,
        target_state_id=states[5].state_id,
    )
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .types import (
    APIErrorDetail,
    ContextInfo,
    PathView,
    StateView,
    TransitionView,
)


JSONDict = Dict[str, Any]


# --------------------------------------------------------------------------- #
# Config and errors
# --------------------------------------------------------------------------- #


@dataclass
class AtlasClientConfig:
    """
    Configuration for AtlasClient.

    Attributes:
        base_url:
            Base URL of the Atlas HTTP server, e.g. "http://localhost:8080".
            Do not include a trailing slash.
        api_key:
            Optional API key to send in the configured header. If None,
            the client makes unauthenticated requests.
        api_key_header:
            Name of the header that carries the API key. Defaults to
            "X-API-Key" (see atlas.api.auth.AuthConfig).
        timeout:
            Socket timeout (seconds) for HTTP requests.
    """

    base_url: str
    api_key: Optional[str] = None
    api_key_header: str = "X-API-Key"
    timeout: int = 10


class AtlasClientError(Exception):
    """
    Exception raised for HTTP or API-level errors.

    Attributes:
        status:
            HTTP status code, if available (e.g. 400, 404, 500).
        error_detail:
            Optional structured error detail parsed from the API body.
        raw_body:
            Raw response body as text (for debugging).
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        error_detail: Optional[APIErrorDetail] = None,
        raw_body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_detail = error_detail
        self.raw_body = raw_body

    def __str__(self) -> str:
        base = super().__str__()
        if self.status is not None:
            base = f"[{self.status}] {base}"
        if self.error_detail is not None:
            base = f"{base} (error={self.error_detail.code})"
        return base


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


class AtlasClient:
    """
    Minimal HTTP client for Ariane Atlas.

    Methods generally fall into:

      - Health:
            health()

      - Contexts:
            list_contexts()
            get_context()

      - States:
            list_states()
            get_state()

      - Transitions:
            list_transitions()
            get_transition()
            list_outgoing()
            list_incoming()

      - Paths:
            shortest_path()

      - Ingest (write):
            ingest_bundle()
    """

    def __init__(self, config: AtlasClientConfig) -> None:
        self._cfg = config

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #

    def health(self) -> JSONDict:
        """
        Query the /health endpoint.

        Returns:
            Raw JSON dict, typically:
                {
                  "status": "ok",
                  "details": {
                    "contexts": ...,
                    "states": ...,
                    "transitions": ...
                  }
                }

        Raises:
            AtlasClientError on HTTP or API error.
        """
        status, payload, _ = self._request("GET", "/health")
        return payload or {}

    # ------------------------------------------------------------------ #
    # Contexts
    # ------------------------------------------------------------------ #

    def list_contexts(self) -> List[ContextInfo]:
        """
        List all contexts known to Atlas.

        Returns:
            List[ContextInfo].
        """
        _, payload, _ = self._request("GET", "/contexts")
        items = payload.get("contexts") or []
        return [ContextInfo.from_api(ctx) for ctx in items]

    def get_context(self, context_id: str) -> ContextInfo:
        """
        Retrieve a single context by id.

        Raises:
            AtlasClientError if not found or on other error.
        """
        path = f"/contexts/{context_id}"
        _, payload, _ = self._request("GET", path)
        ctx_dict = payload.get("context")
        if not ctx_dict:
            raise AtlasClientError(
                f"Malformed response from {path}: missing 'context'"
            )
        return ContextInfo.from_api(ctx_dict)

    # ------------------------------------------------------------------ #
    # States
    # ------------------------------------------------------------------ #

    def list_states(self, context_id: str) -> List[StateView]:
        """
        List all states for a context.

        Returns:
            List[StateView].
        """
        path = f"/contexts/{context_id}/states"
        _, payload, _ = self._request("GET", path)
        items = payload.get("states") or []
        return [StateView.from_state_record(rec) for rec in items]

    def get_state(self, context_id: str, state_id: str) -> StateView:
        """
        Retrieve a single state within a context.

        Raises:
            AtlasClientError if not found or on other error.
        """
        path = f"/contexts/{context_id}/states/{state_id}"
        _, payload, _ = self._request("GET", path)
        rec = payload.get("state")
        # QueryHandler.get_state wraps record under "state"
        if isinstance(rec, dict) and "state" in rec:
            # User is calling this with output of /contexts/... already?
            record_dict = rec
        else:
            # Normal API shape: {"context_id": ..., "state": { ...record... }}
            record_dict = payload
        return StateView.from_state_record(record_dict)

    # ------------------------------------------------------------------ #
    # Transitions
    # ------------------------------------------------------------------ #

    def list_transitions(self, context_id: str) -> List[TransitionView]:
        """
        List all transitions for a context.

        Returns:
            List[TransitionView].
        """
        path = f"/contexts/{context_id}/transitions"
        _, payload, _ = self._request("GET", path)
        items = payload.get("transitions") or []
        return [TransitionView.from_transition_record(rec) for rec in items]

    def get_transition(
        self, context_id: str, transition_id: str
    ) -> TransitionView:
        """
        Retrieve a single transition by id within a context.

        Raises:
            AtlasClientError if not found or on other error.
        """
        path = f"/contexts/{context_id}/transitions/{transition_id}"
        _, payload, _ = self._request("GET", path)
        rec = payload.get("transition")
        if isinstance(rec, dict) and "transition" in rec:
            record_dict = rec
        else:
            record_dict = payload
        return TransitionView.from_transition_record(record_dict)

    def list_outgoing(
        self, context_id: str, state_id: str
    ) -> List[TransitionView]:
        """
        List outgoing transitions from a given state.

        Returns:
            List[TransitionView].
        """
        path = f"/contexts/{context_id}/states/{state_id}/outgoing"
        _, payload, _ = self._request("GET", path)
        items = payload.get("outgoing") or []
        return [TransitionView.from_transition_record(rec) for rec in items]

    def list_incoming(
        self, context_id: str, state_id: str
    ) -> List[TransitionView]:
        """
        List incoming transitions to a given state.

        Returns:
            List[TransitionView].
        """
        path = f"/contexts/{context_id}/states/{state_id}/incoming"
        _, payload, _ = self._request("GET", path)
        items = payload.get("incoming") or []
        return [TransitionView.from_transition_record(rec) for rec in items]

    # ------------------------------------------------------------------ #
    # Path / navigation
    # ------------------------------------------------------------------ #

    def shortest_path(
        self,
        context_id: str,
        source_state_id: str,
        target_state_id: str,
        *,
        max_depth: Optional[int] = None,
    ) -> PathView:
        """
        Compute the shortest path (in transitions) between two states.

        Returns:
            PathView. If there is no path, PathView.transitions is None.
        """
        path = f"/contexts/{context_id}/path"
        query: Dict[str, Any] = {
            "source": source_state_id,
            "target": target_state_id,
        }
        if max_depth is not None:
            query["max_depth"] = str(max_depth)

        _, payload, _ = self._request("GET", path, query=query)
        return PathView.from_api(payload)

    # ------------------------------------------------------------------ #
    # Ingest (write)
    # ------------------------------------------------------------------ #

    def ingest_bundle(self, bundle: JSONDict) -> JSONDict:
        """
        Ingest a full context + states + transitions bundle.

        This is a thin wrapper over POST /ingest/bundle.

        Args:
            bundle:
                JSON-serializable dict as produced by Theseus' Exporter.
                Expected shape:
                    {
                      "context": { ... },
                      "states": [ ... ],
                      "transitions": [ ... ]
                    }

        Returns:
            Raw JSON response from the server, typically:
                {
                  "status": "ok",
                  "context": { ... },
                  "states": { "count": ... },
                  "transitions": { "count": ... }
                }
        """
        _, payload, _ = self._request("POST", "/ingest/bundle", body=bundle)
        return payload or {}

    # ------------------------------------------------------------------ #
    # Low-level HTTP helpers
    # ------------------------------------------------------------------ #

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[JSONDict | List[Any]] = None,
    ) -> Tuple[int, JSONDict, Dict[str, str]]:
        """
        Perform a low-level HTTP request.

        Args:
            method:
                HTTP method (e.g. "GET", "POST").
            path:
                Path starting with "/" (e.g. "/contexts").
            query:
                Optional query parameters as a dict.
            body:
                Optional JSON-serializable object for request body.

        Returns:
            (status, payload_dict, headers_dict)

        Raises:
            AtlasClientError for HTTP errors or API error payloads.
        """
        if not path.startswith("/"):
            path = "/" + path

        url = self._cfg.base_url.rstrip("/") + path

        if query:
            qs = urlencode(query, doseq=True)
            url = url + "?" + qs

        headers: Dict[str, str] = {
            "Accept": "application/json",
        }

        if self._cfg.api_key is not None:
            headers[self._cfg.api_key_header] = self._cfg.api_key

        data_bytes: Optional[bytes] = None
        if body is not None:
            data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        req = Request(
            url=url,
            data=data_bytes,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urlopen(req, timeout=self._cfg.timeout) as resp:
                status = resp.getcode()
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                raw = resp.read()
        except HTTPError as exc:
            # Even for HTTPError, we may get a body with error details
            status = exc.code
            resp_headers = {k.lower(): v for k, v in exc.headers.items()}
            raw = exc.read()
            self._raise_from_error(status, raw, resp_headers)
            # If _raise_from_error does not raise, treat as generic
            raise AtlasClientError(
                f"HTTP error {status} for {url}",
                status=status,
                raw_body=raw.decode("utf-8", errors="replace") if raw else None,
            )
        except URLError as exc:
            raise AtlasClientError(f"Connection error for {url}: {exc}") from exc

        payload: JSONDict = {}
        if raw:
            text = raw.decode("utf-8", errors="replace")
            if self._is_json_response(resp_headers):
                try:
                    decoded = json.loads(text)
                    if isinstance(decoded, dict):
                        payload = decoded
                    else:
                        payload = {"_": decoded}
                except json.JSONDecodeError:
                    # Non-JSON response where JSON was expected
                    raise AtlasClientError(
                        f"Invalid JSON response from {url}",
                        status=status,
                        raw_body=text,
                    )
            else:
                payload = {"_raw": text}

        if status >= 400:
            self._raise_from_error(status, raw, resp_headers)

        return status, payload, resp_headers

    @staticmethod
    def _is_json_response(headers: Dict[str, str]) -> bool:
        """
        Check whether response content-type looks like JSON.
        """
        ctype = headers.get("content-type", "")
        return "application/json" in ctype or "+json" in ctype

    @staticmethod
    def _parse_error_body(
        status: int,
        raw: bytes,
        headers: Dict[str, str],
    ) -> Tuple[str, Optional[APIErrorDetail], Optional[str]]:
        """
        Parse an error payload (if any) into message + APIErrorDetail.

        Returns:
            (message, error_detail, raw_text)
        """
        if not raw:
            return f"HTTP {status}", None, None

        text = raw.decode("utf-8", errors="replace")

        if "application/json" in headers.get("content-type", ""):
            try:
                decoded = json.loads(text)
                if isinstance(decoded, dict) and "error" in decoded:
                    detail = APIErrorDetail.from_api(decoded)
                    msg = detail.detail or detail.code or f"HTTP {status}"
                    return msg, detail, text
            except json.JSONDecodeError:
                # fall through to generic
                pass

        # Non-JSON or no "error" field
        return f"HTTP {status}", None, text

    def _raise_from_error(
        self,
        status: int,
        raw: bytes,
        headers: Dict[str, str],
    ) -> None:
        """
        Raise AtlasClientError based on an HTTP error response.
        """
        msg, detail, text = self._parse_error_body(status, raw, headers)
        raise AtlasClientError(
            msg,
            status=status,
            error_detail=detail,
            raw_body=text,
        )
