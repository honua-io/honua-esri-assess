"""Catalog-walk orchestrator for the ArcGIS Server scanner.

The scanner is intentionally pure on top of :class:`ServerClient`: it does
no HTTP itself, it composes ``get_*`` calls and aggregates results into a
:class:`ServerScanResult`. Per-service failures emit a diagnostic and
preserve the partial record; only top-level identity failures abort.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from ..diagnostics import (
    AssessmentError,
    ServerApiError,
    ServerAuthError,
    ServerConnectionError,
    ServerForbiddenError,
    ServerNotFoundError,
    ServerRateLimitedError,
)
from ..logging import get_logger
from .catalog import (
    DEEP_PROBE_TYPES,
    UNKNOWN_KIND,
    classify_geometry,
    classify_ogc_capabilities,
    classify_service,
)
from .client import ServerClient
from .layer_detail import parse_layer_detail
from .models import (
    FolderRecord,
    LayerRecord,
    ScanDiagnostic,
    ServerInfo,
    ServerScanResult,
    ServiceRecord,
)

# Service types whose layers expose a per-layer schema/behavior resource worth
# fetching when layer-detail capture is enabled.
LAYER_DETAIL_TYPES: frozenset[str] = frozenset({"MapServer", "FeatureServer"})


class ServerScanner:
    """Walk an ArcGIS Server catalog and return a typed scan result.

    Parameters
    ----------
    deep:
        When ``True``, follow each service URL and capture per-service
        metadata (layers, capabilities). Defaults to a shallow walk.
    folder:
        When set, restrict the walk to a single folder (still reads the
        top-level catalog for identity).
    """

    def __init__(
        self,
        *,
        deep: bool = False,
        folder: str | None = None,
        layer_detail: bool = False,
    ) -> None:
        self.deep = deep
        self.folder_filter = folder
        # Layer-detail capture implies a deep walk (the per-service body is
        # needed to enumerate layer ids before each layer can be probed).
        self.layer_detail = layer_detail and deep
        self._log = get_logger("server.scanner")

    def scan(self, client: ServerClient) -> ServerScanResult:
        diagnostics: list[ScanDiagnostic] = []
        info = self._scan_info(client, diagnostics)
        root_body = client.get_services_root()
        root_folders = _ensure_str_list(root_body.get("folders"))
        root_services = _ensure_service_list(root_body.get("services"))

        folder_records: list[FolderRecord] = []
        service_records: list[ServiceRecord] = []

        for raw_service in root_services:
            record, diags = self._build_service_record(
                client=client,
                folder=None,
                raw_service=raw_service,
            )
            if record is not None:
                service_records.append(record)
            diagnostics.extend(diags)

        for folder_name in root_folders:
            if self.folder_filter and folder_name != self.folder_filter:
                continue
            folder_record, sub_services, sub_diags = self._scan_folder(client, folder_name)
            folder_records.append(folder_record)
            service_records.extend(sub_services)
            diagnostics.extend(sub_diags)

        return ServerScanResult(
            info=info,
            auth_mode=client.credential.auth_mode,
            deep=self.deep,
            folders=tuple(folder_records),
            services=tuple(service_records),
            diagnostics=tuple(diagnostics),
        )

    # ------------------------------------------------------------------

    def _scan_info(
        self,
        client: ServerClient,
        diagnostics: list[ScanDiagnostic],
    ) -> ServerInfo:
        current_version: str | None = None
        full_version: str | None = None
        auth_info: dict[str, Any] = {}
        software_auth: dict[str, Any] = {}
        try:
            info_body = client.get_rest_info()
        except (
            ServerConnectionError,
            ServerForbiddenError,
            ServerNotFoundError,
            ServerRateLimitedError,
            ServerApiError,
        ) as exc:
            diagnostics.append(
                ScanDiagnostic(
                    code="server.info.partial",
                    severity="warning",
                    message=f"could not read /rest/info: {exc.message}",
                    field="info",
                )
            )
        else:
            current_version = _stringify(info_body.get("currentVersion"))
            full_version = _stringify(info_body.get("fullVersion"))
            if isinstance(info_body.get("authInfo"), dict):
                auth_info = dict(info_body["authInfo"])
            for key in ("softwareAuthorization", "softwareAuthInfo", "license"):
                value = info_body.get(key)
                if isinstance(value, dict):
                    software_auth = dict(value)
                    break

        return ServerInfo(
            url=client.rest_root,
            current_version=current_version,
            full_version=full_version,
            auth_info=auth_info,
            software_authorization=software_auth,
        )

    def _scan_folder(
        self,
        client: ServerClient,
        folder_name: str,
    ) -> tuple[FolderRecord, list[ServiceRecord], list[ScanDiagnostic]]:
        diagnostics: list[ScanDiagnostic] = []
        services: list[ServiceRecord] = []
        try:
            body = client.get_folder(folder_name)
        except ServerForbiddenError as exc:
            diagnostics.append(
                ScanDiagnostic(
                    code="server.folder.forbidden",
                    severity="warning",
                    message=f"skipped folder {folder_name!r}: {exc.message}",
                    field=f"folders/{folder_name}",
                )
            )
            return FolderRecord(name=folder_name, service_count=0), services, diagnostics
        except ServerRateLimitedError as exc:
            diagnostics.append(
                ScanDiagnostic(
                    code="server.folder.rate-limited",
                    severity="warning",
                    message=f"folder {folder_name!r} was rate-limited: {exc.message}",
                    field=f"folders/{folder_name}",
                )
            )
            return FolderRecord(name=folder_name, service_count=0), services, diagnostics
        except ServerConnectionError as exc:
            diagnostics.append(
                ScanDiagnostic(
                    code="server.folder.connection",
                    severity="warning",
                    message=f"folder {folder_name!r} could not be reached: {exc.message}",
                    field=f"folders/{folder_name}",
                )
            )
            return FolderRecord(name=folder_name, service_count=0), services, diagnostics
        except (ServerNotFoundError, ServerApiError) as exc:
            diagnostics.append(
                ScanDiagnostic(
                    code="server.folder.error",
                    severity="error",
                    message=f"folder {folder_name!r} returned an error: {exc.message}",
                    field=f"folders/{folder_name}",
                )
            )
            return FolderRecord(name=folder_name, service_count=0), services, diagnostics

        nested = _ensure_str_list(body.get("folders"))
        if nested:
            diagnostics.append(
                ScanDiagnostic(
                    code="server.folder.nested",
                    severity="warning",
                    message=(
                        f"folder {folder_name!r} reported nested folders; ArcGIS Server REST "
                        "does not nest — ignored to prevent recursion."
                    ),
                    field=f"folders/{folder_name}",
                )
            )

        raw_services = _ensure_service_list(body.get("services"))
        for raw_service in raw_services:
            record, diags = self._build_service_record(
                client=client,
                folder=folder_name,
                raw_service=raw_service,
            )
            if record is not None:
                services.append(record)
            diagnostics.extend(diags)
        return (
            FolderRecord(name=folder_name, service_count=len(services)),
            services,
            diagnostics,
        )

    def _build_service_record(
        self,
        *,
        client: ServerClient,
        folder: str | None,
        raw_service: dict[str, Any],
    ) -> tuple[ServiceRecord | None, list[ScanDiagnostic]]:
        raw_name = raw_service.get("name")
        raw_type = raw_service.get("type")
        if not isinstance(raw_name, str) or not isinstance(raw_type, str):
            return None, [
                ScanDiagnostic(
                    code="server.service.malformed",
                    severity="warning",
                    message="catalog entry missing name/type; skipped",
                    field=f"folders/{folder or '_root'}/services",
                )
            ]
        bare_name = raw_name.split("/")[-1]
        kind = classify_service(raw_type)
        url = _build_service_url(client.rest_root, folder, bare_name, raw_type)
        capabilities: tuple[str, ...] = ()
        # OGC interfaces (WMS/WFS/WCS) are advertised on the catalog entry's
        # ``supportedExtensions`` field, so they are captured even on a shallow
        # walk; a deep probe may refine them from the per-service body.
        ogc_capabilities = classify_ogc_capabilities(raw_service.get("supportedExtensions"))
        layers: tuple[LayerRecord, ...] = ()
        tables: tuple[LayerRecord, ...] = ()
        gp_tasks: tuple[str, ...] = ()
        description: str | None = None
        service_data_type: str | None = None
        single_fused_map_cache: bool | None = None
        deep_scanned = False
        diagnostics: list[ScanDiagnostic] = []
        identity_field = _service_identity_field(folder, bare_name, raw_type)

        if kind == UNKNOWN_KIND:
            diagnostics.append(
                ScanDiagnostic(
                    code="server.service.unknown-type",
                    severity="info",
                    message=f"unrecognized service type {raw_type!r} mapped to 'other'",
                    field=identity_field,
                )
            )

        if self.deep and raw_type in DEEP_PROBE_TYPES:
            try:
                body = client.get_service(
                    name=bare_name,
                    service_type=raw_type,
                    folder=folder,
                )
            except (
                ServerAuthError,
                ServerForbiddenError,
                ServerNotFoundError,
                ServerRateLimitedError,
                ServerConnectionError,
                ServerApiError,
            ) as exc:
                diagnostics.append(
                    ScanDiagnostic(
                        code=_deep_failure_code(exc),
                        severity="warning",
                        message=f"deep scan of {bare_name!r} failed: {exc.message}",
                        field=identity_field,
                    )
                )
            else:
                description = _stringify(body.get("description")) or None
                capabilities = _split_capabilities(body.get("capabilities"))
                body_ogc = classify_ogc_capabilities(body.get("supportedExtensions"))
                if body_ogc:
                    ogc_capabilities = tuple(sorted(set(ogc_capabilities) | set(body_ogc)))
                layers = tuple(_parse_layers(body.get("layers")))
                tables = tuple(_parse_layers(body.get("tables")))
                # A GPServer body advertises its geoprocessing tasks in a flat
                # ``tasks`` array (task-name strings). They are recorded only to
                # seed the cross-repo migration handoff; no task is crawled.
                if raw_type == "GPServer":
                    gp_tasks = _parse_gp_tasks(body.get("tasks"))
                service_data_type = _stringify(body.get("serviceDataType"))
                if "singleFusedMapCache" in body:
                    single_fused_map_cache = bool(body.get("singleFusedMapCache"))
                deep_scanned = True

                if self.layer_detail and raw_type in LAYER_DETAIL_TYPES:
                    layers = self._attach_layer_detail(
                        client=client,
                        folder=folder,
                        bare_name=bare_name,
                        service_type=raw_type,
                        layers=layers,
                        identity_field=identity_field,
                        diagnostics=diagnostics,
                    )
                    tables = self._attach_layer_detail(
                        client=client,
                        folder=folder,
                        bare_name=bare_name,
                        service_type=raw_type,
                        layers=tables,
                        identity_field=identity_field,
                        diagnostics=diagnostics,
                    )

        return (
            ServiceRecord(
                name=bare_name,
                folder=folder,
                service_type=raw_type,
                kind=kind,
                url=url,
                description=description,
                capabilities=capabilities,
                ogc_capabilities=ogc_capabilities,
                layers=layers,
                tables=tables,
                gp_tasks=gp_tasks,
                service_data_type=service_data_type,
                single_fused_map_cache=single_fused_map_cache,
                deep_scanned=deep_scanned,
            ),
            diagnostics,
        )

    def _attach_layer_detail(
        self,
        *,
        client: ServerClient,
        folder: str | None,
        bare_name: str,
        service_type: str,
        layers: tuple[LayerRecord, ...],
        identity_field: str,
        diagnostics: list[ScanDiagnostic],
    ) -> tuple[LayerRecord, ...]:
        """Fetch each layer/table resource and attach parsed schema detail.

        Per-layer failures are non-fatal: the layer keeps its summary and a
        ``partial-coverage`` diagnostic records the gap.
        """

        detailed: list[LayerRecord] = []
        for layer in layers:
            try:
                body = client.get_layer(
                    name=bare_name,
                    service_type=service_type,
                    folder=folder,
                    layer_id=layer.id,
                )
            except (
                ServerAuthError,
                ServerForbiddenError,
                ServerNotFoundError,
                ServerRateLimitedError,
                ServerConnectionError,
                ServerApiError,
            ) as exc:
                diagnostics.append(
                    ScanDiagnostic(
                        code=_deep_failure_code(exc),
                        severity="warning",
                        message=(
                            f"layer-detail probe of {bare_name!r} "
                            f"layer {layer.id} failed: {exc.message}"
                        ),
                        field=f"{identity_field}/{layer.id}",
                    )
                )
                detailed.append(layer)
                continue
            detail = parse_layer_detail(body)
            detailed.append(replace(layer, detail=detail))
        return tuple(detailed)


# ---------------------------------------------------------------------------


def _ensure_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _ensure_service_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _split_capabilities(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _parse_layers(value: Any) -> Iterable[LayerRecord]:
    if not isinstance(value, list):
        return ()
    parsed: list[LayerRecord] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        if not isinstance(raw_id, int):
            continue
        name = entry.get("name")
        parsed.append(
            LayerRecord(
                id=raw_id,
                name=name if isinstance(name, str) else f"layer-{raw_id}",
                type=_stringify(entry.get("type")),
                geometry_type=classify_geometry(_stringify(entry.get("geometryType"))),
            )
        )
    return parsed


def _parse_gp_tasks(value: Any) -> tuple[str, ...]:
    """Extract GPServer task names from a service body's ``tasks`` array.

    ArcGIS publishes a GPServer's geoprocessing tasks as a flat array of
    task-name strings. Entries are de-duplicated and ordered for determinism;
    non-string and empty entries are ignored. No task resource is fetched —
    only the names already present on the service body are read.
    """

    if not isinstance(value, list):
        return ()
    names = {item.strip() for item in value if isinstance(item, str) and item.strip()}
    return tuple(sorted(names))


def _deep_failure_code(exc: AssessmentError) -> str:
    if isinstance(exc, ServerRateLimitedError):
        return "server.service.rate-limited"
    if isinstance(exc, (ServerAuthError, ServerForbiddenError)):
        return "server.service.missing-permission"
    return "server.service.deep-failed"


def _build_service_url(root: str, folder: str | None, name: str, service_type: str) -> str:
    if folder:
        return f"{root}/{folder}/{name}/{service_type}"
    return f"{root}/{name}/{service_type}"


def _service_identity_field(folder: str | None, name: str, service_type: str) -> str:
    """Stable diagnostic scope keyed by full service identity.

    The emitter filters the inventory by these triples, so two services
    sharing a bare name (e.g. ``Planning/Parcels`` and ``Utilities/Parcels``)
    are not collapsed by a terminal diagnostic against either one.
    """

    return f"services/{folder or '_root'}/{name}/{service_type}"


__all__ = ["ServerScanner"]
