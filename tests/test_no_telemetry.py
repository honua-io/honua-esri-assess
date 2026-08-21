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

# Documented, non-network exceptions (issue #84): the ``caps`` command builds
# a *shareable catalog URL* pointing at honua.io as plain output data -- it is
# printed/written to the artifact, never fetched. No HTTP client in this
# codebase is ever pointed at this constant; see
# ``honua_esri_assess.caps.renderer.CATALOG_BASE_URL`` and
# ``tests/caps/test_cli.py::test_caps_never_fetches_network_by_default``,
# which asserts the default ``caps`` run makes zero network calls.
_ALLOWED_PHONE_HOME_REFERENCES: frozenset[tuple[str, str]] = frozenset(
    {("caps/renderer.py", "https://honua.io")}
)


def test_source_has_no_phone_home_urls() -> None:
    offenders: list[str] = []
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(SRC_ROOT).as_posix()
        for match in _FORBIDDEN_HOSTS.finditer(text):
            if (relative, match.group(0)) in _ALLOWED_PHONE_HOME_REFERENCES:
                continue
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
    allowed = {"https://github.com/honua-io/honua-migrate"}
    leftovers = [url for url in hardcoded if url not in allowed]
    assert not leftovers, f"unexpected hardcoded URLs in client.py: {leftovers}"
