"""Smoke tests for the EsriFootprint v0.1 schema and its canonical sample."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "esri-footprint-v0.1.json"
PACKAGED_SCHEMA_PATH = (
    REPO_ROOT
    / "src"
    / "honua_esri_assess"
    / "schemas"
    / "esri-footprint-v0.1.json"
)
SAMPLE_PATH = REPO_ROOT / "docs" / "samples" / "esri-footprint.sample.json"

LOCKED_DIAGNOSTIC_CODES_V01 = frozenset(
    {
        "rate-limited",
        "partial-coverage",
        "missing-permission",
        "unresolved-reference",
        "unsupported-item-type",
        "redacted-field",
    }
)
UTC_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("date-time")
def _is_utc_rfc3339(value: object) -> bool:
    if not isinstance(value, str):
        return True
    if not UTC_RFC3339_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() == timezone.utc.utcoffset(None)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def schema() -> dict:
    return _load_json(SCHEMA_PATH)


@pytest.fixture(scope="module")
def sample() -> dict:
    return _load_json(SAMPLE_PATH)


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def _valid_artifact_for_kind(sample: dict, source_kind: str) -> dict:
    artifact = copy.deepcopy(sample)
    if source_kind == "arcgis-online":
        return artifact
    if source_kind == "arcgis-server":
        artifact["source"] = {
            "kind": "arcgis-server",
            "locator": "https://gis.example.com/arcgis/rest/services",
            "capturedAt": "2026-05-22T14:02:11Z",
        }
        artifact.pop("portal", None)
        artifact["server"] = {
            "folders": ["Utilities", "Planning"],
            "serviceCounts": {"MapServer": 1, "FeatureServer": 1},
            "version": "11.2",
        }
        artifact["inventory"] = [_server_service_item()]
        artifact["counts"] = {
            "items": {
                "portal-item": 0,
                "server-service": 1,
                "filegdb-feature-class": 0,
            },
            "layers": 4,
            "featureClasses": 0,
        }
        return artifact
    if source_kind == "filegdb":
        artifact["source"] = {
            "kind": "filegdb",
            "locator": "sha256:" + "0" * 64,
            "capturedAt": "2026-05-22T14:02:11Z",
        }
        artifact.pop("portal", None)
        artifact["filegdb"] = {
            "pathHash": "sha256:" + "0" * 64,
            "featureClassCount": 1,
            "version": "10.x",
        }
        artifact["inventory"] = [_filegdb_feature_class_item()]
        artifact["counts"] = {
            "items": {
                "portal-item": 0,
                "server-service": 0,
                "filegdb-feature-class": 1,
            },
            "layers": 0,
            "featureClasses": 1,
        }
        return artifact
    raise ValueError(f"Unsupported source kind for test fixture: {source_kind}")


def _server_service_item() -> dict:
    return {
        "kind": "server-service",
        "serviceUrl": "https://gis.example.com/arcgis/rest/services/Utilities/Water/MapServer",
        "serviceType": "MapServer",
        "folder": "Utilities",
        "layerCount": 4,
        "geometryType": "esriGeometryPolyline",
        "extent": {
            "bbox": [-122.5, 47.4, -122.2, 47.8],
            "crs": {"wkid": 4326},
        },
        "sr": {"wkid": 4326},
    }


def _filegdb_feature_class_item() -> dict:
    return {
        "kind": "filegdb-feature-class",
        "name": "Parcels",
        "geometryType": "esriGeometryPolygon",
        "sr": {"wkid": 2926},
        "featureCount": 12345,
        "fields": [
            {"name": "OBJECTID", "type": "esriFieldTypeOID", "nullable": False},
            {"name": "PARCEL_ID", "type": "esriFieldTypeString", "nullable": False},
        ],
    }


def _facet_for_name(sample: dict, facet_name: str) -> dict:
    if facet_name == "portal":
        return copy.deepcopy(sample["portal"])
    if facet_name == "server":
        return {"folders": [], "serviceCounts": {}}
    if facet_name == "filegdb":
        return {"pathHash": "sha256:" + "0" * 64, "featureClassCount": 0}
    raise ValueError(f"Unsupported facet for test fixture: {facet_name}")


def _inventory_item_for_kind(sample: dict, item_kind: str) -> dict:
    if item_kind == "portal-item":
        return copy.deepcopy(sample["inventory"][0])
    if item_kind == "server-service":
        return _server_service_item()
    if item_kind == "filegdb-feature-class":
        return _filegdb_feature_class_item()
    raise ValueError(f"Unsupported item kind for test fixture: {item_kind}")


def test_schema_id_carries_full_semver(schema: dict) -> None:
    assert schema["$id"] == (
        "https://schemas.honua.io/esri-footprint/v0.1.0/esri-footprint.json"
    )


def test_schema_uses_draft_2020_12(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_packaged_schema_matches_published_schema(schema: dict) -> None:
    assert _load_json(PACKAGED_SCHEMA_PATH) == schema


def test_canonical_sample_validates(validator: Draft202012Validator, sample: dict) -> None:
    errors = sorted(validator.iter_errors(sample), key=lambda e: list(e.path))
    assert errors == [], "\n".join(
        f"{list(err.path)}: {err.message}" for err in errors
    )


def test_sample_schema_version_is_v01(sample: dict) -> None:
    assert sample["schemaVersion"] == "v0.1"


def test_sample_diagnostic_codes_are_in_locked_enum(sample: dict) -> None:
    codes = {entry["code"] for entry in sample["diagnostics"]}
    unknown = codes - LOCKED_DIAGNOSTIC_CODES_V01
    assert not unknown, f"Sample uses diagnostic codes outside v0.1 vocabulary: {unknown}"


def test_schema_diagnostic_enum_matches_locked_vocabulary(schema: dict) -> None:
    schema_codes = set(schema["$defs"]["Diagnostic"]["properties"]["code"]["enum"])
    assert schema_codes == LOCKED_DIAGNOSTIC_CODES_V01


def test_top_level_is_closed(schema: dict) -> None:
    assert schema["additionalProperties"] is False


def test_server_service_variant_validates(validator: Draft202012Validator, sample: dict) -> None:
    artifact = _valid_artifact_for_kind(sample, "arcgis-server")
    errors = sorted(validator.iter_errors(artifact), key=lambda e: list(e.path))
    assert errors == [], "\n".join(
        f"{list(err.path)}: {err.message}" for err in errors
    )


def test_filegdb_feature_class_variant_validates(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = _valid_artifact_for_kind(sample, "filegdb")
    errors = sorted(validator.iter_errors(artifact), key=lambda e: list(e.path))
    assert errors == [], "\n".join(
        f"{list(err.path)}: {err.message}" for err in errors
    )


def test_unknown_diagnostic_code_is_rejected(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["diagnostics"].append(
        {
            "code": "made-up-code",
            "severity": "warn",
            "message": "should be rejected",
            "scope": "arcgis-online",
        }
    )
    assert not validator.is_valid(artifact)


def test_unknown_top_level_key_is_rejected(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["telemetry"] = {"sent": True}
    assert not validator.is_valid(artifact)


def test_spatial_reference_requires_at_least_one_identifier(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["inventory"][0]["extent"]["crs"] = {}
    assert not validator.is_valid(artifact)


@pytest.mark.parametrize(
    ("source_kind", "required_facet"),
    [
        ("arcgis-online", "portal"),
        ("arcgis-server", "server"),
        ("filegdb", "filegdb"),
    ],
)
def test_source_kind_requires_matching_facet(
    validator: Draft202012Validator,
    sample: dict,
    source_kind: str,
    required_facet: str,
) -> None:
    artifact = _valid_artifact_for_kind(sample, source_kind)
    artifact.pop(required_facet)
    assert not validator.is_valid(artifact)


@pytest.mark.parametrize(
    ("source_kind", "sibling_facet"),
    [
        ("arcgis-online", "server"),
        ("arcgis-online", "filegdb"),
        ("arcgis-server", "portal"),
        ("arcgis-server", "filegdb"),
        ("filegdb", "portal"),
        ("filegdb", "server"),
    ],
)
def test_source_kind_rejects_sibling_facets(
    validator: Draft202012Validator,
    sample: dict,
    source_kind: str,
    sibling_facet: str,
) -> None:
    artifact = _valid_artifact_for_kind(sample, source_kind)
    artifact[sibling_facet] = _facet_for_name(sample, sibling_facet)
    assert not validator.is_valid(artifact)


@pytest.mark.parametrize(
    ("source_kind", "inventory_kind"),
    [
        ("arcgis-online", "server-service"),
        ("arcgis-online", "filegdb-feature-class"),
        ("arcgis-server", "portal-item"),
        ("arcgis-server", "filegdb-feature-class"),
        ("filegdb", "portal-item"),
        ("filegdb", "server-service"),
    ],
)
def test_source_kind_rejects_mismatched_inventory_variants(
    validator: Draft202012Validator,
    sample: dict,
    source_kind: str,
    inventory_kind: str,
) -> None:
    artifact = _valid_artifact_for_kind(sample, source_kind)
    artifact["inventory"] = [_inventory_item_for_kind(sample, inventory_kind)]
    assert not validator.is_valid(artifact)


@pytest.mark.parametrize(
    ("source_kind", "locator"),
    [
        ("arcgis-online", "https://example.maps.arcgis.com/0123ABCDEF456789"),
        ("arcgis-online", "C:/Users/Alice/customer.gdb"),
        ("arcgis-online", r"C:\Users\Alice\customer.gdb"),
        ("arcgis-online", "token=secret"),
        ("arcgis-online", "user:pass@example.maps.arcgis.com/0123ABCDEF456789"),
        ("arcgis-online", "example.maps.arcgis.com/0123ABCDEF456789?token=secret"),
        ("arcgis-online", "example.maps.arcgis.com/0123ABCDEF456789#fragment"),
        (
            "arcgis-server",
            "https://user:pass@gis.example.com/arcgis/rest/services",
        ),
        ("arcgis-server", "https://gis.example.com/arcgis/rest/services?token=secret"),
        ("arcgis-server", "https://gis.example.com/arcgis/rest/services#fragment"),
        ("filegdb", "C:/data/parcels.gdb"),
    ],
)
def test_source_locator_rejects_unsafe_values(
    validator: Draft202012Validator,
    sample: dict,
    source_kind: str,
    locator: str,
) -> None:
    artifact = _valid_artifact_for_kind(sample, source_kind)
    artifact["source"]["locator"] = locator
    assert not validator.is_valid(artifact)


def test_server_service_url_rejects_query_string(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["source"] = {
        "kind": "arcgis-server",
        "locator": "https://gis.example.com/arcgis/rest/services",
        "capturedAt": "2026-05-22T14:02:11Z",
    }
    artifact.pop("portal", None)
    artifact["server"] = {
        "folders": [],
        "serviceCounts": {"MapServer": 1},
    }
    artifact["inventory"] = [
        {
            "kind": "server-service",
            "serviceUrl": "https://gis.example.com/arcgis/rest/services/Water/MapServer?token=secret",
            "serviceType": "MapServer",
            "folder": "",
            "layerCount": 1,
        }
    ]
    artifact["counts"] = {
        "items": {"portal-item": 0, "server-service": 1, "filegdb-feature-class": 0},
        "layers": 1,
        "featureClasses": 0,
    }
    assert not validator.is_valid(artifact)


def test_server_service_url_rejects_userinfo(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["source"] = {
        "kind": "arcgis-server",
        "locator": "https://gis.example.com/arcgis/rest/services",
        "capturedAt": "2026-05-22T14:02:11Z",
    }
    artifact.pop("portal", None)
    artifact["server"] = {
        "folders": [],
        "serviceCounts": {"MapServer": 1},
    }
    artifact["inventory"] = [
        {
            "kind": "server-service",
            "serviceUrl": "https://user:pass@gis.example.com/arcgis/rest/services/Water/MapServer",
            "serviceType": "MapServer",
            "folder": "",
            "layerCount": 1,
        }
    ]
    artifact["counts"] = {
        "items": {"portal-item": 0, "server-service": 1, "filegdb-feature-class": 0},
        "layers": 1,
        "featureClasses": 0,
    }
    assert not validator.is_valid(artifact)


@pytest.mark.parametrize(
    "org_url",
    [
        "https://user:pass@example.maps.arcgis.com",
        "https://example.maps.arcgis.com?token=secret",
        "https://example.maps.arcgis.com/#fragment",
    ],
)
def test_portal_org_url_rejects_secret_bearing_urls(
    validator: Draft202012Validator, sample: dict, org_url: str
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["portal"]["orgUrl"] = org_url
    assert not validator.is_valid(artifact)


@pytest.mark.parametrize(
    ("source_kind", "map_path", "unsafe_key"),
    [
        (
            "arcgis-online",
            ("portal", "itemCounts"),
            "https://collector.example.com/hook?token=secret",
        ),
        ("arcgis-online", ("portal", "itemCounts"), "https://collector.example.com/hook"),
        ("arcgis-online", ("portal", "itemCounts"), "token=secret"),
        (
            "arcgis-server",
            ("server", "serviceCounts"),
            "https://collector.example.com/hook?token=secret",
        ),
        ("arcgis-server", ("server", "serviceCounts"), "https://collector.example.com/hook"),
        ("arcgis-server", ("server", "serviceCounts"), "token=secret"),
    ],
)
def test_count_maps_reject_url_or_token_like_keys(
    validator: Draft202012Validator,
    sample: dict,
    source_kind: str,
    map_path: tuple[str, ...],
    unsafe_key: str,
) -> None:
    artifact = _valid_artifact_for_kind(sample, source_kind)
    target = artifact
    for segment in map_path:
        target = target[segment]
    target[unsafe_key] = 1
    assert not validator.is_valid(artifact)


@pytest.mark.parametrize(
    ("path", "key", "value"),
    [
        (("portal",), "token", "secret"),
        (("portal",), "callbackUrl", "https://collector.example.com/hook"),
        (("inventory", 0), "token", "secret"),
        (("inventory", 0), "callbackUrl", "https://collector.example.com/hook"),
    ],
)
def test_schema_rejects_extension_points_that_can_smuggle_secrets_or_telemetry(
    validator: Draft202012Validator,
    sample: dict,
    path: tuple[str | int, ...],
    key: str,
    value: str,
) -> None:
    artifact = copy.deepcopy(sample)
    target = artifact
    for segment in path:
        target = target[segment]
    target[key] = value
    assert not validator.is_valid(artifact)


@pytest.mark.parametrize(
    "path",
    [
        ("generatedAt",),
        ("source", "capturedAt"),
        ("inventory", 0, "modified"),
    ],
)
@pytest.mark.parametrize(
    "invalid_timestamp",
    [
        "not-a-date",
        "2026-13-22T14:08:33Z",
        "2026-02-30T14:08:33Z",
        "2026-05-22T25:08:33Z",
        "2026-05-22T14:08:33+00:00",
    ],
)
def test_rfc3339_timestamps_reject_invalid_values(
    validator: Draft202012Validator,
    sample: dict,
    path: tuple[str | int, ...],
    invalid_timestamp: str,
) -> None:
    artifact = copy.deepcopy(sample)
    target = artifact
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = invalid_timestamp
    assert not validator.is_valid(artifact)
