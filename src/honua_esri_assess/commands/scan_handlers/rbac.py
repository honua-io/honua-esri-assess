"""Read-only RBAC / access-footprint scanner adapter.

Wires the documented, GET-only :mod:`honua_esri_assess.scanners.admin_rbac`
scanner into the ``scan rbac`` command and renders its result into the
``EsriAccessFootprint.json`` v0.1 wire shape via
:func:`honua_esri_assess.footprint.access.build_access_footprint`.

This is the deferred slice of issue #30. Full per-service ACE crawling and
effective-permission resolution are intentionally out of scope here; the
scanner only models the identity / RBAC posture exposed by the documented
Portal ``admin``/``community`` and ArcGIS Server ``admin/security`` endpoints.
"""

from __future__ import annotations

from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.entitlements.http import RequestsHttpClient
from honua_esri_assess.footprint.access import build_access_footprint
from honua_esri_assess.scanners.admin_rbac import scan_portal_rbac, scan_server_rbac


def run(options: ScanOptions) -> ScanResult:
    client = RequestsHttpClient(
        token=options.token,
        user_agent=options.user_agent,
        default_timeout=options.timeout,
    )
    if options.rbac_kind == "server":
        footprint = scan_server_rbac(options.target, client, timeout=options.timeout)
    else:
        footprint = scan_portal_rbac(options.target, client, timeout=options.timeout)
    artifact = build_access_footprint(footprint)
    return ScanResult(
        footprint=artifact,
        diagnostics=tuple(footprint.diagnostics),
    )
