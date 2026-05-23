"""Smoke tests for the EsriFootprint v0.1 schema and its canonical sample."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "esri-footprint-v0.1.json"
SAMPLE_PATH = REPO_ROOT / "tests" / "fixtures" / "esri-footprint-sample.json"

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
    return Draft202012Validator(schema)


def test_schema_id_carries_full_semver(schema: dict) -> None:
    assert schema["$id"] == (
        "https://schemas.honua.io/esri-footprint/v0.1.0/esri-footprint.json"
    )


def test_schema_uses_draft_2020_12(schema: dict) -> None:
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


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
    artifact = copy.deepcopy(sample)
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
    artifact["inventory"] = [
        {
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
    ]
    artifact["counts"] = {
        "items": {"portal-item": 0, "server-service": 1, "filegdb-feature-class": 0},
        "layers": 4,
        "featureClasses": 0,
    }
    errors = sorted(validator.iter_errors(artifact), key=lambda e: list(e.path))
    assert errors == [], "\n".join(
        f"{list(err.path)}: {err.message}" for err in errors
    )


def test_filegdb_feature_class_variant_validates(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
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
    artifact["inventory"] = [
        {
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
    ]
    artifact["counts"] = {
        "items": {"portal-item": 0, "server-service": 0, "filegdb-feature-class": 1},
        "layers": 0,
        "featureClasses": 1,
    }
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


def test_arcgis_online_rejects_sibling_facets(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["server"] = {
        "folders": [],
        "serviceCounts": {},
    }
    assert not validator.is_valid(artifact)


def test_arcgis_online_rejects_filegdb_inventory(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["inventory"].append(
        {
            "kind": "filegdb-feature-class",
            "name": "Parcels",
            "geometryType": "esriGeometryPolygon",
            "sr": {"wkid": 4326},
        }
    )
    artifact["counts"]["items"]["filegdb-feature-class"] = 1
    artifact["counts"]["featureClasses"] = 1
    assert not validator.is_valid(artifact)


def test_arcgis_server_rejects_missing_facet(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["source"] = {
        "kind": "arcgis-server",
        "locator": "https://gis.example.com/arcgis/rest/services",
        "capturedAt": "2026-05-22T14:02:11Z",
    }
    artifact.pop("portal", None)
    artifact["inventory"] = []
    artifact["counts"] = {
        "items": {"portal-item": 0, "server-service": 0, "filegdb-feature-class": 0},
        "layers": 0,
        "featureClasses": 0,
    }
    assert not validator.is_valid(artifact)


def test_filegdb_locator_rejects_raw_path(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["source"] = {
        "kind": "filegdb",
        "locator": "C:/data/parcels.gdb",
        "capturedAt": "2026-05-22T14:02:11Z",
    }
    artifact.pop("portal", None)
    artifact["filegdb"] = {
        "pathHash": "sha256:" + "0" * 64,
        "featureClassCount": 0,
    }
    artifact["inventory"] = []
    artifact["counts"] = {
        "items": {"portal-item": 0, "server-service": 0, "filegdb-feature-class": 0},
        "layers": 0,
        "featureClasses": 0,
    }
    assert not validator.is_valid(artifact)


def test_arcgis_server_locator_rejects_userinfo(
    validator: Draft202012Validator, sample: dict
) -> None:
    artifact = copy.deepcopy(sample)
    artifact["source"] = {
        "kind": "arcgis-server",
        "locator": "https://user:pass@gis.example.com/arcgis/rest/services",
        "capturedAt": "2026-05-22T14:02:11Z",
    }
    artifact.pop("portal", None)
    artifact["server"] = {"folders": [], "serviceCounts": {}}
    artifact["inventory"] = []
    artifact["counts"] = {
        "items": {"portal-item": 0, "server-service": 0, "filegdb-feature-class": 0},
        "layers": 0,
        "featureClasses": 0,
    }
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
