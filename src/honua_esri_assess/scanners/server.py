"""Read-only ArcGIS Server REST scanner."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests

from ..diagnostics import Diagnostic

_SERVICE_KINDS = {
    "FeatureServer": "feature-service",
    "MapServer": "map-service",
}


def scan(target: str, *, session: requests.Session | None = None) -> dict[str, Any]:
    sess = session or requests.Session()
    base = _ensure_trailing_slash(target)
    diagnostics: list[Diagnostic] = []
    inventory: list[dict[str, Any]] = []
    service_counts: dict[str, int] = {}
    folders: list[str] = []

    root = _fetch_json(sess, urljoin(base, "services"), diagnostics, "services")
    if not isinstance(root, dict):
        return {
            "inventory": inventory,
            "diagnostics": diagnostics,
            "server": {"serviceCounts": service_counts, "folders": folders},
        }

    for service in root.get("services", []) or []:
        _record_service(sess, base, service, "", inventory, diagnostics, service_counts)

    for folder in root.get("folders", []) or []:
        if not isinstance(folder, str):
            continue
        folders.append(folder)
        folder_url = urljoin(base, f"services/{folder}")
        folder_doc = _fetch_json(sess, folder_url, diagnostics, f"services/{folder}")
        if not isinstance(folder_doc, dict):
            continue
        for service in folder_doc.get("services", []) or []:
            _record_service(sess, base, service, folder, inventory, diagnostics, service_counts)

    return {
        "inventory": inventory,
        "diagnostics": diagnostics,
        "server": {"serviceCounts": service_counts, "folders": folders},
    }


def _ensure_trailing_slash(target: str) -> str:
    return target if target.endswith("/") else target + "/"


def _record_service(
    sess: requests.Session,
    base: str,
    service: dict[str, Any],
    folder: str,
    inventory: list[dict[str, Any]],
    diagnostics: list[Diagnostic],
    service_counts: dict[str, int],
) -> None:
    raw_type = service.get("type")
    name = service.get("name")
    if not isinstance(raw_type, str) or not isinstance(name, str):
        return
    service_counts[raw_type] = service_counts.get(raw_type, 0) + 1
    kind = _SERVICE_KINDS.get(raw_type)
    if kind is None:
        diagnostics.append(
            Diagnostic(
                code="unsupported-item-type",
                message=f"Skipped unsupported service type {raw_type!r}.",
                target=name,
            )
        )
        return
    relative = f"services/{name}/{raw_type}" if not folder else f"services/{folder}/{name.split('/')[-1]}/{raw_type}"
    probe_url = urljoin(base, relative)
    probe = _fetch_json(sess, probe_url, diagnostics, relative)
    layers: list[Any] = []
    if isinstance(probe, dict):
        candidate_layers = probe.get("layers")
        if isinstance(candidate_layers, list):
            layers = candidate_layers
    record = {
        "kind": kind,
        "id": name.split("/")[-1],
        "title": probe.get("serviceDescription") if isinstance(probe, dict) and isinstance(probe.get("serviceDescription"), str) else name.split("/")[-1],
        "url": probe_url,
        "layerCount": len(layers),
    }
    inventory.append(record)


def _fetch_json(
    sess: requests.Session,
    url: str,
    diagnostics: list[Diagnostic],
    target_label: str,
) -> Any:
    try:
        response = sess.get(url, params={"f": "json"}, timeout=10)
    except requests.RequestException:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Could not reach {target_label}; inventory may be incomplete.",
                target=target_label,
            )
        )
        return None
    status = response.status_code
    if status == 403:
        diagnostics.append(
            Diagnostic(
                code="missing-permission",
                message=f"Access denied while reading {target_label}.",
                target=target_label,
            )
        )
        return None
    if status == 429:
        diagnostics.append(
            Diagnostic(
                code="rate-limited",
                message=f"Rate limited while reading {target_label}; partial inventory returned.",
                target=target_label,
            )
        )
        return None
    if status >= 400:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Upstream returned HTTP {status} for {target_label}.",
                target=target_label,
            )
        )
        return None
    try:
        return response.json()
    except ValueError:
        diagnostics.append(
            Diagnostic(
                code="partial-coverage",
                message=f"Non-JSON response from {target_label}.",
                target=target_label,
            )
        )
        return None
