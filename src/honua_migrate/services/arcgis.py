"""Safe CLI client for Honua's ArcGIS GeoServices import API.

The source ArcGIS service is only ever discovered by the server.  This module
does not issue requests to it directly, which keeps planning read-only and
centralises SSRF protection in the Honua server endpoint.
"""

from __future__ import annotations

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

ARTIFACT_VERSION = "honua.arcgis-service-migration/v1"
API_PREFIX = "/api/v1/admin/import/geoservices"
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

arcgis_app = typer.Typer(
    help="Discover, plan, and import ArcGIS FeatureServer or MapServer services.",
    no_args_is_help=True,
)


class ArcGisMigrationError(RuntimeError):
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
            str(key): ("[REDACTED]" if str(key).lower() in {"credentials", "accesstoken", "password", "x-api-key", "authorization"} else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


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
            f"Refusing to overwrite existing artifact: {path}; use --force."
        ) from exc
    except OSError as exc:
        raise ArcGisMigrationError(f"Could not write artifact: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_artifact(path: Path) -> dict[str, Any]:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArcGisMigrationError(f"Could not read plan artifact: {exc}") from exc
    if artifact.get("artifactVersion") != ARTIFACT_VERSION or artifact.get("kind") != "plan":
        raise ArcGisMigrationError("Plan artifact is not a supported ArcGIS migration plan.")
    request = artifact.get("request")
    if not isinstance(request, dict):
        raise ArcGisMigrationError("Plan artifact has no valid request.")
    return request


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


def _job_id(job_id: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", job_id) is None:
        raise ArcGisMigrationError("Job ID may contain only letters, numbers, hyphens, and underscores.")
    return job_id


def _request(service_url: str, timeout_seconds: int, token_secret_ref: str | None) -> dict[str, Any]:
    request: dict[str, Any] = {"serviceUrl": _safe_url(service_url), "timeoutSeconds": timeout_seconds}
    if token_secret_ref:
        request["credentials"] = {"mode": "token", "accessTokenSecretReference": token_secret_ref}
    return request


def _emit(data: Mapping[str, Any], output: Path | None, *, force: bool = False) -> None:
    if output:
        _write_json(output, data, force=force)
    typer.echo(json.dumps(_redact(data), sort_keys=True))


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
        artifact = {"artifactVersion": ARTIFACT_VERSION, "kind": "plan", "request": request}
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
    request = _read_artifact(plan)
    if token_secret_ref:
        request["credentials"] = {
            "mode": "token",
            "accessTokenSecretReference": token_secret_ref,
        }
    response = ArcGisClient.from_options(honua_url, api_key, timeout_seconds, retries).start(request)
    artifact = {"artifactVersion": ARTIFACT_VERSION, "kind": "apply", "plan": str(plan), "response": response}
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
