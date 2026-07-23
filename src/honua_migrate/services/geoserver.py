"""GeoServer catalog migration client and Typer command group."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

import requests
import typer

from honua_migrate.contract_validation import validate_contract
from honua_migrate.contracts import MigrationError, MigrationPlan
from honua_esri_assess.diagnostics import redact
from honua_esri_assess.output_io import (
    OutputExistsError,
    atomic_write_text,
    ensure_overwrite_allowed,
)
from honua_esri_assess.redaction import sanitize_handoff_url

geoserver_app = typer.Typer(help="Migrate GeoServer catalogs through Honua jobs.")

_INVENTORY_SCHEMA = "honua-migrate/geoserver-inventory/v1"
_SECRET_KEY = re.compile(r"(?i)(password|secret|token|api[_-]?key|authorization)")
_LOCAL_REFERENCE = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")
_SERVER_REFERENCE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_ACTIVE_STATUSES = frozenset({"queued", "processing"})
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_PLAN_CLASSIFICATIONS = (
    "applied",
    "already-applied",
    "manual-review",
    "unsupported",
)
_UNSUPPORTED_BEHAVIORS = {
    "skip": 0,
    "log-warning": 1,
    "fail-import": 2,
}


def resolve_secret_reference(reference: str) -> str:
    """Resolve a local environment reference used for Honua authentication."""
    match = _LOCAL_REFERENCE.fullmatch(reference)
    if not match:
        raise MigrationError("Secret references must use env:VARIABLE_NAME.")
    value = os.environ.get(match.group(1))
    if not value:
        raise MigrationError("The requested secret reference is not available.")
    return value


def validate_server_secret_reference(reference: str) -> str:
    """Validate, but never resolve, a reference interpreted by Honua."""
    if not _SERVER_REFERENCE.fullmatch(reference):
        raise MigrationError("GeoServer secret reference syntax is invalid.")
    return reference


def redact_artifact(value: Any, *, key: str = "") -> Any:
    """Produce JSON-safe output with secrets and credential references removed."""
    if _SECRET_KEY.search(key):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {
            str(k): redact_artifact(v, key=str(k))
            for k, v in value.items()
            if not _SECRET_KEY.search(str(k))
        }
    if isinstance(value, list):
        return [redact_artifact(item) for item in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            value = sanitize_handoff_url(value)
        return redact(value)
    return value


def validate_url(value: str, *, label: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MigrationError(f"{label} must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise MigrationError(
            f"{label} cannot contain credentials, a query, or a fragment."
        )
    return value.rstrip("/")


def validate_job_id(job_id: str) -> str:
    if not _JOB_ID.fullmatch(job_id):
        raise MigrationError("Job ID contains unsupported characters.")
    return job_id


def write_artifact(
    payload: Mapping[str, Any], output: Path, *, force: bool
) -> None:
    try:
        ensure_overwrite_allowed(output, force=force)
        serialized = json.dumps(
            redact_artifact(payload), indent=2, sort_keys=True
        ) + "\n"
        atomic_write_text(output, serialized)
    except OutputExistsError as exc:
        raise MigrationError(
            "Output already exists; pass --force to overwrite it."
        ) from exc
    except OSError as exc:
        raise MigrationError("Could not write the requested artifact.") from exc


def _preflight_output(output: Path | None, *, force: bool) -> None:
    if output is None:
        return
    try:
        ensure_overwrite_allowed(output, force=force)
    except OutputExistsError as exc:
        raise MigrationError(
            "Output already exists; pass --force to overwrite it."
        ) from exc


class HonuaMigrationClient:
    """Small client for the public Honua GeoServer migration APIs."""

    def __init__(
        self,
        base_url: str,
        api_key_reference: str,
        *,
        timeout: float = 120,
        retries: int = 3,
    ) -> None:
        if timeout <= 0 or retries < 0:
            raise MigrationError(
                "Timeout must be positive and retries cannot be negative."
            )
        self.base_url = validate_url(base_url, label="Honua URL")
        self.api_key = resolve_secret_reference(api_key_reference)
        self.timeout = timeout
        self.retries = retries

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.base_url + "/" + path.lstrip("/")
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        retry_count = self.retries if method.upper() == "GET" else 0
        for attempt in range(retry_count + 1):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    json=body,
                    timeout=self.timeout,
                )
                if (
                    response.status_code in {429, 502, 503, 504}
                    and attempt < retry_count
                ):
                    time.sleep(min(2**attempt, 4))
                    continue
                if not response.ok:
                    raise MigrationError(
                        f"Honua API request failed with HTTP {response.status_code}."
                    )
                data = response.json()
                if not isinstance(data, dict):
                    raise MigrationError(
                        "Honua API returned an invalid JSON response."
                    )
                return data
            except MigrationError:
                raise
            except (requests.RequestException, ValueError) as exc:
                if attempt == retry_count:
                    raise MigrationError("Honua API request failed.") from exc
                time.sleep(min(2**attempt, 4))
        raise AssertionError("request retry loop did not terminate")

    def scan(
        self,
        source_url: str,
        username: str | None,
        password_reference: str | None,
        *,
        include_styles: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "geoServerRestUrl": validate_url(
                source_url, label="GeoServer URL"
            ),
            "includeStyleContent": include_styles,
        }
        if username:
            body["username"] = username
        if password_reference:
            body["password"] = resolve_secret_reference(password_reference)
        return self.request(
            "POST", "/api/v1/admin/import/geoserver/discover", body=body
        )

    def start(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self.request(
            "POST", "/api/v1/admin/import/geoserver/start", body=request
        )

    def status(self, job_id: str) -> dict[str, Any]:
        safe_id = validate_job_id(job_id)
        return self.request(
            "GET", f"/api/v1/admin/import/geoserver/jobs/{safe_id}"
        )

    def list(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/admin/import/geoserver/jobs")

    def cancel(self, job_id: str) -> dict[str, Any]:
        safe_id = validate_job_id(job_id)
        return self.request(
            "POST",
            f"/api/v1/admin/import/geoserver/jobs/{safe_id}/cancel",
            body={},
        )

    def wait_for_completed(
        self,
        job_id: str,
        *,
        wait_timeout: float,
        poll_interval: float,
    ) -> dict[str, Any]:
        job = self.wait_for_terminal(
            job_id,
            wait_timeout=wait_timeout,
            poll_interval=poll_interval,
        )
        status = str(job.get("status", "")).lower()
        if status != "completed":
            raise MigrationError(
                f"GeoServer dry-run job ended with {status} status."
            )
        _validate_completed_job(job, expected_job_id=job_id)
        return job

    def wait_for_terminal(
        self,
        job_id: str,
        *,
        wait_timeout: float,
        poll_interval: float,
    ) -> dict[str, Any]:
        """Bounded GET-only wait for an existing job's terminal state."""
        validate_job_id(job_id)
        if wait_timeout <= 0 or poll_interval < 0:
            raise MigrationError(
                "Wait timeout must be positive and poll interval cannot be negative."
            )
        deadline = time.monotonic() + wait_timeout
        while True:
            job = self.status(job_id)
            if job.get("jobId") != job_id:
                raise MigrationError("GeoServer job identity changed while waiting.")
            status = str(job.get("status", "")).lower()
            if status in _TERMINAL_STATUSES:
                return job
            if status not in _ACTIVE_STATUSES:
                raise MigrationError(
                    "GeoServer job returned an unknown status."
                )
            if time.monotonic() >= deadline:
                raise MigrationError("Timed out waiting for the GeoServer job.")
            time.sleep(poll_interval)


def _client(
    url: str, key: str, timeout: float, retries: int
) -> HonuaMigrationClient:
    return HonuaMigrationClient(url, key, timeout=timeout, retries=retries)


def _emit(
    payload: Mapping[str, Any], output: Path | None, force: bool
) -> None:
    safe = redact_artifact(payload)
    if output:
        write_artifact(safe, output, force=force)
    typer.echo(json.dumps(safe, indent=2, sort_keys=True))


def _validate_completed_job(
    job: Mapping[str, Any], *, expected_job_id: str
) -> None:
    if (
        job.get("jobId") != expected_job_id
        or str(job.get("status", "")).lower() != "completed"
        or not isinstance(job.get("completedAt"), str)
        or not job["completedAt"]
        or not isinstance(job.get("geoServerUrl"), str)
        or not isinstance(job.get("progress"), Mapping)
    ):
        raise MigrationError(
            "GeoServer dry-run job did not return complete terminal evidence."
        )


def _safe_completed_result(job: Mapping[str, Any]) -> dict[str, Any]:
    progress = job["progress"]
    assert isinstance(progress, Mapping)
    apply_plan = progress.get("applyPlan")
    return {
        "geoServerUrl": validate_url(
            str(job["geoServerUrl"]), label="GeoServer result URL"
        ),
        "resourcesProcessed": progress.get("resourcesProcessed"),
        "estimatedTotalResources": progress.get("estimatedTotalResources"),
        "failedResources": progress.get("failedResources"),
        "resourceBreakdown": progress.get("resourceBreakdown"),
        "applyPlan": apply_plan,
        "classifications": _classify_apply_plan(apply_plan),
    }


def _classify_apply_plan(value: Any) -> dict[str, list[Any]]:
    """Group only classifications explicitly present in server plan evidence."""
    grouped: dict[str, list[Any]] = {
        classification: [] for classification in _PLAN_CLASSIFICATIONS
    }
    if not isinstance(value, Mapping):
        return grouped
    steps = value.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            classification = step.get("outcome", step.get("disposition"))
            if classification in grouped:
                grouped[str(classification)].append(dict(step))
    manual_items = value.get("manualReviewItems")
    if isinstance(manual_items, list):
        grouped["manual-review"].extend(manual_items)
    unsupported_items = value.get("unsupportedItems")
    if isinstance(unsupported_items, list):
        grouped["unsupported"].extend(unsupported_items)
    return grouped


def _unsupported_behavior(value: str, *, label: str) -> int:
    try:
        return _UNSUPPORTED_BEHAVIORS[value]
    except KeyError as exc:
        allowed = ", ".join(_UNSUPPORTED_BEHAVIORS)
        raise MigrationError(f"{label} must be one of: {allowed}.") from exc


def _workspace_mappings(values: list[str] | None) -> dict[str, str] | None:
    if not values:
        return None
    mappings: dict[str, str] = {}
    for value in values:
        source, separator, target = value.partition("=")
        if not separator or not source.strip() or not target.strip():
            raise MigrationError(
                "Workspace mappings must use SOURCE=TARGET syntax."
            )
        source = source.strip()
        if source in mappings:
            raise MigrationError("Workspace mappings cannot repeat a source.")
        mappings[source] = target.strip()
    return mappings


def _inventory_artifact(
    source_url: str, discovery: Mapping[str, Any]
) -> dict[str, Any]:
    compatibility = discovery.get("migrationCompatibility")
    if compatibility is None:
        compatibility = discovery.get("compatibility")
    return {
        "schemaVersion": _INVENTORY_SCHEMA,
        "kind": "geoserver-inventory",
        "source": {
            "geoServerRestUrl": validate_url(
                source_url, label="GeoServer URL"
            )
        },
        "inventory": dict(discovery),
        "compatibility": compatibility,
    }


def _build_start_request(
    *,
    geoserver_url: str,
    geoserver_password_ref: str,
    username: str | None,
    dry_run: bool,
    timeout: float,
    retries: int,
    workspaces: list[str] | None = None,
    datastores: list[str] | None = None,
    layers: list[str] | None = None,
    import_styles: bool = False,
    overwrite_existing: bool = False,
    target_srid: int | None = None,
    auto_publish_layers: bool = True,
    batch_size: int = 10,
    unsupported_datastore_behavior: str = "log-warning",
    unsupported_layer_behavior: str = "log-warning",
    unsupported_style_behavior: str = "log-warning",
    continue_on_resource_failure: bool = True,
    workspace_mappings: list[str] | None = None,
    default_workspace_name: str = "geoserver-import",
) -> dict[str, Any]:
    if target_srid is not None and target_srid <= 0:
        raise MigrationError("Target SRID must be positive.")
    if batch_size <= 0:
        raise MigrationError("Batch size must be positive.")
    if not default_workspace_name.strip():
        raise MigrationError("Default workspace name cannot be empty.")
    import_options: dict[str, Any] = {
        "unsupportedDataStoreBehavior": _unsupported_behavior(
            unsupported_datastore_behavior,
            label="Unsupported datastore behavior",
        ),
        "unsupportedLayerBehavior": _unsupported_behavior(
            unsupported_layer_behavior,
            label="Unsupported layer behavior",
        ),
        "unsupportedStyleBehavior": _unsupported_behavior(
            unsupported_style_behavior,
            label="Unsupported style behavior",
        ),
        "continueOnResourceFailure": continue_on_resource_failure,
        "defaultWorkspaceName": default_workspace_name.strip(),
    }
    mappings = _workspace_mappings(workspace_mappings)
    if mappings:
        import_options["workspaceNameMappings"] = mappings
    body: dict[str, Any] = {
        "geoServerRestUrl": validate_url(
            geoserver_url, label="GeoServer URL"
        ),
        "passwordSecretReference": validate_server_secret_reference(
            geoserver_password_ref
        ),
        "dryRun": dry_run,
        "applyMode": not dry_run,
        "requestTimeoutSeconds": int(timeout),
        "maxRetries": retries,
        "importStyles": import_styles,
        "overwriteExisting": overwrite_existing,
        "autoPublishLayers": auto_publish_layers,
        "batchSize": batch_size,
        "importOptions": import_options,
    }
    if target_srid is not None:
        body["targetSrid"] = target_srid
    if username:
        body["username"] = username
    if workspaces:
        body["workspaceNames"] = workspaces
    if datastores:
        body["dataStoreNames"] = datastores
    if layers:
        body["layerNames"] = layers
    return body


def _plan_request_without_credentials(
    request: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        key: value
        for key, value in request.items()
        if not _SECRET_KEY.search(key)
    }


def _load_completed_plan(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(
            "Plan must be a completed GeoServer dry-run artifact."
        ) from exc
    if not isinstance(payload, dict):
        raise MigrationError(
            "Plan must be a completed GeoServer dry-run artifact."
        )
    validate_contract("plan", payload)
    actions = payload.get("actions")
    action = actions[0] if isinstance(actions, list) and len(actions) == 1 else None
    request = action.get("request") if isinstance(action, dict) else None
    job = action.get("dry_run_job") if isinstance(action, dict) else None
    if (
        payload.get("contract_version") != "v1"
        or payload.get("service") != "geoserver"
        or payload.get("safety_mode") != "plan"
        or not isinstance(payload.get("id"), str)
        or not payload["id"]
        or not isinstance(action, dict)
        or not isinstance(request, dict)
        or not isinstance(job, dict)
        or action.get("kind") != "geoserver-import"
        or request.get("dryRun") is not True
        or request.get("applyMode") is not False
    ):
        raise MigrationError(
            "Plan must be a completed GeoServer dry-run artifact."
        )
    contract = MigrationPlan(
        id=str(payload["id"]),
        service=str(payload["service"]),
        actions=tuple(payload["actions"]),
    )
    if not contract.verify(payload):
        raise MigrationError("Plan digest does not match its contents.")
    job_id = job.get("jobId")
    if not isinstance(job_id, str):
        raise MigrationError("Plan does not contain a valid dry-run job identity.")
    validate_job_id(job_id)
    if payload["id"] != f"geoserver-plan-{job_id}":
        raise MigrationError("Plan identity does not match its dry-run job.")
    if (
        str(job.get("status", "")).lower() != "completed"
        or not isinstance(job.get("completedAt"), str)
        or not job["completedAt"]
        or not isinstance(action.get("result"), dict)
    ):
        raise MigrationError("Plan does not contain completed dry-run evidence.")
    return request, job


def _verify_plan_job(
    client: HonuaMigrationClient,
    request: Mapping[str, Any],
    recorded_job: Mapping[str, Any],
) -> None:
    job_id = str(recorded_job["jobId"])
    live_job = client.status(job_id)
    _validate_completed_job(live_job, expected_job_id=job_id)
    if (
        live_job.get("completedAt") != recorded_job.get("completedAt")
        or validate_url(
            str(live_job.get("geoServerUrl")), label="GeoServer result URL"
        )
        != validate_url(
            str(request.get("geoServerRestUrl")), label="GeoServer URL"
        )
    ):
        raise MigrationError(
            "Plan dry-run evidence does not match the server job."
        )


@geoserver_app.command("scan")
def scan_command(
    honua_url: Annotated[str, typer.Option("--honua-url")],
    honua_api_key_ref: Annotated[
        str, typer.Option("--honua-api-key-ref")
    ],
    geoserver_url: Annotated[str, typer.Option("--geoserver-url")],
    geoserver_password_ref: Annotated[
        str | None, typer.Option("--geoserver-password-ref")
    ] = None,
    username: Annotated[str | None, typer.Option("--username")] = None,
    include_styles: Annotated[
        bool, typer.Option("--include-styles/--no-include-styles")
    ] = True,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    retries: Annotated[int, typer.Option("--retries")] = 3,
) -> None:
    """Discover a GeoServer catalog; this source operation is read-only."""
    _preflight_output(output, force=force)
    discovery = _client(honua_url, honua_api_key_ref, timeout, retries).scan(
        geoserver_url,
        username,
        geoserver_password_ref,
        include_styles=include_styles,
    )
    _emit(_inventory_artifact(geoserver_url, discovery), output, force)


@geoserver_app.command("plan")
def plan_command(
    honua_url: Annotated[str, typer.Option("--honua-url")],
    honua_api_key_ref: Annotated[
        str, typer.Option("--honua-api-key-ref")
    ],
    geoserver_url: Annotated[str, typer.Option("--geoserver-url")],
    geoserver_password_ref: Annotated[
        str, typer.Option("--geoserver-password-ref")
    ],
    username: Annotated[str | None, typer.Option("--username")] = None,
    workspace: Annotated[
        list[str] | None, typer.Option("--workspace")
    ] = None,
    datastore: Annotated[
        list[str] | None, typer.Option("--datastore")
    ] = None,
    layer: Annotated[list[str] | None, typer.Option("--layer")] = None,
    import_styles: Annotated[
        bool, typer.Option("--import-styles/--no-import-styles")
    ] = False,
    overwrite_existing: Annotated[
        bool,
        typer.Option("--overwrite-existing/--no-overwrite-existing"),
    ] = False,
    target_srid: Annotated[int | None, typer.Option("--target-srid")] = None,
    auto_publish_layers: Annotated[
        bool, typer.Option("--auto-publish/--no-auto-publish")
    ] = True,
    batch_size: Annotated[int, typer.Option("--batch-size")] = 10,
    unsupported_datastore_behavior: Annotated[
        str, typer.Option("--unsupported-datastore")
    ] = "log-warning",
    unsupported_layer_behavior: Annotated[
        str, typer.Option("--unsupported-layer")
    ] = "log-warning",
    unsupported_style_behavior: Annotated[
        str, typer.Option("--unsupported-style")
    ] = "log-warning",
    continue_on_resource_failure: Annotated[
        bool,
        typer.Option(
            "--continue-on-resource-failure/--stop-on-resource-failure"
        ),
    ] = True,
    workspace_mapping: Annotated[
        list[str] | None, typer.Option("--workspace-map")
    ] = None,
    default_workspace_name: Annotated[
        str, typer.Option("--default-workspace")
    ] = "geoserver-import",
    output: Annotated[Path | None, typer.Option("--output")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    retries: Annotated[int, typer.Option("--retries")] = 3,
    wait_timeout: Annotated[
        float, typer.Option("--wait-timeout")
    ] = 600,
    poll_interval: Annotated[
        float, typer.Option("--poll-interval")
    ] = 1,
) -> None:
    """Run a dry-run to completion and emit reviewable evidence."""
    _preflight_output(output, force=force)
    request = _build_start_request(
        geoserver_url=geoserver_url,
        geoserver_password_ref=geoserver_password_ref,
        username=username,
        dry_run=True,
        timeout=timeout,
        retries=retries,
        workspaces=workspace,
        datastores=datastore,
        layers=layer,
        import_styles=import_styles,
        overwrite_existing=overwrite_existing,
        target_srid=target_srid,
        auto_publish_layers=auto_publish_layers,
        batch_size=batch_size,
        unsupported_datastore_behavior=unsupported_datastore_behavior,
        unsupported_layer_behavior=unsupported_layer_behavior,
        unsupported_style_behavior=unsupported_style_behavior,
        continue_on_resource_failure=continue_on_resource_failure,
        workspace_mappings=workspace_mapping,
        default_workspace_name=default_workspace_name,
    )
    client = _client(honua_url, honua_api_key_ref, timeout, retries)
    queued = client.start(request)
    job_id = queued.get("jobId")
    if not isinstance(job_id, str):
        raise MigrationError("Honua did not return a dry-run job identity.")
    validate_job_id(job_id)
    completed = client.wait_for_completed(
        job_id,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
    )
    plan_request = _plan_request_without_credentials(request)
    action: dict[str, Any] = {
        "kind": "geoserver-import",
        "request": plan_request,
        "dry_run_job": {
            "jobId": job_id,
            "status": "completed",
            "completedAt": completed["completedAt"],
        },
        "result": _safe_completed_result(completed),
    }
    safe_action = redact_artifact(action)
    if not isinstance(safe_action, dict):
        raise MigrationError("Could not produce a credential-free plan artifact.")
    artifact = MigrationPlan(
        id=f"geoserver-plan-{job_id}",
        service="geoserver",
        actions=(safe_action,),
    ).to_dict()
    validate_contract("plan", artifact)
    _emit(artifact, output, force)


@geoserver_app.command("apply")
def apply_command(
    honua_url: Annotated[str, typer.Option("--honua-url")],
    honua_api_key_ref: Annotated[
        str, typer.Option("--honua-api-key-ref")
    ],
    plan: Annotated[
        Path,
        typer.Option(
            "--plan", help="Reviewed artifact emitted by the plan command."
        ),
    ],
    geoserver_password_ref: Annotated[
        str, typer.Option("--geoserver-password-ref")
    ],
    acknowledge: Annotated[
        bool,
        typer.Option(
            "--acknowledge-apply",
            help="Required acknowledgement to mutate the target catalog.",
        ),
    ] = False,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    retries: Annotated[int, typer.Option("--retries")] = 3,
) -> None:
    """Apply a reviewed, completed plan with explicit acknowledgement."""
    if not acknowledge:
        raise typer.BadParameter(
            "--acknowledge-apply is required for target mutations."
        )
    _preflight_output(output, force=force)
    request, recorded_job = _load_completed_plan(plan)
    password_reference = validate_server_secret_reference(
        geoserver_password_ref
    )
    client = _client(honua_url, honua_api_key_ref, timeout, retries)
    _verify_plan_job(client, request, recorded_job)
    apply_request = dict(request)
    apply_request.update(
        {
            "passwordSecretReference": password_reference,
            "dryRun": False,
            "applyMode": True,
        }
    )
    _emit(client.start(apply_request), output, force)


def _job_command(
    action: str,
    honua_url: str,
    honua_api_key_ref: str,
    job_id: str | None,
    output: Path | None,
    force: bool,
    timeout: float,
    retries: int,
) -> None:
    _preflight_output(output, force=force)
    client = _client(honua_url, honua_api_key_ref, timeout, retries)
    if action == "list":
        payload = client.list()
    elif action == "status":
        payload = client.status(job_id or "")
    else:
        payload = client.cancel(job_id or "")
    _emit(payload, output, force)


@geoserver_app.command("status")
def status_command(
    honua_url: Annotated[str, typer.Option("--honua-url")],
    honua_api_key_ref: Annotated[
        str, typer.Option("--honua-api-key-ref")
    ],
    job_id: Annotated[str, typer.Argument()],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    retries: Annotated[int, typer.Option("--retries")] = 3,
) -> None:
    _job_command(
        "status",
        honua_url,
        honua_api_key_ref,
        job_id,
        output,
        force,
        timeout,
        retries,
    )


@geoserver_app.command("resume")
def resume_command(
    honua_url: Annotated[str, typer.Option("--honua-url")],
    honua_api_key_ref: Annotated[
        str, typer.Option("--honua-api-key-ref")
    ],
    job_id: Annotated[str, typer.Argument()],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    retries: Annotated[int, typer.Option("--retries")] = 3,
    wait_timeout: Annotated[
        float, typer.Option("--wait-timeout")
    ] = 600,
    poll_interval: Annotated[
        float, typer.Option("--poll-interval")
    ] = 1,
) -> None:
    """Resume monitoring an existing job until a bounded terminal state."""
    _preflight_output(output, force=force)
    client = _client(honua_url, honua_api_key_ref, timeout, retries)
    job = client.wait_for_terminal(
        job_id,
        wait_timeout=wait_timeout,
        poll_interval=poll_interval,
    )
    _emit(job, output, force)


@geoserver_app.command("list")
def list_command(
    honua_url: Annotated[str, typer.Option("--honua-url")],
    honua_api_key_ref: Annotated[
        str, typer.Option("--honua-api-key-ref")
    ],
    output: Annotated[Path | None, typer.Option("--output")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    retries: Annotated[int, typer.Option("--retries")] = 3,
) -> None:
    _job_command(
        "list",
        honua_url,
        honua_api_key_ref,
        None,
        output,
        force,
        timeout,
        retries,
    )


@geoserver_app.command("cancel")
def cancel_command(
    honua_url: Annotated[str, typer.Option("--honua-url")],
    honua_api_key_ref: Annotated[
        str, typer.Option("--honua-api-key-ref")
    ],
    job_id: Annotated[str, typer.Argument()],
    acknowledge: Annotated[
        bool, typer.Option("--acknowledge-cancel")
    ] = False,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    retries: Annotated[int, typer.Option("--retries")] = 3,
) -> None:
    if not acknowledge:
        raise typer.BadParameter(
            "--acknowledge-cancel is required to cancel a job."
        )
    _job_command(
        "cancel",
        honua_url,
        honua_api_key_ref,
        job_id,
        output,
        force,
        timeout,
        retries,
    )
