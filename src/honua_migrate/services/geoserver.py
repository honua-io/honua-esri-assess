"""GeoServer catalog migration client and Typer command group.

This module deliberately keeps secret values transient: command arguments only
accept ``env:NAME`` references and emitted JSON is recursively redacted.
"""

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

from honua_esri_assess.output_io import atomic_write_text, ensure_overwrite_allowed
from honua_esri_assess.redaction import sanitize_handoff_url

geoserver_app = typer.Typer(help="Migrate GeoServer catalogs through Honua jobs.")

_SECRET_KEY = re.compile(r"(?i)(password|secret|token|api[_-]?key|authorization)")
_REFERENCE = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class MigrationError(Exception):
    """A safe, operator-facing migration failure."""


def resolve_secret_reference(reference: str) -> str:
    """Resolve an environment secret reference without ever serializing it."""
    match = _REFERENCE.fullmatch(reference)
    if not match:
        raise MigrationError("Secret references must use env:VARIABLE_NAME.")
    value = os.environ.get(match.group(1))
    if not value:
        raise MigrationError("The requested secret reference is not available.")
    return value


def redact_artifact(value: Any, *, key: str = "") -> Any:
    """Produce a JSON-safe artifact with secrets and URL auth removed."""
    if _SECRET_KEY.search(key) and not key.lower().endswith("reference"):
        return "<redacted>"
    if isinstance(value, Mapping):
        return {str(k): redact_artifact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_artifact(item) for item in value]
    if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
        return sanitize_handoff_url(value)
    return value


def validate_url(value: str, *, label: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MigrationError(f"{label} must be an absolute HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise MigrationError(f"{label} cannot contain credentials, a query, or a fragment.")
    return value.rstrip("/")


def validate_job_id(job_id: str) -> str:
    if not _JOB_ID.fullmatch(job_id):
        raise MigrationError("Job ID contains unsupported characters.")
    return job_id


def write_artifact(payload: Mapping[str, Any], output: Path, *, force: bool) -> None:
    try:
        ensure_overwrite_allowed(output, force=force)
        atomic_write_text(output, json.dumps(redact_artifact(payload), indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise MigrationError("Could not write the requested artifact.") from exc


class HonuaMigrationClient:
    """Small retrying client for the public Honua GeoServer migration APIs."""

    def __init__(self, base_url: str, api_key_reference: str, *, timeout: float = 120, retries: int = 3) -> None:
        if timeout <= 0 or retries < 0:
            raise MigrationError("Timeout must be positive and retries cannot be negative.")
        self.base_url = validate_url(base_url, label="Honua URL")
        self.api_key = resolve_secret_reference(api_key_reference)
        self.timeout = timeout
        self.retries = retries

    def request(self, method: str, path: str, *, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        url = self.base_url + "/" + path.lstrip("/")
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        last_error: Exception | None = None
        retry_count = self.retries if method.upper() == "GET" else 0
        for attempt in range(retry_count + 1):
            try:
                response = requests.request(method, url, headers=headers, json=body, timeout=self.timeout)
                if response.status_code in {429, 502, 503, 504} and attempt < retry_count:
                    time.sleep(min(2**attempt, 4))
                    continue
                if not response.ok:
                    raise MigrationError(f"Honua API request failed with HTTP {response.status_code}.")
                data = response.json()
                if not isinstance(data, dict):
                    raise MigrationError("Honua API returned an invalid JSON response.")
                return data
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                if attempt < retry_count:
                    time.sleep(min(2**attempt, 4))
        raise MigrationError("Honua API request failed after retrying.") from last_error

    def scan(self, source_url: str, username: str | None, password_reference: str | None, *, include_styles: bool) -> dict[str, Any]:
        body: dict[str, Any] = {"geoServerRestUrl": validate_url(source_url, label="GeoServer URL"), "includeStyleContent": include_styles}
        if username:
            body["username"] = username
        if password_reference:
            body["password"] = resolve_secret_reference(password_reference)
        return self.request("POST", "/api/v1/admin/import/geoserver/discover", body=body)

    def start(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/api/v1/admin/import/geoserver/start", body=request)

    def status(self, job_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/v1/admin/import/geoserver/jobs/{validate_job_id(job_id)}")

    def list(self) -> dict[str, Any]:
        return self.request("GET", "/api/v1/admin/import/geoserver/jobs")

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self.request("POST", f"/api/v1/admin/import/geoserver/jobs/{validate_job_id(job_id)}/cancel", body={})


def _client(url: str, key: str, timeout: float, retries: int) -> HonuaMigrationClient:
    return HonuaMigrationClient(url, key, timeout=timeout, retries=retries)


def _emit(payload: Mapping[str, Any], output: Path | None, force: bool) -> None:
    safe = redact_artifact(payload)
    if output:
        write_artifact(safe, output, force=force)
    typer.echo(json.dumps(safe, indent=2, sort_keys=True))


@geoserver_app.command("scan")
def scan_command(
    honua_url: Annotated[str, typer.Option("--honua-url")],
    honua_api_key_ref: Annotated[str, typer.Option("--honua-api-key-ref")],
    geoserver_url: Annotated[str, typer.Option("--geoserver-url")],
    geoserver_password_ref: Annotated[str | None, typer.Option("--geoserver-password-ref")] = None,
    username: Annotated[str | None, typer.Option("--username")] = None,
    include_styles: Annotated[bool, typer.Option("--include-styles/--no-include-styles")] = True,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    timeout: Annotated[float, typer.Option("--timeout")] = 120,
    retries: Annotated[int, typer.Option("--retries")] = 3,
) -> None:
    """Discover a GeoServer catalog; this source operation is read-only."""
    _emit(_client(honua_url, honua_api_key_ref, timeout, retries).scan(geoserver_url, username, geoserver_password_ref, include_styles=include_styles), output, force)


def _start_command(*, dry_run: bool, honua_url: str, honua_api_key_ref: str, geoserver_url: str, geoserver_password_ref: str, username: str | None, output: Path | None, force: bool, timeout: float, retries: int, apply: bool = False, workspaces: list[str] | None = None, datastores: list[str] | None = None, layers: list[str] | None = None) -> None:
    body: dict[str, Any] = {"geoServerRestUrl": validate_url(geoserver_url, label="GeoServer URL"), "passwordSecretReference": geoserver_password_ref, "dryRun": dry_run, "applyMode": apply, "requestTimeoutSeconds": int(timeout), "maxRetries": retries}
    if username:
        body["username"] = username
    if workspaces:
        body["workspaceNames"] = workspaces
    if datastores:
        body["dataStoreNames"] = datastores
    if layers:
        body["layerNames"] = layers
    response = _client(honua_url, honua_api_key_ref, timeout, retries).start(body)
    payload: Mapping[str, Any] = response
    if dry_run:
        payload = {"schemaVersion": "honua-migrate/geoserver-plan/v1", "kind": "geoserver-plan", "request": body, "job": response}
    _emit(payload, output, force)


@geoserver_app.command("plan")
def plan_command(honua_url: Annotated[str, typer.Option("--honua-url")], honua_api_key_ref: Annotated[str, typer.Option("--honua-api-key-ref")], geoserver_url: Annotated[str, typer.Option("--geoserver-url")], geoserver_password_ref: Annotated[str, typer.Option("--geoserver-password-ref")], username: Annotated[str | None, typer.Option("--username")] = None, workspace: Annotated[list[str] | None, typer.Option("--workspace")] = None, datastore: Annotated[list[str] | None, typer.Option("--datastore")] = None, layer: Annotated[list[str] | None, typer.Option("--layer")] = None, output: Annotated[Path | None, typer.Option("--output")] = None, force: Annotated[bool, typer.Option("--force")] = False, timeout: Annotated[float, typer.Option("--timeout")] = 120, retries: Annotated[int, typer.Option("--retries")] = 3) -> None:
    """Queue a dry-run that emits the deterministic migration plan."""
    _start_command(dry_run=True, honua_url=honua_url, honua_api_key_ref=honua_api_key_ref, geoserver_url=geoserver_url, geoserver_password_ref=geoserver_password_ref, username=username, output=output, force=force, timeout=timeout, retries=retries, workspaces=workspace, datastores=datastore, layers=layer)


@geoserver_app.command("apply")
def apply_command(honua_url: Annotated[str, typer.Option("--honua-url")], honua_api_key_ref: Annotated[str, typer.Option("--honua-api-key-ref")], plan: Annotated[Path, typer.Option("--plan", help="Reviewed artifact emitted by the plan command.")], acknowledge: Annotated[bool, typer.Option("--acknowledge-apply", help="Required acknowledgement to mutate the target catalog.")] = False, output: Annotated[Path | None, typer.Option("--output")] = None, force: Annotated[bool, typer.Option("--force")] = False, timeout: Annotated[float, typer.Option("--timeout")] = 120, retries: Annotated[int, typer.Option("--retries")] = 3) -> None:
    """Apply a reviewed plan; requires explicit acknowledgement."""
    if not acknowledge:
        raise typer.BadParameter("--acknowledge-apply is required for target mutations.")
    try:
        reviewed = json.loads(plan.read_text(encoding="utf-8"))
        request = reviewed["request"]
        if reviewed.get("kind") != "geoserver-plan" or request.get("dryRun") is not True:
            raise ValueError
        source_url = str(request["geoServerRestUrl"])
        password_ref = str(request["passwordSecretReference"])
    except (OSError, ValueError, KeyError, TypeError):
        raise typer.BadParameter("--plan must be a reviewed GeoServer dry-run artifact.") from None
    _start_command(dry_run=False, apply=True, honua_url=honua_url, honua_api_key_ref=honua_api_key_ref, geoserver_url=source_url, geoserver_password_ref=password_ref, username=request.get("username"), output=output, force=force, timeout=timeout, retries=retries, workspaces=request.get("workspaceNames"), datastores=request.get("dataStoreNames"), layers=request.get("layerNames"))


def _job_command(action: str, honua_url: str, honua_api_key_ref: str, job_id: str | None, output: Path | None, force: bool, timeout: float, retries: int) -> None:
    client = _client(honua_url, honua_api_key_ref, timeout, retries)
    payload = client.list() if action == "list" else client.status(job_id or "") if action == "status" else client.cancel(job_id or "")
    _emit(payload, output, force)


@geoserver_app.command("status")
def status_command(honua_url: Annotated[str, typer.Option("--honua-url")], honua_api_key_ref: Annotated[str, typer.Option("--honua-api-key-ref")], job_id: Annotated[str, typer.Argument()], output: Annotated[Path | None, typer.Option("--output")] = None, force: Annotated[bool, typer.Option("--force")] = False, timeout: Annotated[float, typer.Option("--timeout")] = 120, retries: Annotated[int, typer.Option("--retries")] = 3) -> None:
    _job_command("status", honua_url, honua_api_key_ref, job_id, output, force, timeout, retries)


@geoserver_app.command("list")
def list_command(honua_url: Annotated[str, typer.Option("--honua-url")], honua_api_key_ref: Annotated[str, typer.Option("--honua-api-key-ref")], output: Annotated[Path | None, typer.Option("--output")] = None, force: Annotated[bool, typer.Option("--force")] = False, timeout: Annotated[float, typer.Option("--timeout")] = 120, retries: Annotated[int, typer.Option("--retries")] = 3) -> None:
    _job_command("list", honua_url, honua_api_key_ref, None, output, force, timeout, retries)


@geoserver_app.command("cancel")
def cancel_command(honua_url: Annotated[str, typer.Option("--honua-url")], honua_api_key_ref: Annotated[str, typer.Option("--honua-api-key-ref")], job_id: Annotated[str, typer.Argument()], acknowledge: Annotated[bool, typer.Option("--acknowledge-cancel")] = False, output: Annotated[Path | None, typer.Option("--output")] = None, force: Annotated[bool, typer.Option("--force")] = False, timeout: Annotated[float, typer.Option("--timeout")] = 120, retries: Annotated[int, typer.Option("--retries")] = 3) -> None:
    if not acknowledge:
        raise typer.BadParameter("--acknowledge-cancel is required to cancel a job.")
    _job_command("cancel", honua_url, honua_api_key_ref, job_id, output, force, timeout, retries)


@geoserver_app.command("resume")
def resume_command(honua_url: Annotated[str, typer.Option("--honua-url")], honua_api_key_ref: Annotated[str, typer.Option("--honua-api-key-ref")], job_id: Annotated[str, typer.Argument()], output: Annotated[Path | None, typer.Option("--output")] = None, force: Annotated[bool, typer.Option("--force")] = False, timeout: Annotated[float, typer.Option("--timeout")] = 120, retries: Annotated[int, typer.Option("--retries")] = 3) -> None:
    """Resume by retrieving durable job state; re-apply only after review."""
    _job_command("status", honua_url, honua_api_key_ref, job_id, output, force, timeout, retries)
