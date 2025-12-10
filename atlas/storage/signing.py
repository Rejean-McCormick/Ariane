"""
Simple signing utilities for Ariane Atlas.

This module provides a minimal, dependency-free mechanism for:

- Creating a deterministic canonical representation of a payload.
- Signing that representation with a shared secret (HMAC).
- Verifying signatures.

It is intended for:

- Detecting accidental corruption.
- Providing a basic integrity check for maps produced by trusted pipelines.

This is **not** a full security framework. For high-security scenarios
(key rotation, multi-tenant secrets, hardware keys, etc.), this module
should be replaced or wrapped by a more robust implementation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional


def _canonical_json_bytes(payload: Any) -> bytes:
    """
    Convert a payload to a canonical JSON byte representation.

    - Sorts keys.
    - Uses compact separators.
    - Disallows NaN/Infinity by default.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


@dataclass
class SignerConfig:
    """
    Configuration for the signer.

    Attributes:
        secret:
            Shared secret used for HMAC. Must be kept private.
        algorithm:
            Name of the hash algorithm to use with HMAC.
            Common options: "sha256", "sha512".
    """

    secret: str
    algorithm: str = "sha256"

    def get_digestmod(self):
        try:
            return getattr(hashlib, self.algorithm)
        except AttributeError as exc:
            raise ValueError(f"Unsupported hash algorithm: {self.algorithm}") from exc


class Signer:
    """
    Simple HMAC-based signer.

    Usage:

        config = SignerConfig(secret="your-secret-token")
        signer = Signer(config)

        signature = signer.sign(payload_dict)
        ok = signer.verify(payload_dict, signature)
    """

    def __init__(self, config: SignerConfig) -> None:
        self._config = config
        self._key_bytes = config.secret.encode("utf-8")
        self._digestmod = config.get_digestmod()

    # ------------------------------------------------------------------ #
    # Core operations
    # ------------------------------------------------------------------ #

    def sign(self, payload: Dict[str, Any]) -> str:
        """
        Compute a signature for the given payload.

        The payload should be JSON-serializable. The function returns a
        URL-safe base64 string (no padding) that can be stored alongside
        the payload.

        Example return value: "Yk0QkF-...".
        """
        canon = _canonical_json_bytes(payload)
        raw = hmac.new(self._key_bytes, canon, self._digestmod).digest()
        # URL-safe base64 without trailing '=' padding to keep it compact.
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def verify(self, payload: Dict[str, Any], signature: str) -> bool:
        """
        Verify that the given signature matches the payload.

        Returns:
            True if the signature is valid for this payload and signer
            configuration, False otherwise.
        """
        if not signature:
            return False

        expected = self.sign(payload)
        # Use hmac.compare_digest for constant-time comparison
        return hmac.compare_digest(expected, signature)

    # ------------------------------------------------------------------ #
    # Convenience helpers for embedding in records
    # ------------------------------------------------------------------ #

    def sign_record(self, record: Dict[str, Any], field: str = "signature") -> Dict[str, Any]:
        """
        Return a new dict with a signature field added.

        The signature is computed over the record **without** the signature
        field, to avoid self-referential hashing.

        Args:
            record: Original record data.
            field: Name of the signature field to inject.

        Returns:
            A shallow copy of the record with `field` set to the signature.
        """
        # Shallow copy; remove signature field if present
        payload = dict(record)
        payload.pop(field, None)

        sig = self.sign(payload)
        record_with_sig = dict(payload)
        record_with_sig[field] = sig
        return record_with_sig

    def verify_record(self, record: Dict[str, Any], field: str = "signature") -> bool:
        """
        Verify a record that embeds its signature under `field`.

        The signature is expected to have been produced by `sign_record`.

        Returns:
            True if the signature is present and valid, False otherwise.
        """
        if field not in record:
            return False

        signature = record[field]
        payload = dict(record)
        payload.pop(field, None)

        return self.verify(payload, signature)


# ---------------------------------------------------------------------- #
# Optional default signer
# ---------------------------------------------------------------------- #

_default_signer: Optional[Signer] = None


def configure_default_signer(secret: str, algorithm: str = "sha256") -> None:
    """
    Configure a process-wide default signer.

    After calling this, you can use sign_with_default / verify_with_default.
    """
    global _default_signer
    _default_signer = Signer(SignerConfig(secret=secret, algorithm=algorithm))


def sign_with_default(payload: Dict[str, Any]) -> str:
    """
    Convenience wrapper around the default signer.

    Raises RuntimeError if no default signer has been configured.
    """
    if _default_signer is None:
        raise RuntimeError("Default signer is not configured")
    return _default_signer.sign(payload)


def verify_with_default(payload: Dict[str, Any], signature: str) -> bool:
    """
    Convenience wrapper around the default signer.

    Returns False if no default signer has been configured.
    """
    if _default_signer is None:
        return False
    return _default_signer.verify(payload, signature)
