"""Read-only ArcGIS Server REST scanner."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests

from ..diagnostics import Diagnostic
from ..scanners.http import RequestOptions, configure_session, fetch_json
from ..redaction import sanitize_handoff_url

_SERVICE_KINDS = {
    "FeatureServer",
    "MapServer",
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
    service_counts: dict[str, int] = {}
    folders: list[str] = []

    root = fetch_json(
        sess,
        urljoin(base, "services"),
        diagnostics,
        "services",
        options=request_options,
    )
    if not isinstance(root, dict):
        return {
            "inventory": inventory,
            "diagnostics": diagnostics,
            "server": {"serviceCounts": service_counts, "folders": folders},
        }

    for service in root.get("services", []) or []:
        _record_service(
            sess,
            base,
            service,
            "",
            inventory,
            diagnostics,
            service_counts,
            request_options,
        )

    for folder in root.get("folders", []) or []:
        if not isinstance(folder, str):
            continue
        folders.append(folder)
        folder_url = urljoin(base, f"services/{folder}")
        folder_doc = fetch_json(
            sess,
            folder_url,
            diagnostics,
            f"services/{folder}",
            options=request_options,
        )
        if not isinstance(folder_doc, dict):
            continue
        for service in folder_doc.get("services", []) or []:
            _record_service(
                sess,
                base,
                service,
                folder,
                inventory,
                diagnostics,
                service_counts,
                request_options,
            )

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
    request_options: RequestOptions,
) -> None:
    raw_type = service.get("type")
    name = service.get("name")
    if not isinstance(raw_type, str) or not isinstance(name, str):
        return
    service_counts[raw_type] = service_counts.get(raw_type, 0) + 1
    if raw_type not in _SERVICE_KINDS:
        diagnostics.append(
            Diagnostic(
                code="unsupported-item-type",
                message=f"Skipped unsupported service type {raw_type!r}.",
                scope=name,
                severity="info",
            )
        )
        return
    relative = f"services/{name}/{raw_type}" if not folder else f"services/{folder}/{name.split('/')[-1]}/{raw_type}"
    probe_url = urljoin(base, relative)
    probe = fetch_json(
        sess,
        probe_url,
        diagnostics,
        relative,
        options=request_options,
    )
    if not isinstance(probe, dict):
        return
    candidate_layers = probe.get("layers")
    layers: list[Any] = candidate_layers if isinstance(candidate_layers, list) else []
    record = {
        "kind": "server-service",
        "serviceUrl": sanitize_handoff_url(probe_url),
        "serviceType": raw_type,
        "folder": folder,
        "layerCount": len(layers),
    }
    inventory.append(record)
