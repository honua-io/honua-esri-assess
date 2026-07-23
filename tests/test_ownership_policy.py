"""Documentation contract for migration ownership and deprecation."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "ownership-and-deprecation.md"


def test_readme_links_the_ownership_policy() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "(docs/ownership-and-deprecation.md)" in readme
    assert POLICY_PATH.is_file()


def test_policy_covers_required_surfaces_and_boundaries() -> None:
    policy = POLICY_PATH.read_text(encoding="utf-8")
    normalized_policy = " ".join(policy.split())

    for surface in (
        "Assessment",
        "JavaScript",
        "Python / ArcPy",
        "MAUI",
        "ArcGIS services",
        "GeoServer",
        "Portal content",
        "Reconciliation",
    ):
        assert f"| {surface} |" in policy

    for requirement in (
        "Apache-2.0",
        "ELv2",
        "experimental `honua-mobile` SDK/control library",
        "experimental `honua-collect` end-user application",
        "Collect is not a migration source or runtime dependency",
        "Reconciliation is the separate shared surface below",
        "unified Python content group is reserved but remains a placeholder",
        "independent `@honua/honua-migrate` package",
        "two consecutive `honua-migrate` minor releases",
        "at least 90 days",
        "Removal never depends on usage telemetry",
        "honua-io/honua-migrate",
    ):
        assert requirement in normalized_policy


def test_policy_local_links_resolve_and_avoids_raw_http_shell_examples() -> None:
    policy = POLICY_PATH.read_text(encoding="utf-8")
    link_targets = re.findall(r"\[[^]]+\]\(([^)]+)\)", policy)

    for target in link_targets:
        if target.startswith(("https://", "mailto:", "#")):
            continue
        relative_target = target.split("#", 1)[0]
        assert (POLICY_PATH.parent / relative_target).resolve().exists(), target

    raw_http_shell = "cu" + "rl"
    assert raw_http_shell not in policy.casefold()
