"""Credential carriers for read-only Portal requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Credential(Protocol):
    @property
    def auth_mode(self) -> str:
        """Describe the authentication mode without exposing credential material."""

    def params(self) -> dict[str, str]:
        """Return query-string auth parameters."""

    def redact(self, value: str) -> str:
        """Remove credential material from a string."""


@dataclass(frozen=True)
class AnonymousCredential:
    auth_mode: str = "anonymous"

    def params(self) -> dict[str, str]:
        return {}

    def redact(self, value: str) -> str:
        return value


@dataclass(frozen=True)
class TokenCredential:
    token: str
    auth_mode: str = "token"

    def params(self) -> dict[str, str]:
        return {"token": self.token}

    def redact(self, value: str) -> str:
        if not self.token:
            return value
        return value.replace(self.token, "[REDACTED]")

    def __repr__(self) -> str:
        return "TokenCredential(token='[REDACTED]')"
