"""
Minimal auth helpers for Ariane Atlas.

This module is **framework-agnostic** and only deals with:

- Representing API key configuration.
- Extracting credentials from request-like headers.
- Validating those credentials against an in-memory registry.

An HTTP layer (see http_server.py) is expected to:

    - Provide a headers dict (e.g. from a request object).
    - Call `authenticate(headers)` or `require_auth(headers)`.
    - Map AuthError to appropriate HTTP responses (e.g. 401 / 403).

This is intentionally simple and suitable for:

- Local development.
- Single-tenant deployments.
- Environments where API keys are provided via configuration.

It is **not** a full security framework (no key rotation, RBAC, JWT, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional


class AuthError(Exception):
    """
    Raised when authentication fails or is missing.

    HTTP servers should typically map this to:

      - 401 Unauthorized (for missing/invalid credentials)
      - 403 Forbidden (for authenticated but unauthorized principals,
        if you choose to implement authorization on top)
    """


@dataclass
class Principal:
    """
    Represents an authenticated principal (client / user / service).

    Attributes:
        id:
            Logical identifier (e.g. "scanner-1", "read-only-client").
        scopes:
            Optional set of scopes or roles (purely advisory at this level).
        metadata:
            Free-form metadata associated with this principal.
    """

    id: str
    scopes: set[str] = field(default_factory=set)
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class AuthConfig:
    """
    Configuration for API-key based auth.

    Attributes:
        api_keys:
            Mapping of API key string -> Principal. The keys are the secrets
            that callers must present; the values describe who they are.
        header_name:
            HTTP header name to inspect for the API key.
            Defaults to "X-API-Key".
        optional:
            If True, `authenticate` will return None instead of raising for
            missing credentials. This is useful for setups where some endpoints
            are public and others call `require_auth` explicitly.
    """

    api_keys: Dict[str, Principal] = field(default_factory=dict)
    header_name: str = "X-API-Key"
    optional: bool = False


class Authenticator:
    """
    Simple API-key authenticator.

    Usage:

        config = AuthConfig(
            api_keys={
                "secret-key-1": Principal(id="scanner-1", scopes={"ingest"}),
                "secret-key-2": Principal(id="reader", scopes={"read"}),
            }
        )
        auth = Authenticator(config)

        principal = auth.require_auth(request.headers)
    """

    def __init__(self, config: AuthConfig) -> None:
        self._config = config

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def authenticate(self, headers: Mapping[str, str]) -> Optional[Principal]:
        """
        Authenticate a request based on headers.

        Args:
            headers:
                Case-insensitive mapping of HTTP header names to values.
                When using a framework-specific request object, convert
                its headers to a plain dict first.

        Returns:
            Principal if authentication succeeds.
            None if no credentials are present and auth is optional.

        Raises:
            AuthError if credentials are present but invalid, or if
            auth is required and missing.
        """
        key = self._extract_api_key(headers)

        if key is None:
            if self._config.optional:
                return None
            raise AuthError("Missing API key")

        principal = self._config.api_keys.get(key)
        if principal is None:
            raise AuthError("Invalid API key")

        return principal

    def require_auth(self, headers: Mapping[str, str]) -> Principal:
        """
        Authenticate and require a valid principal.

        This is a strict variant of `authenticate` that always raises
        on failure (including missing credentials).

        Returns:
            Principal if authentication succeeds.

        Raises:
            AuthError otherwise.
        """
        principal = self.authenticate(headers)
        if principal is None:
            raise AuthError("Authentication required")
        return principal

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _extract_api_key(self, headers: Mapping[str, str]) -> Optional[str]:
        """
        Look up the API key in headers, using the configured header name.

        Header matching is case-insensitive.
        """
        target = self._config.header_name.lower()
        for name, value in headers.items():
            if name.lower() == target:
                stripped = value.strip()
                if stripped:
                    return stripped
        return None


# ---------------------------------------------------------------------- #
# Optional module-level default authenticator
# ---------------------------------------------------------------------- #

_default_authenticator: Optional[Authenticator] = None


def configure_default_auth(api_keys: Dict[str, Principal], header_name: str = "X-API-Key", optional: bool = False) -> None:
    """
    Configure a process-wide default Authenticator.

    After calling this, you can use `authenticate_with_default` or
    `require_auth_with_default` without passing an Authenticator instance.
    """
    global _default_authenticator
    config = AuthConfig(api_keys=api_keys, header_name=header_name, optional=optional)
    _default_authenticator = Authenticator(config)


def authenticate_with_default(headers: Mapping[str, str]) -> Optional[Principal]:
    """
    Authenticate using the default authenticator, if configured.

    Returns:
        Principal on success, None on optional/missing auth.

    Raises:
        AuthError if no default authenticator is configured, or if
        credentials are invalid while auth is required.
    """
    if _default_authenticator is None:
        raise AuthError("Default authenticator is not configured")
    return _default_authenticator.authenticate(headers)


def require_auth_with_default(headers: Mapping[str, str]) -> Principal:
    """
    Strict variant of `authenticate_with_default`.

    Always requires a valid principal.

    Raises:
        AuthError if authentication fails in any way.
    """
    if _default_authenticator is None:
        raise AuthError("Default authenticator is not configured")
    return _default_authenticator.require_auth(headers)
