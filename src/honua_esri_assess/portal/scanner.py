"""ArcGIS Online Portal scanner built on the read-only Sharing REST API."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from honua_esri_assess.diagnostics import (
    Diagnostic,
    PortalApiError,
    PortalError,
    PortalForbiddenError,
    PortalRateLimitedError,
)
from honua_esri_assess.portal.classification import classify_item
from honua_esri_assess.portal.client import PortalClient
from honua_esri_assess.portal.models import (
    FederatedServer,
    FederationInfo,
    GroupRecord,
    ItemRecord,
    LayerRecord,
    OrgInfo,
    PortalScanResult,
    ServiceRecord,
)
from honua_esri_assess.server._safe import credential_free_url
from honua_esri_assess.portal.pagination import iter_paginated

SERVICE_TYPE_SUFFIXES = {
    "FeatureServer": "featureService",
    "MapServer": "mapService",
    "ImageServer": "imageService",
    "VectorTileServer": "vectorTileService",
    "SceneServer": "sceneService",
}

#: Advanced server products/roles worth recording for migration planning,
#: keyed by the lower-cased ``serverFunction`` token the documented
#: ``portals/self/servers`` federation surface advertises. Values are the
#: stable role tags emitted into the footprint. Only presence is recorded —
#: deep per-server configuration is out of scope (covered by #43/#44).
ADVANCED_SERVER_FUNCTIONS = {
    "geoevent": "geoevent",
    "geoanalytics": "geoanalytics",
    "notebookserver": "notebook",
    "notebook": "notebook",
    "knowledgeserver": "knowledge",
    "knowledge": "knowledge",
}

ITEM_TYPE_BUCKETS = {
    "feature service": "featureService",
    "map service": "mapService",
    "image service": "imageService",
    "vector tile service": "vectorTileService",
    "scene service": "sceneService",
    "web map": "webMap",
    "web mapping application": "webApp",
    "dashboard": "dashboard",
    "arcgis dashboard": "dashboard",
    "experience builder": "experience",
    "notebook": "notebook",
    "solution": "solution",
}


class PortalScanner:
    """Enumerate an AGOL org through GET-only Portal Sharing API calls."""

    def __init__(self, client: PortalClient, *, deep: bool = False) -> None:
        self.client = client
        self.deep = deep
        self.diagnostics: list[Diagnostic] = []

    def scan(self) -> PortalScanResult:
        captured_at = datetime.now(timezone.utc)
        self.diagnostics = []
        org = self._scan_org()
        if not org.id:
            raise PortalApiError("ArcGIS Portal did not expose an organization id.")
        groups = self._scan_groups(org.id) if org.id else []
        org = replace(org, group_count=len(groups))
        user_count = self._scan_user_count(org.id)
        org = replace(org, user_count=user_count)
        items = self._scan_items(org.id) if org.id else []
        federation = self._scan_federation()
        services = self._scan_services(items) if self.deep else []
        if services:
            layer_counts = {service.item_id: len(service.layers) for service in services}
            items = [
                replace(item, layer_count=layer_counts.get(item.id, item.layer_count))
                for item in items
            ]

        return PortalScanResult(
            org=org,
            auth_mode=self.client.auth_mode,
            captured_at=captured_at,
            items=items,
            groups=groups,
            services=services,
            federation=federation,
            diagnostics=list(self.diagnostics),
        )

    def _scan_org(self) -> OrgInfo:
        payload = self.client.get_json("portals/self")
        org_id = _optional_str(payload.get("id"))
        return OrgInfo(
            id=org_id,
            name=_optional_str(payload.get("name")),
            portal_url=self.client.portal_url,
            sharing_rest_url=self.client.sharing_rest_url,
            is_portal=_optional_bool(payload.get("isPortal")),
            url_key=_optional_str(payload.get("urlKey")),
            custom_base_url=_optional_str(payload.get("customBaseUrl")),
            licensed_extensions=_extract_extensions(payload),
        )

    def _scan_federation(self) -> FederationInfo | None:
        """Read the documented Portal federation surface (read-only GET).

        ``portals/self/servers`` lists the server sites federated with the
        Portal, each carrying an assigned role (hosting/federated) and any
        advanced server functions (GeoEvent, GeoAnalytics, Notebook,
        Knowledge, ...). Returns ``None`` when the surface is not reachable
        (unfederated AGOL orgs, anonymous scans, or permission/transport
        failures) so the additive footprint block is omitted and plain scans
        stay unchanged. Failures degrade to a typed diagnostic, never an abort.
        """

        try:
            payload = self.client.get_json("portals/self/servers")
        except PortalForbiddenError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.federation.forbidden",
                    severity="warning",
                    message="The token cannot read the Portal federation surface; federation topology was skipped.",
                    context=exc.context,
                )
            )
            return None
        except PortalRateLimitedError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.federation.rate-limited",
                    severity="info",
                    message="ArcGIS Portal rate limited the federation surface; federation topology was skipped.",
                    context=exc.context,
                )
            )
            return None
        except PortalError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.federation.failed",
                    severity="warn",
                    message="Federation surface enumeration failed; federation topology was skipped.",
                    context=exc.context,
                )
            )
            return None

        raw_servers = payload.get("servers")
        if not isinstance(raw_servers, list):
            return None
        servers = [
            federated
            for entry in raw_servers
            if isinstance(entry, dict)
            and (federated := _federated_server_from_payload(entry)) is not None
        ]
        if not servers:
            return None
        return FederationInfo(servers=tuple(servers))

    def _scan_user_count(self, org_id: str | None) -> int | None:
        if not org_id:
            return None
        if self.client.auth_mode == "anonymous":
            self.diagnostics.append(
                Diagnostic(
                    code="portal.users.skipped",
                    severity="info",
                    message="Anonymous scans do not enumerate organization users.",
                )
            )
            return None
        try:
            payload = self.client.get_json("community/users", {"q": f"orgid:{org_id}", "num": 1})
        except PortalForbiddenError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.users.forbidden",
                    severity="warning",
                    message="The token cannot list organization users; user count was skipped.",
                    context=exc.context,
                )
            )
            return None
        except PortalRateLimitedError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.users.rate-limited",
                    severity="info",
                    message="ArcGIS Portal rate limited organization user enumeration; user count was skipped.",
                    context=exc.context,
                )
            )
            return None
        except PortalError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.users.failed",
                    severity="warn",
                    message="Organization user enumeration failed; user count was skipped.",
                    context=exc.context,
                )
            )
            return None
        return _optional_int(payload.get("total"))

    def _scan_groups(self, org_id: str | None) -> list[GroupRecord]:
        if not org_id:
            return []
        try:
            return [
                GroupRecord(
                    id=str(group.get("id") or ""),
                    title=_optional_str(group.get("title")),
                    owner=_optional_str(group.get("owner")),
                    access=_optional_str(group.get("access")),
                )
                for group in iter_paginated(
                    self.client,
                    "community/groups",
                    params={"q": f"orgid:{org_id}"},
                )
                if group.get("id")
            ]
        except PortalForbiddenError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.groups.forbidden",
                    severity="warning",
                    message="The scan cannot list organization groups; group enumeration was skipped.",
                    context=exc.context,
                )
            )
            return []
        except PortalRateLimitedError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.groups.rate-limited",
                    severity="info",
                    message="ArcGIS Portal rate limited group enumeration; group records were skipped.",
                    context=exc.context,
                )
            )
            return []
        except PortalError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.groups.failed",
                    severity="warn",
                    message="Group enumeration failed; group records were skipped.",
                    context=exc.context,
                )
            )
            return []

    def _scan_items(self, org_id: str | None) -> list[ItemRecord]:
        if not org_id:
            return []
        items: list[ItemRecord] = []
        try:
            for item in iter_paginated(
                self.client,
                "search",
                params={"q": f"orgid:{org_id}"},
            ):
                items.append(_item_from_payload(item))
        except PortalForbiddenError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.items.forbidden",
                    severity="warn",
                    message="The scan cannot list additional organization items; partial inventory returned.",
                    context=exc.context,
                )
            )
        except PortalRateLimitedError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.items.rate-limited",
                    severity="info",
                    message="ArcGIS Portal rate limited item search; partial inventory returned.",
                    context=exc.context,
                )
            )
        except PortalError as exc:
            self.diagnostics.append(
                Diagnostic(
                    code="portal.items.failed",
                    severity="warn",
                    message="Item search failed; partial inventory returned.",
                    context=exc.context,
                )
            )
        return items

    def _scan_services(self, items: list[ItemRecord]) -> list[ServiceRecord]:
        services: list[ServiceRecord] = []
        for item in items:
            if not item.url or not _is_service_url(item.url):
                continue
            try:
                allowed = _is_allowed_service_host(item.url, self.client.portal_url)
            except ValueError:
                allowed = False
            if not allowed:
                self.diagnostics.append(
                    Diagnostic(
                        code="portal.item-probe.failed",
                        severity="warning",
                        message=(
                            f"Layer metadata for item {item.id} was skipped because "
                            "its URL is outside ArcGIS Online hosted domains or malformed."
                        ),
                        context={"itemId": item.id},
                    )
                )
                continue
            try:
                payload = self.client.get_json(item.url)
            except PortalRateLimitedError as exc:
                self.diagnostics.append(
                    Diagnostic(
                        code="portal.item-probe.rate-limited",
                        severity="info",
                        message=f"Layer metadata for item {item.id} was rate limited.",
                        context={"itemId": item.id, **exc.context},
                    )
                )
                continue
            except PortalForbiddenError as exc:
                self.diagnostics.append(
                    Diagnostic(
                        code="portal.item-probe.forbidden",
                        severity="warn",
                        message=f"Layer metadata for item {item.id} could not be read due to permissions.",
                        context={"itemId": item.id, **exc.context},
                    )
                )
                continue
            except PortalError:
                self.diagnostics.append(
                    Diagnostic(
                        code="portal.item-probe.failed",
                        severity="warning",
                        message=f"Layer metadata for item {item.id} could not be read.",
                        context={"itemId": item.id, "url": item.url},
                    )
                )
                continue
            except ValueError:
                # Defensive: malformed service URLs (e.g. non-numeric port)
                # should record a typed diagnostic instead of aborting the
                # opt-in deep probe.
                self.diagnostics.append(
                    Diagnostic(
                        code="portal.item-probe.failed",
                        severity="warning",
                        message=f"Layer metadata for item {item.id} could not be read; the service URL is malformed.",
                        context={"itemId": item.id},
                    )
                )
                continue
            services.append(_service_from_payload(item, payload))
        return services


def _item_from_payload(payload: dict[str, Any]) -> ItemRecord:
    item_type = _optional_str(payload.get("type"))
    type_keywords = _str_list(payload.get("typeKeywords"))
    return ItemRecord(
        id=str(payload.get("id") or ""),
        title=_optional_str(payload.get("title")),
        owner=_optional_str(payload.get("owner")),
        item_type=item_type,
        type_bucket=_bucket_item_type(item_type),
        content_category=classify_item(item_type, type_keywords),
        access=_optional_str(payload.get("access")),
        url=_optional_str(payload.get("url")),
        created=_epoch_millis_to_iso(payload.get("created")),
        modified=_epoch_millis_to_iso(payload.get("modified")),
        tags=_str_list(payload.get("tags")),
        type_keywords=type_keywords,
        layer_count=_optional_int(payload.get("layerCount")),
        extent=payload.get("extent") if isinstance(payload.get("extent"), list) else None,
        dependencies=_str_list(payload.get("dependencies")),
    )


def _service_from_payload(item: ItemRecord, payload: dict[str, Any]) -> ServiceRecord:
    return ServiceRecord(
        item_id=item.id,
        url=item.url or "",
        service_type=_optional_str(payload.get("serviceDescription"))
        or _service_type_from_url(item.url or ""),
        capabilities=_optional_str(payload.get("capabilities")),
        layers=[_layer_from_payload(layer) for layer in _list_of_dicts(payload.get("layers"))],
        tables=[_layer_from_payload(table) for table in _list_of_dicts(payload.get("tables"))],
    )


def _layer_from_payload(payload: dict[str, Any]) -> LayerRecord:
    return LayerRecord(
        id=payload.get("id"),
        name=_optional_str(payload.get("name")),
        layer_type=_optional_str(payload.get("type")),
        geometry_type=_optional_str(payload.get("geometryType")),
        max_record_count=_optional_int(payload.get("maxRecordCount")),
    )


def _federated_server_from_payload(payload: dict[str, Any]) -> FederatedServer | None:
    raw_url = _optional_str(payload.get("url")) or _optional_str(payload.get("adminUrl"))
    if not raw_url:
        return None
    safe_url = credential_free_url(raw_url)
    if not safe_url:
        return None
    server_function = _optional_str(payload.get("serverFunction"))
    functions = _parse_server_functions(server_function)
    advanced = tuple(
        sorted({ADVANCED_SERVER_FUNCTIONS[token.lower()] for token in functions if token.lower() in ADVANCED_SERVER_FUNCTIONS})
    )
    return FederatedServer(
        url=safe_url,
        server_role=_optional_str(payload.get("serverRole")),
        server_function=server_function,
        is_hosted=_optional_bool(payload.get("isHosted")),
        functions=functions,
        advanced_roles=advanced,
    )


def _parse_server_functions(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(token.strip() for token in value.split(",") if token.strip())


def _extract_extensions(payload: dict[str, Any]) -> list[str]:
    extensions: list[str] = []
    helper_services = payload.get("helperServices")
    if isinstance(helper_services, dict):
        extensions.extend(sorted(str(key) for key in helper_services))
    portal_properties = payload.get("portalProperties")
    if isinstance(portal_properties, dict):
        apps = portal_properties.get("apps")
        if isinstance(apps, list):
            extensions.extend(str(app) for app in apps if app)
    return sorted(set(extensions))


def _bucket_item_type(item_type: str | None) -> str:
    if not item_type:
        return "other"
    return ITEM_TYPE_BUCKETS.get(item_type.lower(), "other")


def _is_service_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    path_parts = [part for part in parsed.path.split("/") if part]
    return any(part in SERVICE_TYPE_SUFFIXES for part in path_parts)


def _is_allowed_service_host(url: str, portal_url: str) -> bool:
    service_host = urlparse(url).hostname or ""
    portal_host = urlparse(portal_url).hostname or ""
    return service_host == portal_host or service_host.endswith(".arcgis.com")


def _service_type_from_url(url: str) -> str | None:
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    for part in reversed(path_parts):
        if part in SERVICE_TYPE_SUFFIXES:
            return SERVICE_TYPE_SUFFIXES[part]
    return None


def _epoch_millis_to_iso(value: Any) -> str | None:
    timestamp = _optional_int(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
