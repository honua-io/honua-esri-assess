"""Tests for the esri-assess-registry -> Honua capability-key crosswalk loader."""

from __future__ import annotations

import json

import pytest

from honua_esri_assess.caps.crosswalk import (
    CrosswalkError,
    bundled_crosswalk_text,
    load_bundled_crosswalk,
    parse_crosswalk,
    parse_crosswalk_text,
)
from honua_esri_assess.verdict.registry import CAPABILITY_REGISTRY

_REGISTRY_KEYS = frozenset(entry.key for entry in CAPABILITY_REGISTRY)


def _valid_payload() -> dict:
    return json.loads(bundled_crosswalk_text())


def test_bundled_crosswalk_loads_and_validates() -> None:
    crosswalk = load_bundled_crosswalk()

    assert crosswalk.schema_version == "capability-keys.v1"
    assert crosswalk.source.startswith("DRAFT-FIXTURE")


def test_bundled_crosswalk_covers_every_registry_key() -> None:
    """The bundled fixture is complete: every registry key has an explicit entry.

    Not a hard requirement (a missing key degrades to "unmapped" at runtime,
    see :meth:`Crosswalk.capability_keys_for`), but the shipped fixture should
    not rely on that fallback.
    """

    crosswalk = load_bundled_crosswalk()

    assert set(crosswalk.mapping) == _REGISTRY_KEYS


def test_capability_keys_for_mapped_entry() -> None:
    crosswalk = load_bundled_crosswalk()

    assert crosswalk.capability_keys_for("feature-service") == ("serve.feature-service",)
    assert crosswalk.capability_keys_for("web-map") == (
        "serve.feature-service",
        "serve.map-service",
    )


def test_capability_keys_for_unmapped_entry_is_empty_tuple() -> None:
    crosswalk = load_bundled_crosswalk()

    assert crosswalk.capability_keys_for("geoprocessing") == ()


def test_capability_keys_for_not_supported_entry_is_none() -> None:
    crosswalk = load_bundled_crosswalk()

    assert crosswalk.capability_keys_for("utility-network") is None
    assert crosswalk.capability_keys_for("parcel-fabric") is None
    assert crosswalk.capability_keys_for("lrs") is None


def test_capability_keys_for_key_absent_from_document_is_empty_tuple() -> None:
    """A registry key the crosswalk document omits never silently disappears."""

    crosswalk = parse_crosswalk(
        {
            "schemaVersion": "capability-keys.v1",
            "source": "test",
            "crosswalks": {"esriAssessRegistry": {}},
        }
    )

    assert crosswalk.capability_keys_for("feature-service") == ()


def test_parse_crosswalk_rejects_unknown_assess_key() -> None:
    payload = _valid_payload()
    payload["crosswalks"]["esriAssessRegistry"]["not-a-real-registry-key"] = []

    with pytest.raises(CrosswalkError, match="not-a-real-registry-key"):
        parse_crosswalk(payload)


def test_parse_crosswalk_rejects_non_object_document() -> None:
    with pytest.raises(CrosswalkError):
        parse_crosswalk(["not", "an", "object"])


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.pop("schemaVersion"),
        lambda payload: payload.pop("source"),
        lambda payload: payload.pop("crosswalks"),
        lambda payload: payload["crosswalks"].pop("esriAssessRegistry"),
    ],
)
def test_parse_crosswalk_rejects_missing_required_fields(mutation) -> None:
    payload = _valid_payload()
    mutation(payload)

    with pytest.raises(CrosswalkError):
        parse_crosswalk(payload)


def test_parse_crosswalk_rejects_bad_entry_shape() -> None:
    payload = _valid_payload()
    payload["crosswalks"]["esriAssessRegistry"]["feature-service"] = "not-a-list"

    with pytest.raises(CrosswalkError):
        parse_crosswalk(payload)


def test_parse_crosswalk_text_rejects_invalid_json() -> None:
    with pytest.raises(CrosswalkError):
        parse_crosswalk_text("{not valid json")


def test_parse_crosswalk_text_round_trips_bundled_fixture() -> None:
    crosswalk = parse_crosswalk_text(bundled_crosswalk_text())

    assert crosswalk.mapping["utility-network"] is None
