from __future__ import annotations

from datetime import datetime, timezone

from honua_esri_assess.diagnostics import Diagnostic
from honua_esri_assess.footprint.schema import validate_footprint
from honua_esri_assess.footprint.v0_1 import to_footprint_v0_1
from honua_esri_assess.portal.models import GroupRecord, ItemRecord, OrgInfo, PortalScanResult


def test_footprint_shape_validates_and_redacts_urls() -> None:
    result = PortalScanResult(
        org=OrgInfo(
            id="org-123",
            name="Demo GIS",
            portal_url="https://demo.maps.arcgis.com",
            sharing_rest_url="https://demo.maps.arcgis.com/sharing/rest",
            user_count=42,
            group_count=1,
        ),
        auth_mode="token",
        items=[
            ItemRecord(
                id="item-1",
                title="Parcels",
                owner="publisher",
                item_type="Feature Service",
                type_bucket="featureService",
                url="https://services.arcgis.com/demo/FeatureServer?token=secret-token",
            )
        ],
        groups=[GroupRecord(id="group-1", title="Public Data")],
        diagnostics=[
            Diagnostic(
                code="portal.test",
                severity="warning",
                message="Synthetic warning",
                context={"url": "https://example.com?token=secret-token", "token": "secret-token"},
            )
        ],
    )

    footprint = to_footprint_v0_1(
        result,
        tool_version="0.0.0",
        generated_at=datetime(2026, 5, 22, 18, 0, tzinfo=timezone.utc),
    )

    validate_footprint(footprint)
    rendered = str(footprint)
    assert footprint["schemaVersion"] == "v0.2"
    assert footprint["tool"]["name"] == "honua-esri-assess"
    assert footprint["source"]["kind"] == "arcgis-online"
    assert "secret-token" not in rendered
