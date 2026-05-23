"""Round-trip the LicensingFacet through the v0.1 emitter."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from honua_esri_assess.entitlements.models import (
    ExtensionEntitlement,
    LicensingFacet,
    PortalLicensing,
    ServerLicensing,
    ServiceExtensionRecord,
    UserTypeCount,
)
from honua_esri_assess.footprint.v0_1 import licensing_facet_to_dict


REPO_ROOT = Path(__file__).resolve().parents[2]


def _full_facet() -> LicensingFacet:
    return LicensingFacet(
        portal=PortalLicensing(
            tier="online",
            subscription_type="Subscription",
            user_types=[UserTypeCount(name="creatorUT", total=50, assigned=32)],
            premium_credits_enabled=True,
            allowed_add_ons=["hub", "premiumContent"],
            extensions_observed=[
                ExtensionEntitlement(
                    code="Spatial",
                    name="ArcGIS Spatial Analyst",
                    status="licensed",
                    source="portal-subscription",
                )
            ],
        ),
        server=ServerLicensing(
            product_name="ArcGIS Server",
            current_version="11.3",
            edition="Advanced",
            extensions=[
                ExtensionEntitlement(
                    code="Network",
                    name="ArcGIS Network Analyst",
                    status="licensed",
                    source="server-admin-licenses",
                )
            ],
            service_extensions=[
                ServiceExtensionRecord(
                    service_url="https://example.com/arcgis/rest/services/Hosted/Parcels/MapServer",
                    soes=["FeatureServer"],
                    sois=["AuthSOI"],
                )
            ],
        ),
    )


def test_licensing_facet_to_dict_uses_camelcase_field_names() -> None:
    payload = licensing_facet_to_dict(_full_facet())

    portal = payload["portal"]["licensing"]
    assert portal["tier"] == "online"
    assert portal["subscriptionType"] == "Subscription"
    assert portal["userTypes"] == [{"name": "creatorUT", "total": 50, "assigned": 32}]
    assert portal["premiumContent"] == {
        "creditsEnabled": True,
        "allowedAddOns": ["hub", "premiumContent"],
    }
    assert portal["extensionsObserved"][0]["code"] == "Spatial"
    assert portal["extensionsObserved"][0]["source"] == "portal-subscription"

    server = payload["server"]["licensing"]
    assert server["productName"] == "ArcGIS Server"
    assert server["currentVersion"] == "11.3"
    assert server["edition"] == "Advanced"
    assert server["extensions"][0]["status"] == "licensed"
    assert server["serviceExtensions"][0]["serviceUrl"].endswith("/Hosted/Parcels/MapServer")
    assert server["serviceExtensions"][0]["soes"] == ["FeatureServer"]
    assert server["serviceExtensions"][0]["sois"] == ["AuthSOI"]


def test_licensing_facet_to_dict_omits_unset_sides() -> None:
    payload = licensing_facet_to_dict(LicensingFacet(portal=None, server=None))
    assert payload == {}

    portal_only = licensing_facet_to_dict(
        LicensingFacet(portal=PortalLicensing(), server=None)
    )
    assert "server" not in portal_only
    assert portal_only["portal"]["licensing"]["userTypes"] == []
    assert portal_only["portal"]["licensing"]["extensionsObserved"] == []


def test_licensing_facet_drops_none_optionals() -> None:
    facet = LicensingFacet(
        portal=PortalLicensing(),
        server=ServerLicensing(),
    )
    payload = licensing_facet_to_dict(facet)
    # Optional scalars stay out of the dict to keep the JSON small and to
    # signal "unknown" to the consumer.
    assert "tier" not in payload["portal"]["licensing"]
    assert "subscriptionType" not in payload["portal"]["licensing"]
    assert "productName" not in payload["server"]["licensing"]
    assert "currentVersion" not in payload["server"]["licensing"]
    assert "edition" not in payload["server"]["licensing"]


def test_user_type_count_omits_unset_numerics() -> None:
    facet = LicensingFacet(
        portal=PortalLicensing(user_types=[UserTypeCount(name="x")]), server=None
    )
    payload = licensing_facet_to_dict(facet)
    assert payload["portal"]["licensing"]["userTypes"] == [{"name": "x"}]


def test_licensing_blocks_validate_inside_v01_schema() -> None:
    schema = json.loads(
        (REPO_ROOT / "schemas" / "esri-footprint-v0.1.json").read_text(
            encoding="utf-8"
        )
    )
    sample = json.loads(
        (REPO_ROOT / "docs" / "samples" / "esri-footprint.sample.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    fragment = licensing_facet_to_dict(_full_facet())

    portal_artifact = copy.deepcopy(sample)
    portal_artifact["portal"].update(fragment["portal"])
    assert list(validator.iter_errors(portal_artifact)) == []

    server_artifact = copy.deepcopy(sample)
    server_artifact["source"] = {
        "kind": "arcgis-server",
        "locator": "https://example.com/arcgis/rest/services",
        "capturedAt": "2026-05-22T14:02:11Z",
    }
    server_artifact.pop("portal")
    server_artifact["server"] = {
        "folders": ["Hosted"],
        "serviceCounts": {"MapServer": 1},
        **fragment["server"],
    }
    server_artifact["inventory"] = [
        {
            "kind": "server-service",
            "serviceUrl": "https://example.com/arcgis/rest/services/Hosted/Parcels/MapServer",
            "serviceType": "MapServer",
            "folder": "Hosted",
            "layerCount": 1,
        }
    ]
    server_artifact["counts"] = {
        "items": {
            "portal-item": 0,
            "server-service": 1,
            "filegdb-feature-class": 0,
        },
        "layers": 1,
        "featureClasses": 0,
    }
    assert list(validator.iter_errors(server_artifact)) == []
