"""Schema-level invariants for the v0.2 EsriFootprint contract."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[2]
V0_1_PATH = REPO_ROOT / "schemas" / "esri-footprint-v0.1.json"
V0_2_PATH = REPO_ROOT / "schemas" / "esri-footprint-v0.2.json"
PACKAGED_V0_2_PATH = (
    REPO_ROOT
    / "src"
    / "honua_esri_assess"
    / "schemas"
    / "esri-footprint-v0.2.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema_v0_2() -> dict:
    return _load(V0_2_PATH)


@pytest.fixture(scope="module")
def validator(schema_v0_2: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema_v0_2)
    return Draft202012Validator(schema_v0_2, format_checker=FormatChecker())


def _v0_2_baseline_portal() -> dict:
    return {
        "schemaVersion": "v0.2",
        "generatedAt": "2026-05-22T14:08:33Z",
        "tool": {"name": "honua-esri-assess", "version": "0.2.0"},
        "source": {
            "kind": "arcgis-online",
            "locator": "example.maps.arcgis.com/0123ABCDEF",
            "capturedAt": "2026-05-22T14:02:11Z",
        },
        "portal": {
            "orgId": "0123ABCDEF",
            "orgUrl": "https://example.maps.arcgis.com",
            "itemCounts": {},
        },
        "inventory": [],
        "counts": {
            "items": {
                "portal-item": 0,
                "server-service": 0,
                "filegdb-feature-class": 0,
            },
            "layers": 0,
            "featureClasses": 0,
        },
        "diagnostics": [],
    }


def test_schema_version_is_v0_2(schema_v0_2: dict) -> None:
    assert schema_v0_2["properties"]["schemaVersion"]["const"] == "v0.2"


def test_schema_v0_2_id_is_v0_2_0(schema_v0_2: dict) -> None:
    assert schema_v0_2["$id"] == (
        "https://schemas.honua.io/esri-footprint/v0.2.0/esri-footprint.json"
    )


def test_packaged_v0_2_matches_canonical_v0_2() -> None:
    assert _load(PACKAGED_V0_2_PATH) == _load(V0_2_PATH)


def test_v0_2_artifact_without_access_validates(
    validator: Draft202012Validator,
) -> None:
    artifact = _v0_2_baseline_portal()
    errors = sorted(validator.iter_errors(artifact), key=lambda e: list(e.path))
    assert errors == []


def test_v0_2_portal_access_rejects_email_field(
    validator: Draft202012Validator,
) -> None:
    artifact = _v0_2_baseline_portal()
    artifact["portal"]["access"] = {
        "users": [
            {
                "username": "alice",
                "status": "active",
                "groupIds": [],
                "email": "alice@example.com",
            }
        ],
        "roles": [],
        "groups": [],
        "itemSharing": [],
    }
    assert not validator.is_valid(artifact)


def test_v0_2_principal_name_rejects_url_like_value(
    validator: Draft202012Validator,
) -> None:
    artifact = _v0_2_baseline_portal()
    artifact["portal"]["access"] = {
        "users": [
            {
                "username": "https://leak.example.com/u?token=secret",
                "status": "active",
                "groupIds": [],
            }
        ],
        "roles": [],
        "groups": [],
        "itemSharing": [],
    }
    assert not validator.is_valid(artifact)


def test_v0_2_service_permission_rejects_url_with_token_query(
    validator: Draft202012Validator,
) -> None:
    artifact = _v0_2_baseline_portal()
    artifact["source"] = {
        "kind": "arcgis-server",
        "locator": "https://gis.example.com/arcgis/rest/services",
        "capturedAt": "2026-05-22T14:02:11Z",
    }
    artifact.pop("portal", None)
    artifact["server"] = {
        "folders": [],
        "serviceCounts": {"MapServer": 1},
        "access": {
            "users": [],
            "roles": [],
            "servicePermissions": [
                {
                    "serviceUrl": "https://gis.example.com/arcgis/rest/services/X/MapServer?token=secret",
                    "principal": "alice",
                    "principalKind": "user",
                    "capabilities": ["Query"],
                }
            ],
        },
    }
    artifact["inventory"] = [
        {
            "kind": "server-service",
            "serviceUrl": "https://gis.example.com/arcgis/rest/services/X/MapServer",
            "serviceType": "MapServer",
            "folder": "",
            "layerCount": 0,
        }
    ]
    artifact["counts"] = {
        "items": {
            "portal-item": 0,
            "server-service": 1,
            "filegdb-feature-class": 0,
        },
        "layers": 0,
        "featureClasses": 0,
    }
    assert not validator.is_valid(artifact)


def test_v0_2_diagnostic_enum_unchanged_from_v0_1() -> None:
    v01 = _load(V0_1_PATH)
    v02 = _load(V0_2_PATH)
    assert set(v01["$defs"]["Diagnostic"]["properties"]["code"]["enum"]) == set(
        v02["$defs"]["Diagnostic"]["properties"]["code"]["enum"]
    )


def test_v0_2_access_facet_is_optional(validator: Draft202012Validator) -> None:
    artifact = _v0_2_baseline_portal()
    # No `access` key on portal at all → still valid.
    assert validator.is_valid(artifact)
    artifact["portal"]["access"] = {
        "users": [],
        "roles": [],
        "groups": [],
        "itemSharing": [],
    }
    assert validator.is_valid(artifact)


def test_v0_2_mapping_recommendation_confidence_enum_is_locked(
    validator: Draft202012Validator, schema_v0_2: dict
) -> None:
    enum = schema_v0_2["$defs"]["HonuaRoleMapping"]["properties"]["confidence"]["enum"]
    assert set(enum) == {"high", "medium", "low"}
    artifact = _v0_2_baseline_portal()
    artifact["portal"]["access"] = {
        "users": [],
        "roles": [],
        "groups": [],
        "itemSharing": [],
        "mappingRecommendation": {
            "honuaRoles": [
                {
                    "esriRoleId": "org_admin",
                    "honuaRole": "admin",
                    "confidence": "very-high",
                    "rationale": "bogus",
                }
            ],
            "oidcRoleClaims": [],
            "facadeAccessPolicies": [],
        },
    }
    assert not validator.is_valid(artifact)


def test_v0_2_user_principal_rejects_password_hash_smuggle(
    validator: Draft202012Validator,
) -> None:
    artifact = _v0_2_baseline_portal()
    artifact["portal"]["access"] = {
        "users": [
            {
                "username": "alice",
                "status": "active",
                "groupIds": [],
                "passwordHash": "deadbeef",
            }
        ],
        "roles": [],
        "groups": [],
        "itemSharing": [],
    }
    assert not validator.is_valid(artifact)


def test_v0_1_artifacts_still_validate_unchanged() -> None:
    """v0.1 keeps shipping alongside v0.2."""

    schema_v01 = _load(V0_1_PATH)
    sample = json.loads(
        (REPO_ROOT / "docs" / "samples" / "esri-footprint.sample.json").read_text(
            encoding="utf-8"
        )
    )
    validator_v01 = Draft202012Validator(schema_v01, format_checker=FormatChecker())
    errors = sorted(validator_v01.iter_errors(sample), key=lambda e: list(e.path))
    assert errors == []
    artifact = copy.deepcopy(sample)
    assert artifact["schemaVersion"] == "v0.1"
