"""Read-only ArcGIS Online Portal Sharing scanner.

The scanner walks a small, fixed set of public Portal Sharing endpoints:

* ``/sharing/rest/portals/self`` (portal metadata)
* ``/sharing/rest/portals/self/users`` (user list, used for counts only)
* ``/sharing/rest/community/groups`` (group list, used for counts only)
* ``/sharing/rest/search`` (item listing, paginated)
* ``/sharing/rest/content/items/<id>`` (per-item probe)

It is strictly GET-only. Failures on probes are downgraded to typed diagnostics
so partial inventories still produce a valid footprint.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit

import requests

from ..diagnostics import Diagnostic
from ..scanners.http import RequestOptions, configure_session, fetch_json
from ..redaction import sanitize_handoff_url

_SUPPORTED_KINDS = {
    "Feature Service",
    "Map Service",
    "Web Map",
}


def scan(
    target: str,
    *,
    session: requests.Session | None = None,
    token: str | None = None,
    user_agent: str | None = None,
    max_retries: int = 0,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Scan an ArcGIS Online portal target and return inventory + metadata."""

    sess = session or requests.Session()
    request_options = RequestOptions(
        token=token,
        user_agent=user_agent,
        max_retries=max_retries,
        timeout=timeout,
    )
    configure_session(sess, request_options)
    base = _ensure_trailing_slash(target)
    diagnostics: list[Diagnostic] = []
    inventory: list[dict[str, Any]] = []

    portal_self = fetch_json(
        sess,
        urljoin(base, "portals/self"),
        diagnostics,
        "portals/self",
        options=request_options,
    )
    if not isinstance(portal_self, dict):
        portal_self = {}

    # Pull users/groups for telemetry — we only need to know they're reachable.
    fetch_json(
        sess,
        urljoin(base, "portals/self/users"),
        diagnostics,
        "portals/self/users",
        options=request_options,
    )
    fetch_json(
        sess,
        urljoin(base, "community/groups"),
        diagnostics,
        "community/groups",
        options=request_options,
    )

    for item in _iter_search_items(sess, base, diagnostics, request_options):
        kind = item.get("type")
        if kind not in _SUPPORTED_KINDS:
            diagnostics.append(
                Diagnostic(
                    code="unsupported-item-type",
                    message=f"Skipped unsupported item type {kind!r}.",
                    scope=str(item.get("id") or "search"),
                    severity="info",
                )
            )
            continue
        record = _probe_item(sess, base, item, diagnostics, request_options)
        if record is not None:
            inventory.append(record)

    return {
        "inventory": inventory,
        "diagnostics": diagnostics,
        "portal": _portal_facet(target, portal_self, inventory),
    }


def _ensure_trailing_slash(target: str) -> str:
    if not target.endswith("/"):
        return target + "/"
    return target


def _iter_search_items(
    sess: requests.Session,
    base: str,
    diagnostics: list[Diagnostic],
    request_options: RequestOptions,
) -> Iterable[dict[str, Any]]:
    start = 1
    while True:
        url = urljoin(base, "search")
        payload = fetch_json(
            sess,
            url,
            diagnostics,
            f"search?start={start}",
            options=request_options,
            params={"f": "json", "q": "*", "start": start, "num": 100},
        )
        if not isinstance(payload, dict):
            return
        results = payload.get("results") or []
        for item in results:
            if isinstance(item, dict):
                yield item
        next_start = payload.get("nextStart", -1)
        if not isinstance(next_start, int) or next_start <= 0:
            return
        if next_start == start:
            return
        start = next_start


def _probe_item(
    sess: requests.Session,
    base: str,
    item: dict[str, Any],
    diagnostics: list[Diagnostic],
    request_options: RequestOptions,
) -> dict[str, Any] | None:
    item_id = item.get("id")
    if not isinstance(item_id, str):
        return None
    url = urljoin(base, f"content/items/{item_id}")
    payload = fetch_json(
        sess,
        url,
        diagnostics,
        f"content/items/{item_id}",
        options=request_options,
    )
    if not isinstance(payload, dict):
        return None
    return _to_record(item, payload)


def _to_record(search_item: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "kind": "portal-item",
        "id": str(search_item.get("id", probe.get("id", ""))),
        "type": str(search_item.get("type") or probe.get("type") or "Unknown"),
        "owner": str(search_item.get("owner") or probe.get("owner") or "unknown"),
        "title": str(search_item.get("title") or probe.get("title") or ""),
        "sharing": _sharing_level(search_item.get("access") or probe.get("access")),
        "modified": _modified_timestamp(search_item.get("modified") or probe.get("modified")),
    }

    if record["type"] == "Web Map":
        deps = probe.get("dependencies")
        if isinstance(deps, list):
            record["dependencies"] = [str(dep) for dep in deps if isinstance(dep, str)]
    return record


def _portal_facet(target: str, portal_self: dict[str, Any], inventory: list[dict[str, Any]]) -> dict[str, Any]:
    org_id = str(portal_self.get("id") or "unknown")
    item_counts = Counter(str(item.get("type", "Unknown")) for item in inventory)
    sharing = Counter(str(item.get("sharing", "private")) for item in inventory)
    return {
        "orgId": org_id,
        "orgUrl": _origin_url(target),
        "itemCounts": dict(item_counts),
        "sharingSummary": {
            "private": sharing.get("private", 0),
            "org": sharing.get("org", 0),
            "public": sharing.get("public", 0),
            "shared": sharing.get("shared", 0),
        },
    }


def _origin_url(target: str) -> str:
    parsed = urlsplit(sanitize_handoff_url(target))
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "https://unknown.local"


def _sharing_level(value: Any) -> str:
    if value in {"org", "public", "shared", "private"}:
        return str(value)
    return "private"


def _modified_timestamp(value: Any) -> str:
    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str) and value.endswith("Z"):
        return value
    return "1970-01-01T00:00:00Z"
