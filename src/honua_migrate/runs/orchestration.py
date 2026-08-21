"""Durable, adapter-neutral execution of immutable migration plans."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from copy import deepcopy
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Protocol
from urllib.parse import urlsplit, urlunsplit

from honua_esri_assess.output_io import atomic_write_text

from ..contract_validation import assert_artifact_safe, validate_contract
from ..contracts import (
    EXIT_APPLY_REFUSED,
    EXIT_INPUT_ERROR,
    EXIT_PARTIAL,
    EXIT_REMOTE_ERROR,
    EXIT_UNAVAILABLE,
    EXIT_VALIDATION_ERROR,
    MigrationError,
    MigrationPlan,
    MigrationRun,
    SafetyMode,
)

_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|secret|token|authorization|api[_-]?key|credential)",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"\bbearer\s+\S+", re.IGNORECASE)
_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


@dataclass(frozen=True)
class ExecutionReceipt:
    """Credential-free evidence returned by a service executor."""

    job_id: str | None = None
    evidence: Mapping[str, Any] | None = None


class MigrationExecutor(Protocol):
    """Boundary implemented by a service-specific migration adapter."""

    def inspect(self, action: Mapping[str, Any]) -> ExecutionReceipt | None:
        """Read target state without queuing or mutating work."""

    def execute(self, action: Mapping[str, Any]) -> ExecutionReceipt:
        """Execute one plan action."""


def _read_object(path: Path, *, artifact: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(
            f"Unable to read the migration {artifact} artifact.",
            exit_code=EXIT_INPUT_ERROR,
        ) from exc
    if not isinstance(value, dict):
        raise MigrationError(
            f"Migration {artifact} artifact must be a JSON object.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    return value


def load_plan(path: Path) -> dict[str, Any]:
    """Load and authenticate one canonical plan artifact."""

    payload = _read_object(path, artifact="plan")
    validate_contract("plan", payload)
    plan = MigrationPlan(
        id=str(payload["id"]),
        service=str(payload["service"]),
        actions=tuple(payload["actions"]),
    )
    if not plan.verify(payload):
        raise MigrationError(
            "Migration plan digest verification failed.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    _validated_actions(payload)
    return payload


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _redact_value(item)
            for key, item in value.items()
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    if not isinstance(value, str):
        return value
    if _BEARER_VALUE.search(value):
        return "[redacted]"
    if not value.lower().startswith(("http://", "https://")):
        return value
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if host is None:
            return "[redacted-url]"
        netloc = host
        if ":" in host and not host.startswith("["):
            netloc = f"[{host}]"
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except ValueError:
        return "[redacted-url]"


def redact_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return a recursively credential-free configuration snapshot."""

    redacted = _redact_value(config)
    if not isinstance(redacted, dict):  # pragma: no cover - mapping contract
        raise AssertionError("redacted mapping unexpectedly changed type")
    assert_artifact_safe(redacted)
    return redacted


def _atomic_write_new(path: Path, data: str) -> None:
    """Atomically install a new file while refusing every overwrite race."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, path)
    finally:
        try:
            temporary_path.unlink()
        except OSError:
            pass


def _serialized(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _unsafe_lock_file(info: os.stat_result) -> bool:
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(info, "st_file_attributes", 0)
    return not stat.S_ISREG(info.st_mode) or bool(attributes & reparse_flag)


class _UnsafeLeaseError(OSError):
    """Raised when the lease path cannot be opened without following a link."""


def _open_lock_file(path: Path) -> BinaryIO:
    try:
        existing = os.lstat(path)
    except FileNotFoundError:
        pass
    else:
        if _unsafe_lock_file(existing):
            raise _UnsafeLeaseError
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        opened = os.fstat(descriptor)
        linked = os.lstat(path)
        if _unsafe_lock_file(opened) or _unsafe_lock_file(linked):
            raise _UnsafeLeaseError
        if not os.path.samestat(opened, linked):
            raise _UnsafeLeaseError
        return os.fdopen(descriptor, "r+b")
    except BaseException:
        os.close(descriptor)
        raise


def _lock(stream: BinaryIO) -> None:
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"\0")
        stream.flush()
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(  # type: ignore[attr-defined]
            stream.fileno(), msvcrt.LK_NBLCK, 1  # type: ignore[attr-defined]
        )
    else:  # pragma: no cover - exercised by Linux CI
        import fcntl

        fcntl.flock(  # type: ignore[attr-defined]
            stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB  # type: ignore[attr-defined]
        )


def _unlock(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(  # type: ignore[attr-defined]
            stream.fileno(), msvcrt.LK_UNLCK, 1  # type: ignore[attr-defined]
        )
    else:  # pragma: no cover - exercised by Linux CI
        import fcntl

        fcntl.flock(  # type: ignore[attr-defined]
            stream.fileno(), fcntl.LOCK_UN  # type: ignore[attr-defined]
        )


class RunStore:
    """Validate and durably persist one migration-run artifact."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def lease(self) -> Iterator[None]:
        """Prevent concurrent processes from inspecting and executing this run."""

        lock_path = self.path.with_name(f".{self.path.name}.lock")
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            stream = _open_lock_file(lock_path)
        except _UnsafeLeaseError as exc:
            raise MigrationError(
                "Migration run lease path is unsafe; no actions were queued.",
                exit_code=EXIT_APPLY_REFUSED,
            ) from exc
        except OSError as exc:
            raise MigrationError(
                "Unable to create the migration run lease.",
                exit_code=EXIT_INPUT_ERROR,
            ) from exc
        try:
            try:
                _lock(stream)
            except OSError as exc:
                raise MigrationError(
                    "Migration run is already active; no actions were queued.",
                    exit_code=EXIT_APPLY_REFUSED,
                ) from exc
            try:
                yield
            finally:
                _unlock(stream)
        finally:
            stream.close()

    def create(self, payload: Mapping[str, Any]) -> None:
        validate_contract("run", payload)
        try:
            _atomic_write_new(self.path, _serialized(payload))
        except FileExistsError as exc:
            raise MigrationError(
                "Migration run artifact already exists; resume it instead.",
                exit_code=EXIT_APPLY_REFUSED,
            ) from exc
        except OSError as exc:
            raise MigrationError(
                "Unable to create the migration run artifact.",
                exit_code=EXIT_INPUT_ERROR,
            ) from exc

    def save(self, payload: Mapping[str, Any]) -> None:
        validate_contract("run", payload)
        try:
            atomic_write_text(self.path, _serialized(payload))
        except OSError as exc:
            raise MigrationError(
                "Unable to update the migration run artifact.",
                exit_code=EXIT_INPUT_ERROR,
            ) from exc

    def load(self) -> dict[str, Any]:
        payload = _read_object(self.path, artifact="run")
        validate_contract("run", payload)
        payload.setdefault("config", {})
        return payload


def _validated_actions(plan: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    actions: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for raw in plan.get("actions", []):
        if not isinstance(raw, dict):
            raise MigrationError(
                "Migration plan contains an invalid action.",
                exit_code=EXIT_VALIDATION_ERROR,
            )
        action_id = raw.get("id")
        write = raw.get("write", True)
        idempotent = raw.get("idempotent", False)
        if (
            not isinstance(action_id, str)
            or not action_id
            or action_id in identifiers
            or not isinstance(write, bool)
            or not isinstance(idempotent, bool)
        ):
            raise MigrationError(
                "Migration plan action identities or safety flags are invalid.",
                exit_code=EXIT_VALIDATION_ERROR,
            )
        identifiers.add(action_id)
        actions.append(raw)
    return tuple(actions)


def _checkpoint(action: Mapping[str, Any], status: str) -> dict[str, Any]:
    return {
        "action_id": action["id"],
        "write": action.get("write", True),
        "idempotent": action.get("idempotent", False),
        "status": status,
    }


def _replace_checkpoint(
    run: dict[str, Any], action: Mapping[str, Any], checkpoint: dict[str, Any]
) -> None:
    checkpoints = list(run["checkpoints"])
    for index, current in enumerate(checkpoints):
        if current.get("action_id") == action["id"]:
            checkpoints[index] = checkpoint
            break
    else:
        checkpoints.append(checkpoint)
    run["checkpoints"] = checkpoints


def _complete(
    run: dict[str, Any],
    action: Mapping[str, Any],
    receipt: ExecutionReceipt,
) -> None:
    evidence = dict(receipt.evidence or {})
    assert_artifact_safe(evidence)
    complete = _checkpoint(action, "succeeded")
    if receipt.job_id is not None:
        if not isinstance(receipt.job_id, str) or not _JOB_ID.fullmatch(receipt.job_id):
            raise MigrationError(
                "Migration executor returned an invalid job identity.",
                exit_code=EXIT_VALIDATION_ERROR,
            )
        assert_artifact_safe(receipt.job_id)
        complete["job_id"] = receipt.job_id
        if receipt.job_id not in run["job_ids"]:
            run["job_ids"] = [*run["job_ids"], receipt.job_id]
    if evidence:
        complete["evidence"] = evidence
    _replace_checkpoint(run, action, complete)


def _bound(
    plan: Mapping[str, Any],
    run: Mapping[str, Any],
    config: Mapping[str, Any],
) -> None:
    if (
        run.get("plan_id") != plan.get("id")
        or run.get("plan_digest") != plan.get("plan_digest")
        or run.get("service") != plan.get("service")
        or run.get("config") != redact_config(config)
    ):
        raise MigrationError(
            "Migration run does not match the authenticated plan.",
            exit_code=EXIT_VALIDATION_ERROR,
        )


def _validated_checkpoints(
    actions: tuple[dict[str, Any], ...], run: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    checkpoints: dict[str, dict[str, Any]] = {}
    represented_job_ids: list[str] = []
    for index, raw in enumerate(run["checkpoints"]):
        if not isinstance(raw, dict):  # schema permits objects only; defensive boundary
            raise MigrationError(
                "Migration run checkpoint state is invalid.",
                exit_code=EXIT_VALIDATION_ERROR,
            )
        if index >= len(actions):
            raise MigrationError(
                "Migration run checkpoint state is invalid.",
                exit_code=EXIT_VALIDATION_ERROR,
            )
        action = actions[index]
        action_id = raw.get("action_id")
        if not isinstance(action_id, str):
            raise MigrationError(
                "Migration run checkpoint state is invalid.",
                exit_code=EXIT_VALIDATION_ERROR,
            )
        status = raw.get("status")
        if (
            action_id != action["id"]
            or action_id in checkpoints
            or status not in {"started", "succeeded"}
            or raw.get("write") is not action.get("write", True)
            or raw.get("idempotent") is not action.get("idempotent", False)
            or (status == "started" and index != len(run["checkpoints"]) - 1)
            or (status == "started" and "job_id" in raw)
        ):
            raise MigrationError(
                "Migration run checkpoint state is invalid.",
                exit_code=EXIT_VALIDATION_ERROR,
            )
        checkpoints[action_id] = raw
        job_id = raw.get("job_id")
        if job_id is not None:
            if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
                raise MigrationError(
                    "Migration run checkpoint state is invalid.",
                    exit_code=EXIT_VALIDATION_ERROR,
                )
            assert_artifact_safe(job_id)
            if job_id not in represented_job_ids:
                represented_job_ids.append(job_id)

    outcome = run["outcome"]
    statuses = [checkpoint["status"] for checkpoint in checkpoints.values()]
    if outcome == "pending" and statuses:
        raise MigrationError(
            "Pending migration run has inconsistent checkpoint evidence.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    if outcome == "running" and not statuses:
        raise MigrationError(
            "Running migration run has inconsistent checkpoint evidence.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    if outcome == "partial" and (not statuses or statuses[-1] != "started"):
        raise MigrationError(
            "Partial migration run has inconsistent checkpoint evidence.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    if outcome == "succeeded" and (
        len(checkpoints) != len(actions) or any(status != "succeeded" for status in statuses)
    ):
        raise MigrationError(
            "Succeeded migration run has incomplete checkpoint evidence.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    if outcome not in {"pending", "running", "partial", "succeeded"}:
        raise MigrationError(
            "Migration run outcome cannot be resumed safely.",
            exit_code=EXIT_APPLY_REFUSED,
        )
    if run["job_ids"] != represented_job_ids:
        raise MigrationError(
            "Migration run job identity evidence is inconsistent.",
            exit_code=EXIT_VALIDATION_ERROR,
        )
    return checkpoints


def _execute_one(
    *,
    run: dict[str, Any],
    action: Mapping[str, Any],
    executor: MigrationExecutor,
    store: RunStore,
) -> None:
    _replace_checkpoint(run, action, _checkpoint(action, "started"))
    run["outcome"] = "running"
    store.save(run)
    try:
        receipt = executor.execute(dict(action))
        completed_run = deepcopy(run)
        _complete(completed_run, action, receipt)
        store.save(completed_run)
        run.clear()
        run.update(completed_run)
    except InterruptedError as exc:
        run["outcome"] = "partial"
        store.save(run)
        raise MigrationError(
            "Migration was interrupted; inspect and resume the run.",
            exit_code=EXIT_PARTIAL,
        ) from exc
    except MigrationError as exc:
        run["outcome"] = "partial"
        store.save(run)
        safe_code = (
            exc.exit_code
            if exc.exit_code
            in {EXIT_APPLY_REFUSED, EXIT_PARTIAL, EXIT_REMOTE_ERROR, EXIT_UNAVAILABLE}
            else EXIT_REMOTE_ERROR
        )
        raise MigrationError(
            "Migration action failed; inspect and resume the run.",
            exit_code=safe_code,
        ) from exc
    except Exception as exc:
        run["outcome"] = "partial"
        store.save(run)
        raise MigrationError(
            "Migration action status is uncertain; inspect and resume the run.",
            exit_code=EXIT_REMOTE_ERROR,
        ) from exc


def start_run(
    plan_path: Path,
    run_path: Path,
    executor: MigrationExecutor,
    *,
    config: Mapping[str, Any] | None = None,
    acknowledged: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Create and execute a new run, checkpointing before every target write."""

    plan = load_plan(plan_path)
    actions = _validated_actions(plan)
    if any(action.get("write", True) for action in actions) and not acknowledged:
        raise MigrationError(
            "Explicit acknowledgement is required before migration writes.",
            exit_code=EXIT_APPLY_REFUSED,
        )
    safety_mode = (
        SafetyMode.APPLY
        if any(action.get("write", True) for action in actions)
        else SafetyMode.READ_ONLY
    )
    run = MigrationRun(
        id=run_id or f"{plan['id']}-run",
        plan_id=plan["id"],
        plan_digest=plan["plan_digest"],
        service=plan["service"],
        safety_mode=safety_mode,
        config=redact_config(config or {}),
    ).to_dict()
    store = RunStore(run_path)
    with store.lease():
        store.create(run)
        for action in actions:
            _execute_one(run=run, action=action, executor=executor, store=store)
        run["outcome"] = "succeeded"
        store.save(run)
    return run


def resume_run(
    plan_path: Path,
    run_path: Path,
    executor: MigrationExecutor,
    *,
    config: Mapping[str, Any] | None = None,
    acknowledged: bool = False,
) -> dict[str, Any]:
    """Resume safely without replaying completed target writes."""

    plan = load_plan(plan_path)
    actions = _validated_actions(plan)
    store = RunStore(run_path)
    with store.lease():
        run = store.load()
        _bound(plan, run, config if config is not None else {})
        checkpoints = _validated_checkpoints(actions, run)

        if run["outcome"] == "succeeded":
            if any(
                action.get("write", True) and not action.get("idempotent", False)
                for action in actions
            ):
                raise MigrationError(
                    "Run already applied non-idempotent work; no actions were replayed.",
                    exit_code=EXIT_APPLY_REFUSED,
                )
            return run

        for action in actions:
            current = checkpoints.get(action["id"])
            if current and current.get("status") == "succeeded":
                continue

            write = action.get("write", True)
            if current and current.get("status") == "started":
                try:
                    observed = executor.inspect(dict(action))
                except Exception as exc:
                    raise MigrationError(
                        "Unable to inspect the incomplete migration action safely.",
                        exit_code=EXIT_REMOTE_ERROR,
                    ) from exc
                if observed is not None:
                    try:
                        _complete(run, action, observed)
                    except Exception as exc:
                        raise MigrationError(
                            "Migration inspection returned unsafe evidence.",
                            exit_code=EXIT_REMOTE_ERROR,
                        ) from exc
                    store.save(run)
                    continue
                if write and not action.get("idempotent", False):
                    raise MigrationError(
                        "Incomplete non-idempotent work has uncertain target state; "
                        "no action was replayed.",
                        exit_code=EXIT_APPLY_REFUSED,
                    )

            if write and not acknowledged:
                raise MigrationError(
                    "Explicit acknowledgement is required before migration writes.",
                    exit_code=EXIT_APPLY_REFUSED,
                )
            _execute_one(run=run, action=action, executor=executor, store=store)
            checkpoints[action["id"]] = next(
                item
                for item in run["checkpoints"]
                if item["action_id"] == action["id"]
            )

        run["outcome"] = "succeeded"
        store.save(run)
        return run
