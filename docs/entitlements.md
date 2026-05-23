# Entitlement Enumeration

E6 adds read-only enumeration for Esri license entitlements and extension
observations. The collector output is designed to slot into the optional
`portal.licensing` and `server.licensing` blocks in `EsriFootprint.json` v0.1.

`EsriFootprint.json` remains the sole handoff contract; entitlement
observations only reach the closed migration product when a `scan` handler
attaches them to the emitted footprint.

> **Status (E9 CLI consolidation).** The interim standalone
> `honua-esri-assess entitlements` subcommand has been retired alongside the
> CLI consolidation in [E9](../README.md#command-line-usage). The Python
> collectors below remain the supported interim surface until scanner
> integration lands; the CLI usage examples in earlier revisions of this
> document apply only to pre-E9 releases.

## Read-only endpoint coverage

The entitlement collectors only issue HTTP GET requests. Tokens, when supplied,
are sent to Esri endpoints only. No entitlement path posts telemetry or calls a
Honua-operated service.

Portal / ArcGIS Online collector:

| Purpose | Endpoint path |
| --- | --- |
| Portal identity and public subscription hints | `/sharing/rest/portals/self` |
| Subscription detail and allowed add-ons | `/sharing/rest/portals/self/subscriptionInfo` |
| User-type license counts | `/sharing/rest/portals/self/userLicenseTypes` |
| Org-wide user total fallback | `/sharing/rest/portals/{orgId}/users` |

When invoked from Python, the Portal collector expects a portal base URL,
for example `https://www.arcgis.com` or `https://example.maps.arcgis.com`. It
is not the `/sharing/rest` base used by `scan agol`.

ArcGIS Server collector:

| Purpose | Endpoint path |
| --- | --- |
| Public product/version fallback | `/rest/info` |
| Admin product/version/edition hints | `/admin/info` |
| Server extension licenses | `/admin/system/licenses` |
| Service discovery for SOE/SOI checks | `/admin/services` and `/admin/services/{folder}` |
| Per-service SOEs/SOIs | `/admin/services/{folder}/{name}.{type}` |

When invoked from Python, the Server collector expects the ArcGIS Server
root, for example `https://gis.example.com/arcgis`.

## Collector knobs

The Python collectors mirror the option surface of the retired CLI:

| Knob | Applies to | Behavior |
| --- | --- | --- |
| `RequestsHttpClient(token=...)` | Portal, Server | Adds the token to Esri GET requests for org/admin endpoints. |
| `RequestsHttpClient(default_timeout=...)` | Portal, Server | Sets HTTP timeout in seconds. Default is `30`. |
| `PortalEntitlementsCollector(anonymous=True)` | Portal | Skips token-required subscription, user-license, and users endpoints. |
| `ServerEntitlementsCollector(include_service_extensions=False)` | Server | Skips per-service SOE/SOI enumeration. |
| `ServerEntitlementsCollector.collect([ServiceRef(...), ...])` | Server | Restricts SOE/SOI lookup to explicit services. Folder is optional. |

Logging is configured by the surrounding application; the collectors emit
no telemetry of their own.

## Response shape

The collectors produce a JSON-serializable fragment:

```json
{
  "target": "server",
  "licensing": {
    "server": {
      "licensing": {
        "productName": "ArcGIS Server",
        "currentVersion": "11.3",
        "edition": "Advanced",
        "extensions": [
          {
            "code": "Spatial",
            "name": "Spatial Analyst",
            "status": "licensed",
            "source": "server-admin-licenses"
          }
        ],
        "serviceExtensions": [
          {
            "serviceUrl": "https://gis.example.com/arcgis/rest/services/World/MapServer",
            "soes": ["FeatureServer", "WMSServer"],
            "sois": ["AuthSOI"]
          }
        ]
      }
    }
  },
  "diagnostics": []
}
```

For Portal targets, `licensing.portal.licensing` contains:

- `tier` and `subscriptionType` when the source exposes them.
- `userTypes`, always present as an array.
- `premiumContent.allowedAddOns`, always present as an array.
- `premiumContent.creditsEnabled` when a credit signal is exposed. Raw credit
  balances are intentionally not emitted.
- `extensionsObserved`, always present as an array.

For Server targets, `licensing.server.licensing` contains:

- `productName`, `currentVersion`, and `edition` when exposed.
- `extensions`, always present as an array.
- `serviceExtensions`, always present as an array.

Optional scalar fields are omitted when unavailable. Required arrays are present
and may be empty when no entitlements are observed, permission is missing, or an
optional lookup is skipped.

## Diagnostics and failures

Soft coverage gaps become typed diagnostics on the collector result. Examples
include:

- `missing-permission` for optional org/admin endpoints denied by the token.
- `partial-coverage` for unexpected but recoverable response shapes or unknown
  extension codes recorded verbatim.
- `unresolved-reference` for service endpoints that cannot be enumerated.

Hard entitlement failures raise `EntitlementsError` subclasses
(`EntitlementsAuthError`, `EntitlementsForbiddenError`,
`EntitlementsNotFoundError`, `EntitlementsRateLimitedError`,
`EntitlementsConnectionError`, `EntitlementsApiError`,
`EntitlementsSchemaError`). Callers are responsible for translating these to
their own user-facing surface; they must never leak raw exception text or
tokens to prospects.

## Developer integration

The public Python surface is `honua_esri_assess.entitlements`:

```python
from honua_esri_assess.entitlements import (
    LicensingFacet,
    PortalEntitlementsCollector,
    RequestsHttpClient,
    ServerEntitlementsCollector,
)
from honua_esri_assess.footprint import licensing_facet_to_dict

client = RequestsHttpClient(token=token)
portal_result = PortalEntitlementsCollector(
    "https://www.arcgis.com", client
).collect()

fragment = licensing_facet_to_dict(
    LicensingFacet(portal=portal_result.licensing, server=None)
)
```

Collector diagnostics use the same v0.1 diagnostic vocabulary as the footprint
schema. The wire-shape conversion lives in
`honua_esri_assess.footprint.licensing_facet_to_dict`, so the dataclasses can
stay Pythonic while the emitted fragment stays camelCase and schema-aligned.
