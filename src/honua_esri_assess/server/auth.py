"""Credential carriers for the ArcGIS Server scanner.

Two modes are supported: anonymous and pre-existing token. The carrier is
responsible for redacting itself from :func:`repr`; the actual token value
is only ever attached to outbound requests via :meth:`apply` and never
appears in log records or cache keys (see ``_safe.py``).

This module deliberately does not implement ``generateToken``: the design
brief defers username/password bootstrapping out of scope for v0.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Credential(Protocol):
    """Minimal contract every credential carrier honors."""

    @property
    def auth_mode(self) -> str:
        """Describe the authentication mode without exposing credential material."""

    def apply(self, params: dict[str, str]) -> dict[str, str]:
        """Return a copy of *params* augmented with any auth parameters."""


@dataclass(frozen=True)
class AnonymousCredential:
    """Sends no auth material."""

    auth_mode: str = "anonymous"

    def apply(self, params: dict[str, str]) -> dict[str, str]:
        return dict(params)


class TokenCredential:
    """Wraps a pre-existing ArcGIS Server token.

    The token is appended to outbound requests as ``token=…``. The carrier
    overrides :func:`repr` so the token cannot leak through accidental
    logging of the credential object itself.
    """

    auth_mode: str = "token"

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("TokenCredential requires a non-empty token")
        self._token = token

    def apply(self, params: dict[str, str]) -> dict[str, str]:
        merged = dict(params)
        merged["token"] = self._token
        return merged

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "TokenCredential(token=***redacted***)"


__all__ = ["AnonymousCredential", "Credential", "TokenCredential"]
