"""Safe CLI client for Honua's ArcGIS GeoServices import API.

The source ArcGIS service is only ever discovered by the server.  This module
does not issue requests to it directly, which keeps planning read-only and
centralises SSRF protection in the Honua server endpoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

import requests
import typer

from honua_migrate.contract_validation import assert_artifact_safe, validate_contract
from honua_migrate.contracts import MigrationError, MigrationPlan
from honua_esri_assess.redaction import sanitize_handoff_url

ARTIFACT_VERSION = "honua.arcgis-service-migration/v1"
API_PREFIX = "/api/v1/admin/import/geoservices"
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled", "canceled"}

arcgis_app = typer.Typer(
    help="Discover, plan, and import ArcGIS FeatureServer or MapServer services.",
    no_args_is_help=True,
)


class ArcGisMigrationError(MigrationError):
    """An actionable, secret-safe error returned by the migration client."""


def _safe_url(value: str, *, allow_relative: bool = False) -> str:
    lower_value = value.lower()
    if (
        not value
        or any(char.isspace() or char == "\\" for char in value)
        or any(encoded in lower_value for encoded in ("%00", "%0a", "%0d"))
    ):
        raise ArcGisMigrationError("URLs must not be blank or contain whitespace controls.")
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ArcGisMigrationError("URLs must not contain credentials, query strings, or fragments.")
    if allow_relative:
        if (
            parsed.scheme
            or parsed.netloc
            or not parsed.path.startswith("/")
            or ".." in parsed.path.split("/")
        ):
            raise ArcGisMigrationError("Server paths must be absolute paths.")
    else:
        try:
            port = parsed.port
        except ValueError as exc:
            raise ArcGisMigrationError("URL port is invalid.") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or port == 0:
            raise ArcGisMigrationError(
                "HONUA_URL and service URLs must be absolute HTTP(S) URLs."
            )
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _get_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ArcGisMigrationError(f"{name} must be set or supplied explicitly.")
    return value


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _redact(item)
            for key, item in value.items()
            if re.search(
                r"password|secret|token|authorization|credential|api[_-]?key|x-api-key",
                str(key),
                flags=re.IGNORECASE,
            )
            is None
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and value.lower().startswith(("http://", "https://")):
        return sanitize_handoff_url(value)
    return value


def _validate_shared_contract(name: str, data: Mapping[str, Any]) -> None:
    try:
        validate_contract(name, data)
    except MigrationError as exc:
        raise ArcGisMigrationError(str(exc)) from exc


def _plan_id(request: Mapping[str, Any]) -> str:
    """Return the foundation-compatible identity for a canonical plan payload."""
    try:
        canonical = json.dumps(
            request,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArcGisMigrationError("Plan request is not canonical JSON.") from exc
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _validate_secret_reference(reference: str | None) -> str | None:
    if reference is None:
        return None
    environment_reference = re.fullmatch(r"env:[A-Za-z_][A-Za-z0-9_]*", reference)
    provider_reference = re.fullmatch(
        r"(?!env:)[A-Za-z][A-Za-z0-9_.-]*:[A-Za-z0-9][A-Za-z0-9_./@+:-]*",
        reference,
        flags=re.IGNORECASE,
    )
    if environment_reference is None and provider_reference is None:
        raise ArcGisMigrationError(
            "Credential must be a provider secret reference such as env:VARIABLE_NAME."
        )
    return reference


def _write_json(path: Path, data: Mapping[str, Any], *, force: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(_redact(data), indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

        if force:
            os.replace(temporary, path)
            temporary = None
        else:
            # Creating the hard link is atomic and fails if the destination exists.
            os.link(temporary, path)
            temporary.unlink()
            temporary = None
    except FileExistsError as exc:
        raise ArcGisMigrationError(
            "Refusing to overwrite an existing artifact; use --force."
        ) from exc
    except OSError as exc:
        raise ArcGisMigrationError("Could not write the requested artifact.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _preflight_output(path: Path | None, *, force: bool) -> None:
    if path is not None and path.exists() and not force:
        raise ArcGisMigrationError(
            "Refusing to overwrite an existing artifact; use --force."
        )


def _read_artifact(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArcGisMigrationError("Could not read the requested plan artifact.") from exc
    if not isinstance(artifact, dict):
        raise ArcGisMigrationError("Plan artifact is not a supported ArcGIS migration plan.")
    stored_id = artifact.get("id")
    if not isinstance(stored_id, str) or not stored_id.startswith("arcgis-plan-"):
        raise ArcGisMigrationError("Plan artifact has no supported immutable plan ID.")
    _validate_shared_contract("plan", artifact)
    actions = artifact.get("actions")
    action = actions[0] if isinstance(actions, list) and len(actions) == 1 else None
    request = action.get("request") if isinstance(action, dict) else None
    if (
        artifact.get("service") != "arcgis"
        or artifact.get("safety_mode") != "plan"
        or not isinstance(actions, list)
        or not isinstance(action, dict)
        or action.get("kind") != "arcgis-service-import"
        or not isinstance(request, dict)
    ):
        raise ArcGisMigrationError("Plan artifact has no valid request.")
    contract = MigrationPlan(
        id=stored_id,
        service="arcgis",
        actions=tuple(actions),
    )
    if not contract.verify(artifact):
        raise ArcGisMigrationError("Plan artifact was modified after it was reviewed.")
    return stored_id, request


@dataclass
class ArcGisClient:
    """Small, injectable HTTP client for the server's GeoServices import API."""

    base_url: str
    api_key: str
    timeout_seconds: float = 30
    retries: int = 2
    session: requests.Session | Any = field(default_factory=requests.Session)
    sleeper: Callable[[float], None] = time.sleep

    @classmethod
    def from_options(
        cls,
        honua_url: str | None,
        api_key: str | None,
        timeout_seconds: float,
        retries: int,
    ) -> "ArcGisClient":
        return cls(
            _safe_url(honua_url or _get_env("HONUA_URL")),
            api_key or _get_env("HONUA_API_KEY"),
            timeout_seconds,
            retries,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        retry: bool = False,
    ) -> dict[str, Any]:
        safe_path = _safe_url(path, allow_relative=True)
        # Retrying a POST could duplicate an import or repeat a cancellation.
        attempts = self.retries + 1 if retry and method.upper() == "GET" else 1
        response: Any = None
        for attempt in range(attempts):
            try:
                response = self.session.request(
                    method,
                    f"{self.base_url}{safe_path}",
                    headers={"X-API-Key": self.api_key, "Accept": "application/json"},
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                if attempt + 1 == attempts:
                    raise ArcGisMigrationError("Honua request failed; check HONUA_URL and network access.") from exc
                self.sleeper(0.25 * (2**attempt))
                continue
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt + 1 == attempts:
                break
            self.sleeper(0.25 * (2**attempt))
        if response is None:
            raise ArcGisMigrationError("Honua request failed.")
        try:
            body = response.json() if response.content else {}
        except ValueError as exc:
            raise ArcGisMigrationError("Honua returned an invalid JSON response.") from exc
        if not response.ok:
            # Server errors may repeat request values.  Never reflect them into CLI output.
            raise ArcGisMigrationError(f"Honua request failed (HTTP {response.status_code}).")
        return body if isinstance(body, dict) else {"result": body}

    def discover(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("POST", f"{API_PREFIX}/discover", payload=request)

    def start(self, request: Mapping[str, Any]) -> dict[str, Any]:
        # Deliberately not retried: replaying a start could enqueue a duplicate import.
        return self.request("POST", f"{API_PREFIX}/start", payload=request)

    def status(self, job_id: str) -> dict[str, Any]:
        return self.request("GET", f"{API_PREFIX}/jobs/{_job_id(job_id)}", retry=True)

    def list(self) -> dict[str, Any]:
        return self.request("GET", f"{API_PREFIX}/jobs", retry=True)

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self.request("POST", f"{API_PREFIX}/jobs/{_job_id(job_id)}/cancel")

    def wait_for_terminal(
        self,
        job_id: str,
        *,
        poll_interval_seconds: float,
        max_wait_seconds: float,
    ) -> dict[str, Any]:
        """GET-poll an existing job without creating or mutating server state."""
        validated_job_id = _job_id(job_id)
        if poll_interval_seconds <= 0 or max_wait_seconds < 0:
            raise ArcGisMigrationError("Poll interval must be positive and max wait non-negative.")
        max_polls = max(1, int(max_wait_seconds // poll_interval_seconds) + 1)
        latest: dict[str, Any] = {}
        for poll_count in range(1, max_polls + 1):
            latest = self.status(validated_job_id)
            status = str(latest.get("status", "")).lower()
            if status in TERMINAL_JOB_STATUSES:
                return {
                    "jobId": validated_job_id,
                    "terminal": True,
                    "timedOut": False,
                    "pollCount": poll_count,
                    "status": latest,
                }
            if poll_count < max_polls:
                self.sleeper(poll_interval_seconds)
        return {
            "jobId": validated_job_id,
            "terminal": False,
            "timedOut": True,
            "pollCount": max_polls,
            "status": latest,
        }


def _job_id(job_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", job_id) is None:
        raise ArcGisMigrationError("Job ID may contain only letters, numbers, hyphens, and underscores.")
    return job_id


def _request(service_url: str, timeout_seconds: int, token_secret_ref: str | None) -> dict[str, Any]:
    request: dict[str, Any] = {"serviceUrl": _safe_url(service_url), "timeoutSeconds": timeout_seconds}
    if token_secret_ref:
        request["credentials"] = {
            "mode": "token",
            "accessTokenSecretReference": _validate_secret_reference(token_secret_ref),
        }
    return request


def _emit(data: Mapping[str, Any], output: Path | None, *, force: bool = False) -> None:
    safe_data = _redact(data)
    try:
        assert_artifact_safe(safe_data)
    except MigrationError as exc:
        raise ArcGisMigrationError(str(exc)) from exc
    if output:
        _write_json(output, safe_data, force=force)
    typer.echo(json.dumps(safe_data, sort_keys=True))


@arcgis_app.command("discover")
def discover_command(
    service_url: str = typer.Argument(..., help="ArcGIS FeatureServer or MapServer root URL."),
    output: Path | None = typer.Option(None, "--output", help="Write a versioned discovery artifact."),
    force: bool = typer.Option(False, "--force", help="Replace an existing output artifact."),
    honua_url: str | None = typer.Option(None, envvar="HONUA_URL"),
    api_key: str | None = typer.Option(None, envvar="HONUA_API_KEY", hide_input=True),
    timeout_seconds: int = typer.Option(30, min=1, max=600),
    retries: int = typer.Option(2, min=0, max=5),
    token_secret_ref: str | None = typer.Option(None, help="Server-side ArcGIS token secret reference."),
) -> None:
    """Read-only discovery; source credentials are never placed in the artifact."""
    try:
        _preflight_output(output, force=force)
        request = _request(service_url, timeout_seconds, token_secret_ref)
        client = ArcGisClient.from_options(honua_url, api_key, timeout_seconds, retries)
        artifact = {"artifactVersion": ARTIFACT_VERSION, "kind": "discovery", "request": request, "discovery": client.discover(request)}
        _emit(artifact, output, force=force)
    except ArcGisMigrationError as exc:
        raise typer.BadParameter(str(exc)) from exc


@arcgis_app.command("plan")
def plan_command(
    service_url: str = typer.Argument(...),
    layer_id: int = typer.Option(..., "--layer-id"),
    table_name: str = typer.Option(..., "--table-name"),
    output: Path = typer.Option(..., "--output", help="Path for the versioned plan artifact."),
    force: bool = typer.Option(False, "--force", help="Replace an existing plan artifact."),
    target_schema: str | None = typer.Option(None),
    target_srid: int = typer.Option(4326, min=1),
    overwrite_existing: bool = typer.Option(False),
    batch_size: int | None = typer.Option(None, min=1),
    max_retries: int = typer.Option(3, min=0, max=20),
    request_timeout_seconds: int = typer.Option(120, min=1, max=3600),
    auto_publish: bool = typer.Option(True, "--auto-publish/--no-auto-publish"),
    service_name: str | None = typer.Option(None),
    where_clause: str | None = typer.Option(None),
    output_fields: list[str] | None = typer.Option(None, help="Repeat for each source field."),
) -> None:
    """Create a local, machine-readable apply plan without mutating either system."""
    try:
        request: dict[str, Any] = {"serviceUrl": _safe_url(service_url)}
        request.update({"layerId": layer_id, "tableName": table_name, "targetSrid": target_srid, "overwriteExisting": overwrite_existing, "maxRetries": max_retries, "requestTimeoutSeconds": request_timeout_seconds, "autoPublish": auto_publish})
        for key, value in {"targetSchema": target_schema, "batchSize": batch_size, "serviceName": service_name, "whereClause": where_clause, "outputFields": output_fields}.items():
            if value is not None:
                request[key] = value
        artifact = MigrationPlan(
            id=f"arcgis-plan-{_plan_id(request).removeprefix('sha256:')}",
            service="arcgis",
            actions=({"kind": "arcgis-service-import", "request": request},),
        ).to_dict()
        _validate_shared_contract("plan", artifact)
        _emit(artifact, output, force=force)
    except ArcGisMigrationError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _apply(
    plan: Path,
    output: Path | None,
    yes: bool,
    honua_url: str | None,
    api_key: str | None,
    timeout_seconds: float,
    retries: int,
    token_secret_ref: str | None,
    force: bool,
) -> None:
    if not yes:
        raise typer.BadParameter("Apply mutates the Honua target. Re-run with --yes.")
    _preflight_output(output, force=force)
    plan_id, request = _read_artifact(plan)
    validated_secret_reference = _validate_secret_reference(token_secret_ref)
    if validated_secret_reference:
        request["credentials"] = {
            "mode": "token",
            "accessTokenSecretReference": validated_secret_reference,
        }
    response = ArcGisClient.from_options(honua_url, api_key, timeout_seconds, retries).start(request)
    artifact = {
        "artifactVersion": ARTIFACT_VERSION,
        "kind": "apply",
        "planId": plan_id,
        "response": response,
    }
    _emit(artifact, output, force=force)


@arcgis_app.command("apply")
def apply_command(
    plan: Path = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Acknowledge target mutation."),
    output: Path | None = typer.Option(None, "--output"),
    force: bool = typer.Option(False, "--force", help="Replace an existing output artifact."),
    honua_url: str | None = typer.Option(None, envvar="HONUA_URL"),
    api_key: str | None = typer.Option(None, envvar="HONUA_API_KEY", hide_input=True),
    timeout_seconds: float = typer.Option(30, min=1), retries: int = typer.Option(2, min=0, max=5),
    token_secret_ref: str | None = typer.Option(
        None, help="Server-side ArcGIS token secret reference; never stored in the plan."
    ),
) -> None:
    """Queue an import from a previously reviewed plan."""
    try:
        _apply(
            plan,
            output,
            yes,
            honua_url,
            api_key,
            timeout_seconds,
            retries,
            token_secret_ref,
            force,
        )
    except ArcGisMigrationError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _job_command(
    action: str,
    job_id: str | None,
    output: Path | None,
    honua_url: str | None,
    api_key: str | None,
    timeout_seconds: float,
    retries: int,
    force: bool,
) -> None:
    _preflight_output(output, force=force)
    validated_job_id = None if action == "list" else _job_id(job_id or "")
    client = ArcGisClient.from_options(honua_url, api_key, timeout_seconds, retries)
    response = (
        client.list()
        if action == "list"
        else getattr(client, action)(validated_job_id)
    )
    _emit(
        {"artifactVersion": ARTIFACT_VERSION, "kind": action, "response": response},
        output,
        force=force,
    )


@arcgis_app.command("status")
def status_command(
    job_id: str = typer.Argument(...),
    output: Path | None = typer.Option(None, "--output"),
    force: bool = typer.Option(False, "--force", help="Replace an existing output artifact."),
    honua_url: str | None = typer.Option(None, envvar="HONUA_URL"),
    api_key: str | None = typer.Option(None, envvar="HONUA_API_KEY", hide_input=True),
    timeout_seconds: float = typer.Option(30, min=1),
    retries: int = typer.Option(2, min=0, max=5),
) -> None:
    try:
        _job_command(
            "status", job_id, output, honua_url, api_key, timeout_seconds, retries, force
        )
    except ArcGisMigrationError as exc:
        raise typer.BadParameter(str(exc)) from exc


@arcgis_app.command("list")
def list_command(
    output: Path | None = typer.Option(None, "--output"),
    force: bool = typer.Option(False, "--force", help="Replace an existing output artifact."),
    honua_url: str | None = typer.Option(None, envvar="HONUA_URL"),
    api_key: str | None = typer.Option(None, envvar="HONUA_API_KEY", hide_input=True),
    timeout_seconds: float = typer.Option(30, min=1),
    retries: int = typer.Option(2, min=0, max=5),
) -> None:
    try:
        _job_command(
            "list", None, output, honua_url, api_key, timeout_seconds, retries, force
        )
    except ArcGisMigrationError as exc:
        raise typer.BadParameter(str(exc)) from exc


@arcgis_app.command("resume")
def resume_command(
    job_id: str = typer.Argument(..., help="Existing ArcGIS import job ID."),
    output: Path | None = typer.Option(None, "--output"),
    force: bool = typer.Option(False, "--force", help="Replace an existing output artifact."),
    honua_url: str | None = typer.Option(None, envvar="HONUA_URL"),
    api_key: str | None = typer.Option(None, envvar="HONUA_API_KEY", hide_input=True),
    timeout_seconds: float = typer.Option(30, min=1),
    retries: int = typer.Option(2, min=0, max=5),
    poll_interval_seconds: float = typer.Option(2, "--poll-interval", min=0.1, max=300),
    max_wait_seconds: float = typer.Option(300, "--max-wait", min=0, max=86400),
) -> None:
    """Wait for an existing job using bounded GET-only polling; never requeue it."""
    try:
        validated_job_id = _job_id(job_id)
        client = ArcGisClient.from_options(honua_url, api_key, timeout_seconds, retries)
        response = client.wait_for_terminal(
            validated_job_id,
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
        )
        _emit(
            {
                "artifactVersion": ARTIFACT_VERSION,
                "kind": "resume",
                "response": response,
            },
            output,
            force=force,
        )
    except ArcGisMigrationError as exc:
        raise typer.BadParameter(str(exc)) from exc


@arcgis_app.command("cancel")
def cancel_command(
    job_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Acknowledge cancellation."),
    output: Path | None = typer.Option(None, "--output"),
    force: bool = typer.Option(False, "--force", help="Replace an existing output artifact."),
    honua_url: str | None = typer.Option(None, envvar="HONUA_URL"),
    api_key: str | None = typer.Option(None, envvar="HONUA_API_KEY", hide_input=True),
    timeout_seconds: float = typer.Option(30, min=1),
    retries: int = typer.Option(2, min=0, max=5),
) -> None:
    try:
        if not yes:
            raise ArcGisMigrationError("Cancel mutates target job state. Re-run with --yes.")
        _job_command(
            "cancel", job_id, output, honua_url, api_key, timeout_seconds, retries, force
        )
    except ArcGisMigrationError as exc:
        raise typer.BadParameter(str(exc)) from exc
