"""Repo-level invariant: no outbound URLs to Honua-owned hosts in source.

Mirrors the design brief's commitment to keep the scanner phone-home-free.
The test intentionally allows local logging and documentation references.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "honua_esri_assess"

_FORBIDDEN_HOSTS = re.compile(
    r"https?://[a-z0-9.\-]*(honua\.io|honua-sdk|telemetry|analytics)",
    re.IGNORECASE,
)


def test_source_has_no_phone_home_urls() -> None:
    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in _FORBIDDEN_HOSTS.finditer(text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path}:{line}: {match.group(0)}")
    assert not offenders, "phone-home host found in source:\n" + "\n".join(offenders)


def test_client_module_does_not_hardcode_any_real_host() -> None:
    """The HTTP client must never pin to a real host other than the user's target.

    Real hosts contain at least one ``.`` in the netloc; docstring placeholders
    like ``https://host`` are ignored.
    """

    text = (SRC_ROOT / "server" / "client.py").read_text(encoding="utf-8")
    pattern = re.compile(r"https?://[A-Za-z0-9.\-]+(?:/[^\s'\")]*)?")
    hardcoded = [
        match.group(0)
        for match in pattern.finditer(text)
        if "." in match.group(0).split("://", 1)[1].split("/", 1)[0]
    ]
    # Repo-link in the default User-Agent is intentional; everything else is forbidden.
    allowed = {"https://github.com/honua-io/honua-esri-assess"}
    leftovers = [url for url in hardcoded if url not in allowed]
    assert not leftovers, f"unexpected hardcoded URLs in client.py: {leftovers}"


def test_access_collectors_emit_only_get_requests() -> None:
    """Access collectors must only call get_json on the HttpClient protocol.

    The HTTP client protocol exposes only get_json (no post/put/delete), but the
    invariant is worth re-stating against the new modules to catch a regression
    if someone introduces a different transport.
    """

    for module_name in ("portal.py", "server.py"):
        text = (SRC_ROOT / "access" / module_name).read_text(encoding="utf-8")
        forbidden_verbs = (
            "self._client.post",
            "self._client.put",
            "self._client.delete",
            "self._client.patch",
            "requests.post",
            "requests.put",
            "requests.delete",
            "requests.patch",
        )
        for verb in forbidden_verbs:
            assert verb not in text, (
                f"access/{module_name} uses {verb}; collectors must stay read-only."
            )


def test_access_models_do_not_declare_secret_fields() -> None:
    """Backstop the runtime guard in access.models with a static check."""

    text = (SRC_ROOT / "access" / "models.py").read_text(encoding="utf-8")
    for forbidden_field in ("email:", "password_hash:", "client_secret:", "mfa_seed:"):
        assert forbidden_field not in text, (
            f"access/models.py declares forbidden field {forbidden_field!r}; "
            "secrets are not part of the v0.2 access contract."
        )
