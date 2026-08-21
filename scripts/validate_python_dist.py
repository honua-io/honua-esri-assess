#!/usr/bin/env python3
"""Validate honua-migrate wheel/sdist metadata, contents, and reproducibility."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
import sys
import tarfile
import tomllib
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

PROJECT = "honua-migrate"
NORMALIZED_PROJECT = "honua_migrate"
REPOSITORY = "https://github.com/honua-io/honua-migrate"
SCRIPTS = {
    "honua-migrate": "honua_migrate.cli:main",
    "honua-esri-assess": "honua_esri_assess.cli:main",
}
_FORBIDDEN_ASSESSMENT_HOSTS = re.compile(
    rb"https?://[a-z0-9.\-]*(honua\.io|honua-sdk|telemetry|analytics)",
    re.IGNORECASE,
)
_ALLOWED_ASSESSMENT_URLS = {
    b"https://honua.io",
    b"https://github.com/honua-io/honua-migrate",
}
_PRIVATE_KEY = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")


class ValidationError(ValueError):
    """A distribution violated the publication contract."""


def project_version(repo_root: Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as fh:
        project = tomllib.load(fh)["project"]
    if project.get("name") != PROJECT:
        raise ValidationError(
            f"Expected project name {PROJECT!r}, found {project.get('name')!r}."
        )
    return str(project["version"])


def _safe_archive_path(name: str) -> PurePosixPath:
    if "\\" in name:
        raise ValidationError(f"Archive member uses a backslash: {name!r}.")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValidationError(f"Unsafe archive member path: {name!r}.")
    return path


def _single(paths: list[Path], label: str) -> Path:
    if len(paths) != 1:
        raise ValidationError(f"Expected exactly one {label}, found {len(paths)}.")
    return paths[0]


def _entry_points(text: str) -> dict[str, str]:
    section: str | None = None
    scripts: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "console_scripts" and "=" in line:
            name, target = line.split("=", 1)
            scripts[name.strip()] = target.strip()
    return scripts


def _validate_record(wheel: zipfile.ZipFile, names: set[str], prefix: str) -> None:
    record_name = f"{prefix}RECORD"
    rows = list(csv.reader(io.StringIO(wheel.read(record_name).decode("utf-8"))))
    recorded = {row[0] for row in rows}
    if recorded != names:
        missing = sorted(names - recorded)
        extra = sorted(recorded - names)
        raise ValidationError(f"Wheel RECORD drift (missing={missing}, extra={extra}).")
    for name, digest, size in rows:
        if name == record_name:
            if digest or size:
                raise ValidationError("Wheel RECORD must not hash itself.")
            continue
        payload = wheel.read(name)
        expected = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
        if digest != f"sha256={expected.decode('ascii')}":
            raise ValidationError(f"Wheel RECORD digest mismatch for {name}.")
        if size != str(len(payload)):
            raise ValidationError(f"Wheel RECORD size mismatch for {name}.")


def _assessment_telemetry_offenders(name: str, payload: bytes) -> list[str]:
    if "honua_esri_assess/" not in name or not name.endswith(".py"):
        return []
    return [
        f"{name}: {match.group(0).decode('ascii')}"
        for match in _FORBIDDEN_ASSESSMENT_HOSTS.finditer(payload)
        if match.group(0) not in _ALLOWED_ASSESSMENT_URLS
    ]


def _validate_assessment_no_telemetry(wheel: zipfile.ZipFile, names: set[str]) -> None:
    offenders: list[str] = []
    for name in sorted(names):
        offenders.extend(_assessment_telemetry_offenders(name, wheel.read(name)))
    if offenders:
        raise ValidationError(
            "Assessment wheel contains a phone-home host:\n" + "\n".join(offenders)
        )


def _validate_metadata(metadata, version: str, artifact: str) -> None:
    if metadata["Name"] != PROJECT or metadata["Version"] != version:
        raise ValidationError(
            f"{artifact} name/version metadata does not match pyproject."
        )
    if metadata["License-Expression"] != "Apache-2.0":
        raise ValidationError(
            f"{artifact} must declare License-Expression: Apache-2.0."
        )
    if metadata["Requires-Python"] != ">=3.11":
        raise ValidationError(f"{artifact} requires-python metadata drifted.")
    project_urls = set(metadata.get_all("Project-URL", []))
    for expected in (
        f"Homepage, {REPOSITORY}",
        f"Repository, {REPOSITORY}",
        f"Issues, {REPOSITORY}/issues",
    ):
        if expected not in project_urls:
            raise ValidationError(f"{artifact} is missing Project-URL {expected!r}.")
    requirements = metadata.get_all("Requires-Dist", [])
    if any(
        re.match(r"(?i)honua[-_.]sdk(?:\s|\[|[<>=!~;]|$)", item)
        for item in requirements
    ):
        raise ValidationError(
            "honua-sdk must not be auto-installed while it owns the same "
            "honua-migrate console script."
        )


def validate_wheel(path: Path, version: str) -> None:
    expected_name = f"{NORMALIZED_PROJECT}-{version}-py3-none-any.whl"
    if path.name != expected_name:
        raise ValidationError(f"Expected wheel {expected_name!r}, found {path.name!r}.")

    with zipfile.ZipFile(path) as wheel:
        raw_names = wheel.namelist()
        if len(raw_names) != len(set(raw_names)):
            raise ValidationError("Wheel contains duplicate member names.")
        names = set(raw_names)
        for name in names:
            _safe_archive_path(name)
            lowered = name.casefold()
            if (
                "/.git/" in f"/{lowered}/"
                or "__pycache__" in lowered
                or lowered.endswith((".pyc", ".pyo", ".pem", ".key", ".env"))
                or PurePosixPath(lowered).name in {"id_rsa", "id_dsa"}
            ):
                raise ValidationError(f"Forbidden wheel member: {name}.")

        prefix = f"{NORMALIZED_PROJECT}-{version}.dist-info/"
        metadata_name = f"{prefix}METADATA"
        entry_points_name = f"{prefix}entry_points.txt"
        required = {
            metadata_name,
            entry_points_name,
            f"{prefix}RECORD",
            f"{prefix}licenses/LICENSE",
            "honua_migrate/__init__.py",
            "honua_migrate/__main__.py",
            "honua_migrate/cli.py",
            "honua_migrate/code/python/provenance.json",
            "honua_migrate/contract_schemas/v1/run.schema.json",
            "honua_esri_assess/__init__.py",
            "honua_esri_assess/cli.py",
            "honua_esri_assess/py.typed",
            "honua_esri_assess/schemas/esri-footprint-v0.2.json",
        }
        missing = sorted(required - names)
        if missing:
            raise ValidationError(f"Wheel is missing required files: {missing}.")

        metadata = BytesParser(policy=policy.default).parsebytes(
            wheel.read(metadata_name)
        )
        _validate_metadata(metadata, version, "Wheel")
        scripts = _entry_points(wheel.read(entry_points_name).decode("utf-8"))
        if scripts != SCRIPTS:
            raise ValidationError(f"Unexpected console scripts: {scripts!r}.")

        _validate_record(wheel, names, prefix)
        _validate_assessment_no_telemetry(wheel, names)
        for name in names:
            if _PRIVATE_KEY.search(wheel.read(name)):
                raise ValidationError(f"Private key material found in {name}.")


def validate_sdist(path: Path, version: str) -> None:
    expected_name = f"{NORMALIZED_PROJECT}-{version}.tar.gz"
    if path.name != expected_name:
        raise ValidationError(f"Expected sdist {expected_name!r}, found {path.name!r}.")
    root = f"{NORMALIZED_PROJECT}-{version}"
    required = {
        f"{root}/LICENSE",
        f"{root}/README.md",
        f"{root}/RELEASE.md",
        f"{root}/PKG-INFO",
        f"{root}/docs/console-script-collision.md",
        f"{root}/pyproject.toml",
        f"{root}/scripts/validate_publish_tag.py",
        f"{root}/scripts/validate_python_dist.py",
        f"{root}/src/honua_migrate/cli.py",
        f"{root}/src/honua_esri_assess/cli.py",
    }
    with tarfile.open(path, mode="r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        telemetry_offenders: list[str] = []
        if len(names) != len(members):
            raise ValidationError("sdist contains duplicate member names.")
        for member in members:
            archive_path = _safe_archive_path(member.name)
            if not archive_path.parts or archive_path.parts[0] != root:
                raise ValidationError(f"sdist member escapes the project root: {member.name}.")
            if not (member.isfile() or member.isdir()):
                raise ValidationError(f"sdist contains a link or special file: {member.name}.")
            if member.mode & 0o6000:
                raise ValidationError(f"sdist member has set-id bits: {member.name}.")
            lowered = member.name.casefold()
            if "__pycache__" in lowered or lowered.endswith((".pyc", ".pyo", ".pem", ".key", ".env")):
                raise ValidationError(f"Forbidden sdist member: {member.name}.")
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValidationError(f"Could not read sdist member: {member.name}.")
                payload = extracted.read()
                if _PRIVATE_KEY.search(payload):
                    raise ValidationError(
                        f"Private key material found in {member.name}."
                    )
                telemetry_offenders.extend(
                    _assessment_telemetry_offenders(member.name, payload)
                )
        missing = sorted(required - names)
        if missing:
            raise ValidationError(f"sdist is missing required files: {missing}.")
        if telemetry_offenders:
            raise ValidationError(
                "Assessment sdist contains a phone-home host:\n"
                + "\n".join(telemetry_offenders)
            )
        metadata_member = archive.extractfile(f"{root}/PKG-INFO")
        if metadata_member is None:
            raise ValidationError("Could not read sdist PKG-INFO.")
        metadata = BytesParser(policy=policy.default).parsebytes(
            metadata_member.read()
        )
        _validate_metadata(metadata, version, "sdist")


def distribution_hashes(dist_dir: Path) -> dict[str, str]:
    files = sorted(path for path in dist_dir.iterdir() if path.is_file())
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def validate_distribution(dist_dir: Path, repo_root: Path) -> dict[str, str]:
    version = project_version(repo_root)
    wheel = _single(sorted(dist_dir.glob("*.whl")), "wheel")
    sdist = _single(sorted(dist_dir.glob("*.tar.gz")), "sdist")
    extra = sorted(
        path.name
        for path in dist_dir.iterdir()
        if path.is_file() and path not in {wheel, sdist}
    )
    if extra:
        raise ValidationError(f"Unexpected distribution files: {extra}.")
    validate_wheel(wheel, version)
    validate_sdist(sdist, version)
    return distribution_hashes(dist_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        first = validate_distribution(args.dist, args.repo_root)
        if args.compare is not None:
            second = validate_distribution(args.compare, args.repo_root)
            if first != second:
                raise ValidationError(
                    f"Distribution builds are not byte-identical: {first!r} != {second!r}."
                )
    except (OSError, KeyError, ValidationError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for name, digest in first.items():
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
