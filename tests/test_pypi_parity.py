"""Tests for retry-safe exact-version PyPI preflight."""

from __future__ import annotations

import hashlib
import importlib.util
import urllib.error
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_pypi_parity", REPO_ROOT / "scripts" / "check_pypi_parity.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dist(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    dist = tmp_path / "dist"
    dist.mkdir()
    files = {
        "honua_migrate-0.7.1-py3-none-any.whl": b"wheel",
        "honua_migrate-0.7.1.tar.gz": b"sdist",
    }
    for name, payload in files.items():
        (dist / name).write_bytes(payload)
    return dist, {
        name: hashlib.sha256(payload).hexdigest()
        for name, payload in files.items()
    }


def _release(hashes: dict[str, str]) -> dict:
    return {
        "info": {"name": "honua-migrate", "version": "0.7.1"},
        "urls": [
            {"filename": name, "digests": {"sha256": digest}}
            for name, digest in hashes.items()
        ],
    }


def test_missing_version_requires_publish(tmp_path: Path) -> None:
    module = _module()
    dist, _ = _dist(tmp_path)

    assert module.publish_required(dist, REPO_ROOT, lambda _project, _version: None)


def test_pypi_404_is_the_only_missing_version_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()

    def missing(_request, timeout: int):
        assert timeout == 30
        raise urllib.error.HTTPError("https://pypi.invalid", 404, "missing", {}, None)

    monkeypatch.setattr(module.urllib.request, "urlopen", missing)
    assert module.fetch_pypi_release("honua-migrate", "0.7.1") is None


def test_exact_existing_version_is_retry_safe(tmp_path: Path) -> None:
    module = _module()
    dist, hashes = _dist(tmp_path)

    assert not module.publish_required(
        dist, REPO_ROOT, lambda _project, _version: _release(hashes)
    )


@pytest.mark.parametrize("change", ["digest", "missing", "extra"])
def test_existing_version_must_have_exact_file_parity(
    tmp_path: Path, change: str
) -> None:
    module = _module()
    dist, hashes = _dist(tmp_path)
    changed = dict(hashes)
    if change == "digest":
        changed[next(iter(changed))] = "0" * 64
    elif change == "missing":
        changed.pop(next(iter(changed)))
    else:
        changed["unexpected.txt"] = "0" * 64

    with pytest.raises(module.ParityError, match="differs from the build"):
        module.publish_required(
            dist, REPO_ROOT, lambda _project, _version: _release(changed)
        )
