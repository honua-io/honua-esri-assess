# Entitlement Enumeration

E6 adds read-only enumeration for Esri license entitlements and extension
observations. The collector output is designed to slot into the optional
`portal.licensing` and `server.licensing` blocks in `EsriFootprint.json` v0.1.

The interim `honua-esri-assess entitlements` command prints a fragment for
validation and integration work. It is not a second handoff contract; the
closed migration product continues to ingest only full `EsriFootprint.json`
artifacts.

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

The Portal CLI `--target` is the portal base URL, for example
`https://www.arcgis.com` or `https://example.maps.arcgis.com`. It is not the
`/sharing/rest` base used by `scan agol`.

ArcGIS Server collector:

| Purpose | Endpoint path |
| --- | --- |
| Public product/version fallback | `/rest/info` |
| Admin product/version/edition hints | `/admin/info` |
| Server extension licenses | `/admin/system/licenses` |
| Service discovery for SOE/SOI checks | `/admin/services` and `/admin/services/{folder}` |
| Per-service SOEs/SOIs | `/admin/services/{folder}/{name}.{type}` |

The Server CLI `--target` is the ArcGIS Server root, for example
`https://gis.example.com/arcgis`.

## CLI usage

```bash
honua-esri-assess entitlements agol \
  --target https://www.arcgis.com \
  --token "$ESRI_TOKEN"

honua-esri-assess entitlements agol \
  --target https://www.arcgis.com \
  --anonymous

honua-esri-assess entitlements server \
  --target https://gis.example.com/arcgis \
  --token "$ESRI_TOKEN"

honua-esri-assess entitlements server \
  --target https://gis.example.com/arcgis \
  --service Hosted/Parcels.MapServer \
  --service World.MapServer

honua-esri-assess entitlements server \
  --target https://gis.example.com/arcgis \
  --no-service-extensions
```

Common flags:

| Flag | Applies to | Behavior |
| --- | --- | --- |
| `--token` | Portal, Server | Adds the token to Esri GET requests for org/admin endpoints. |
| `--timeout` | Portal, Server | Sets HTTP timeout in seconds. Default is `30`. |
| `--verbose` | Portal, Server | Enables INFO logs to stderr. |
| `--debug` | Portal, Server | Enables DEBUG logs and re-raises hard failures. Do not use for customer-facing runs. |
| `--anonymous` | Portal | Skips token-required subscription, user-license, and users endpoints. |
| `--service FOLDER/NAME.TYPE` | Server | Restricts SOE/SOI lookup to explicit services. Repeatable. Folder is optional. |
| `--no-service-extensions` | Server | Skips per-service SOE/SOI enumeration. |

## Response shape

The command writes JSON to stdout:

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

Soft coverage gaps become typed diagnostics in the JSON payload and keep exit
code `0`. Examples include:

- `missing-permission` for optional org/admin endpoints denied by the token.
- `partial-coverage` for unexpected but recoverable response shapes or unknown
  extension codes recorded verbatim.
- `unresolved-reference` for service endpoints that cannot be enumerated.

Hard entitlement failures return exit code `3` with a prospect-safe stderr
message unless `--debug` is set. Hard failures include authentication required
on required endpoints, forbidden/not-found/rate-limit responses that cannot be
downgraded, connection failures, Esri API errors, and non-JSON responses.

Unexpected failures return exit code `1`. Invalid CLI usage returns exit code
`2`.

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
