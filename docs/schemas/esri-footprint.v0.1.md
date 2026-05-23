# EsriFootprint v0.1 reference

- Schema id: `https://schemas.honua.io/esri-footprint/v0.1.0/esri-footprint.json`
- Schema file: [`schemas/esri-footprint-v0.1.json`](../../schemas/esri-footprint-v0.1.json)
- Canonical sample: [`tests/fixtures/esri-footprint-sample.json`](../../tests/fixtures/esri-footprint-sample.json)
- JSON Schema dialect: draft-2020-12

## Purpose

`EsriFootprint.json` is the read-only artifact that the open-source
`honua-esri-assess` scanner emits and the **closed Honua migration product**
ingests. The contract describes the inventory of a single Esri source
(ArcGIS Online, ArcGIS Server, or FileGDB) in enough detail for the
migration product to plan a Honua takeover *without round-tripping back to
the source system*.

The closed migration product is the sole intended consumer at v0.1. Other
tools may read the file, but no other consumer is part of the contract.

## What this document covers

- The promises this contract makes (read-only, no telemetry, prospect-safe).
- The stability policy for v0.x and the road to v1.0.
- Every top-level field and `$def` in the schema.
- A diagnostic code catalog (closed enum at v0.1).
- A verbatim canonical sample.
- What is intentionally **out of scope** at v0.1.

## Promises

- **Read-only.** Every field describes an observation made against a source.
  No field hints at write, migrate, or mutation semantics.
- **No network telemetry.** The schema contains no upload manifests,
  phone-home shapes, or fields that imply the scanner reports back to
  Honua. Local structured logs are allowed; network telemetry stays off by
  default and is not part of v0.1.
- **Prospect-safe diagnostics.** Raw exceptions and stack traces are
  forbidden by project constraint and excluded from the schema.
  `diagnostics[].code` is drawn from a locked enum so prospects can audit
  the vocabulary before running the scanner.
- **No credentials or raw on-prem paths.** `source.locator`,
  `filegdb.pathHash`, and `ServerService.serviceUrl` are schema-pattern
  enforced so a published footprint never reveals a prospect's secrets
  or filesystem layout. AGOL locators must be exactly `host/org-id`.
  Server locators reject `@` (userinfo), `?` (query string), `#`
  (fragment), and whitespace; FileGDB locators must match
  `^sha256:[0-9a-f]{64}$`; service URLs reject the same unsafe
  components. Count-map keys are also constrained to type labels, not
  URLs or token assignments. See [Source](#source) for the per-kind
  patterns.

## Stability policy

| Range  | Stability                                                          |
|--------|--------------------------------------------------------------------|
| v0.x   | **Unstable.** Breaking changes are permitted between minor bumps.  |
| v0.1.x | Patch bumps are non-breaking clarifications, producer bug fixes, or additions inside explicitly open maps only. |
| v0.2.0 | May break v0.1 consumers (e.g. expand the diagnostic enum).        |
| v1.0   | First stable promise. Breaking changes require a v2 bump.          |

The artifact carries `schemaVersion: "v0.1"` (major.minor) in-band. The
full SemVer (`v0.1.0`) lives in `$id`. Consumers should pin on
`schemaVersion` and treat unknown patch versions as compatible.

## Top-level shape

The top-level object uses `additionalProperties: false` — adding a new
top-level key is a deliberate schema bump. Contract objects are closed at
v0.1, including the source block, facets, inventory variants, diagnostics,
spatial references, extents, and field descriptors. The only open maps are
the documented count-by-type maps such as `portal.itemCounts` and
`server.serviceCounts`; their keys are constrained to prospect-safe type
labels and consumers must not treat unknown map keys as load-bearing
contract fields.

| Field           | Required | Type                              | Description                                                                                                  |
|-----------------|----------|-----------------------------------|--------------------------------------------------------------------------------------------------------------|
| `schemaVersion` | yes      | const `"v0.1"`                    | Contract major.minor carried in-band.                                                                        |
| `generatedAt`   | yes      | RFC3339 UTC                       | When the scanner finished producing this artifact.                                                           |
| `tool`          | yes      | [`ToolProvenance`](#toolprovenance) | Scanner provenance.                                                                                          |
| `source`        | yes      | [`Source`](#source)               | Identifies the scanned Esri source. `source.kind` is the discriminator (see [Discriminator rules](#discriminator-rules)). |
| `portal`        | conditional | [`PortalFacet`](#portalfacet)  | **Required** iff `source.kind == "arcgis-online"`; **forbidden** otherwise.                                  |
| `server`        | conditional | [`ServerFacet`](#serverfacet)  | **Required** iff `source.kind == "arcgis-server"`; **forbidden** otherwise.                                  |
| `filegdb`       | conditional | [`FileGdbFacet`](#filegdbfacet)| **Required** iff `source.kind == "filegdb"`; **forbidden** otherwise.                                        |
| `inventory`     | yes      | [`EsriItem[]`](#esriitem)         | Normalized records. Variant is constrained by `source.kind` (see [Discriminator rules](#discriminator-rules)). Empty array is valid. |
| `counts`        | yes      | [`Counts`](#counts)               | Aggregate roll-up.                                                                                           |
| `diagnostics`   | yes      | [`Diagnostic[]`](#diagnostic)     | Typed, prospect-safe diagnostics. Empty array is valid.                                                      |

### Discriminator rules

`source.kind` is enforced by top-level `allOf` / `if`-`then` branches in
the schema. For each value, the matching facet is required, sibling
facets are forbidden, and `inventory[]` is constrained to the matching
`EsriItem` variant. A single artifact describes exactly one source.

| `source.kind`   | Required facet | Forbidden facets         | `inventory[]` variant                              |
|-----------------|----------------|--------------------------|----------------------------------------------------|
| `arcgis-online` | `portal`       | `server`, `filegdb`      | [`PortalItem`](#portalitem-kind-portal-item)       |
| `arcgis-server` | `server`       | `portal`, `filegdb`      | [`ServerService`](#serverservice-kind-server-service) |
| `filegdb`       | `filegdb`      | `portal`, `server`       | [`FileGdbFeatureClass`](#filegdbfeatureclass-kind-filegdb-feature-class) |

Mixing facets (e.g. an `arcgis-server` artifact that still carries
`portal`) or mixing inventory variants (e.g. a `filegdb-feature-class`
record under an `arcgis-online` source) is a schema validation failure.

### ToolProvenance

| Field     | Required | Type                          | Description                                                       |
|-----------|----------|-------------------------------|-------------------------------------------------------------------|
| `name`    | yes      | const `"honua-esri-assess"`   | Only `honua-esri-assess` is part of the contract at v0.1.         |
| `version` | yes      | SemVer string                 | Scanner build that produced this artifact (e.g. `"0.1.0"`).       |

### Source

`source.kind` is the discriminator. It pins the required facet and the
allowed `EsriItem` variant, and it pins the `locator` pattern. See
[Discriminator rules](#discriminator-rules) for the top-level effect.

| Field        | Required | Type        | Description                                                                                                                                 |
|--------------|----------|-------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| `kind`       | yes      | enum        | One of `arcgis-online`, `arcgis-server`, `filegdb`.                                                                                          |
| `locator`    | yes      | string      | Prospect-safe identifier; format is constrained by `kind` (see below). Never includes credentials, query strings, fragments, or raw on-prem paths. |
| `capturedAt` | yes      | RFC3339 UTC | When the scan against this source began.                                                                                                    |

`source.locator` patterns enforced by the schema:

| `source.kind`   | `locator` pattern                                                                                                     | Example                                            |
|-----------------|-----------------------------------------------------------------------------------------------------------------------|----------------------------------------------------|
| `arcgis-online` | `^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}/[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`              | `honua.maps.arcgis.com/0123ABCDEF456789`           |
| `arcgis-server` | `^https?://[^@?#\s]+(/[^?#\s]*)?$`                                                                                   | `https://gis.example.com/arcgis/rest/services`     |
| `filegdb`       | `^sha256:[0-9a-f]{64}$`                                                                                              | `sha256:0000…` (salted sha256 of the gdb path)     |

The AGOL pattern rejects schemes, colons, backslashes, equals signs, and
extra path segments by requiring exactly a DNS host plus one organization-id
segment. Server locator patterns reject `@` (userinfo), `?` (query string),
`#` (fragment), and whitespace. The FileGDB pattern is why a raw filesystem
path is schema-rejected for `filegdb` sources.

### PortalFacet

Required iff `source.kind == "arcgis-online"`; forbidden otherwise (see [Discriminator rules](#discriminator-rules)). Extra facet fields are rejected at v0.1.

| Field            | Required | Type                                                | Description                                              |
|------------------|----------|-----------------------------------------------------|----------------------------------------------------------|
| `orgId`          | yes      | string                                              | ArcGIS Online organization id.                           |
| `orgUrl`         | yes      | URI                                                 | Organization base URL.                                   |
| `itemCounts`     | yes      | `{ [safe itemType label]: integer }`                | Roll-up by Esri item type (e.g. `Feature Service`). Keys must match `^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,79}$`. |
| `sharingSummary` | no       | `{ private, org, public, shared: integer }`         | Roll-up of sharing levels across portal items.           |
| `licensing`      | no       | [`PortalLicensing`](#portallicensing)               | Read-only license entitlement observations from documented Portal Sharing endpoints. |

### ServerFacet

Required iff `source.kind == "arcgis-server"`; forbidden otherwise (see [Discriminator rules](#discriminator-rules)). Extra facet fields are rejected at v0.1.

| Field           | Required | Type                                    | Description                                                                 |
|-----------------|----------|-----------------------------------------|-----------------------------------------------------------------------------|
| `folders`       | yes      | string[]                                | Top-level service folder names. Empty array if all services live at the root.|
| `serviceCounts` | yes      | `{ [safe serviceType label]: integer }` | Roll-up by Esri service type (e.g. `MapServer`). Keys must match `^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,79}$`. |
| `version`       | no       | string                                  | Reported ArcGIS Server version (e.g. `"11.2"`).                             |
| `licensing`     | no       | [`ServerLicensing`](#serverlicensing)   | Read-only license entitlement observations from documented ArcGIS Server REST/admin endpoints. |

### PortalLicensing

Optional block under `portal.licensing`. It records only entitlement facts
read from documented Sharing API endpoints; credit balances are reduced to
`creditsEnabled` so commercially sensitive balances are not published.

| Field                | Required | Type                         | Description                                      |
|----------------------|----------|------------------------------|--------------------------------------------------|
| `tier`               | no       | string                       | Portal tier observed from the source.            |
| `subscriptionType`   | no       | string                       | Subscription type when exposed.                  |
| `userTypes`          | yes      | [`UserTypeCount[]`](#usertypecount) | Available user-type licenses and counts.         |
| `premiumContent`     | yes      | object                       | `{ creditsEnabled?, allowedAddOns }`.            |
| `extensionsObserved` | yes      | [`ExtensionEntitlement[]`](#extensionentitlement) | Portal add-ons/extensions observed.              |

### ServerLicensing

Optional block under `server.licensing`. It records server-level extension
licenses plus enabled per-service SOEs/SOIs from read-only REST/admin GETs.

| Field               | Required | Type                         | Description                                      |
|---------------------|----------|------------------------------|--------------------------------------------------|
| `productName`       | no       | string                       | Product name reported by ArcGIS Server.          |
| `currentVersion`    | no       | string                       | Server version reported by REST/admin info.      |
| `edition`           | no       | string                       | Server edition when the admin endpoint exposes it. |
| `extensions`        | yes      | [`ExtensionEntitlement[]`](#extensionentitlement) | Server-level extension entitlements.             |
| `serviceExtensions` | yes      | [`ServiceExtensionRecord[]`](#serviceextensionrecord) | Enabled SOEs/SOIs by service.                    |

### Entitlement emission semantics

The `portal.licensing` and `server.licensing` blocks are optional. Absence
means entitlement enumeration was not requested, was not yet wired into that
scanner path, or was intentionally omitted by the producer. When a licensing
block is present, its required arrays are emitted even when empty:
`userTypes`, `extensionsObserved`, `extensions`, and `serviceExtensions`.
An empty array means "nothing observed or enumerable with the current
credential", not a schema error.

Optional scalar fields such as `tier`, `subscriptionType`, `productName`,
`currentVersion`, `edition`, and `creditsEnabled` are omitted when the source
endpoint does not expose them. Portal credit balances are never emitted; the
contract reduces that signal to `premiumContent.creditsEnabled` when available.

The interim `honua-esri-assess entitlements` CLI emits
`{ target, licensing, diagnostics }`, where `licensing` contains the same
nested facet fragment documented here. That interim JSON is a validation and
integration surface only. The closed migration product's handoff remains full
`EsriFootprint.json`.

### ExtensionEntitlement

| Field    | Required | Type | Description |
|----------|----------|------|-------------|
| `code`   | yes      | string | Esri extension code, catalog-normalized when known. |
| `name`   | yes      | string | Human-readable extension name. |
| `status` | yes      | enum | `licensed`, `evaluation`, `expired`, or `unknown`. |
| `source` | yes      | enum | `server-admin-licenses`, `service-extensions`, or `portal-subscription`. |

### UserTypeCount

| Field      | Required | Type        | Description |
|------------|----------|-------------|-------------|
| `name`     | yes      | string      | User-type id or stable name. |
| `total`    | no       | integer ≥ 0 | Seats granted to the org, when exposed. |
| `assigned` | no       | integer ≥ 0 | Seats assigned, when exposed. |

### ServiceExtensionRecord

| Field        | Required | Type     | Description |
|--------------|----------|----------|-------------|
| `serviceUrl` | yes      | URI      | Credentials-stripped service URL; query strings, fragments, and userinfo are rejected. |
| `soes`       | yes      | string[] | Enabled server object extensions. |
| `sois`       | yes      | string[] | Enabled server object interceptors. |

### FileGdbFacet

Required iff `source.kind == "filegdb"`; forbidden otherwise (see [Discriminator rules](#discriminator-rules)). Extra facet fields are rejected at v0.1.

| Field               | Required | Type                              | Description                                                          |
|---------------------|----------|-----------------------------------|----------------------------------------------------------------------|
| `pathHash`          | yes      | `sha256:<64 hex>`                 | Salted hash of the FileGDB path. The raw path is never published.    |
| `featureClassCount` | yes      | integer ≥ 0                       | Number of feature classes discovered.                                |
| `version`           | no       | string                            | FileGDB format version reported by the reader, when available.       |

For FileGDB artifacts, the producer emits `source.locator` and
`filegdb.pathHash` as the same salted path hash. Stable hashes require the
caller to provide the same salt across runs; otherwise the producer may use a
per-run random salt and the hash is only stable within that artifact. The raw
workspace path is never part of the contract.

### EsriItem

Discriminated union via `kind`. Three variants — `portal-item`,
`server-service`, `filegdb-feature-class`. Each variant is closed at v0.1;
adding item fields requires the next minor line.

Within a single artifact, `inventory[]` is constrained to one variant
matching `source.kind` (see [Discriminator rules](#discriminator-rules)).
Consumers must still `switch (item.kind)` to handle artifacts from
different sources uniformly. Per-item readiness/risk flags and explicit
dependency edges across types are deliberately out of scope at v0.1 (see
[Out of scope](#out-of-scope-at-v01)).

#### PortalItem (`kind: "portal-item"`)

| Field          | Required | Type                              | Description                                                           |
|----------------|----------|-----------------------------------|-----------------------------------------------------------------------|
| `id`           | yes      | string                            | Portal item id.                                                       |
| `type`         | yes      | string                            | Esri portal item type (e.g. `Feature Service`).                       |
| `owner`        | yes      | string                            | Item owner username.                                                  |
| `title`        | yes      | string                            | Display title.                                                        |
| `sharing`      | yes      | enum                              | One of `private`, `org`, `public`, `shared`.                          |
| `modified`     | yes      | RFC3339 UTC                       | Item last-modified timestamp.                                         |
| `extent`       | no       | [`Extent`](#extent)               | Item extent when published by the portal.                             |
| `dependencies` | no       | string[]                          | Portal item ids this item references (e.g. webmap → services).        |

#### ServerService (`kind: "server-service"`)

| Field          | Required | Type                              | Description                                                                  |
|----------------|----------|-----------------------------------|------------------------------------------------------------------------------|
| `serviceUrl`   | yes      | URI                               | Fully-qualified service URL. Schema pattern `^https?://[^@?#\s]+(/[^?#\s]*)?$` rejects userinfo, query strings, and fragments. **Credentials must never appear in this field.** |
| `serviceType`  | yes      | string                            | Esri service type (e.g. `MapServer`, `FeatureServer`).                       |
| `folder`       | yes      | string                            | Folder relative to the services root, or empty string for root services.     |
| `layerCount`   | yes      | integer ≥ 0                       | Number of layers exposed by the service.                                     |
| `geometryType` | no       | [`GeometryType`](#geometrytype)   | Service geometry type when uniform across layers.                            |
| `extent`       | no       | [`Extent`](#extent)               | Service full extent.                                                         |
| `sr`           | no       | [`SpatialReference`](#spatialreference) | Service spatial reference.                                              |

#### FileGdbFeatureClass (`kind: "filegdb-feature-class"`)

| Field          | Required | Type                              | Description                                                       |
|----------------|----------|-----------------------------------|-------------------------------------------------------------------|
| `name`         | yes      | string                            | Feature class name as stored in the FileGDB.                      |
| `geometryType` | yes      | [`GeometryType`](#geometrytype)   | Feature class geometry type. `null` for tables.                   |
| `sr`           | yes      | [`SpatialReference`](#spatialreference) | Feature class spatial reference.                            |
| `featureCount` | no       | integer ≥ 0                       | Row count, when the reader can compute it cheaply.                |
| `fields`       | no       | [`FieldDescriptor[]`](#fielddescriptor) | Minimal field metadata.                                     |

The current FileGDB producer maps read-only `pyogrio`/GDAL metadata into this
variant. `featureCount` is optional because counting can be expensive or
unavailable for a layer; the CLI `--force-feature-count` flag asks the backend
to compute it anyway. `fields` contains minimal schema metadata when the
backend reports it. Unsupported geometry labels are emitted as
`geometryType: null` with an `unsupported-item-type` diagnostic rather than raw
reader output.

### Counts

`additionalProperties: false` on both `counts` and `counts.items`. Adding
a new aggregate is a deliberate schema bump.

| Field                            | Required | Type        | Description                                                              |
|----------------------------------|----------|-------------|--------------------------------------------------------------------------|
| `items`                          | yes      | object      | Container for per-kind totals (`additionalProperties: false`).           |
| `items.portal-item`              | no       | integer ≥ 0 | Count of `portal-item` records in `inventory`.                           |
| `items.server-service`           | no       | integer ≥ 0 | Count of `server-service` records in `inventory`.                        |
| `items.filegdb-feature-class`    | no       | integer ≥ 0 | Count of `filegdb-feature-class` records.                                |
| `layers`                         | yes      | integer ≥ 0 | Sum of `layerCount` across `server-service` items.                       |
| `featureClasses`                 | yes      | integer ≥ 0 | Count of `filegdb-feature-class` records.                                |

Scanners SHOULD emit all three `items` sub-keys so the migration product
can rely on per-kind totals; consumers should treat an absent sub-key as
`0`. Tightening the schema to require those sub-keys would be a breaking
change for strict v0.1 validators and therefore requires a v0.2 bump.

For FileGDB artifacts, `filegdb.featureClassCount`,
`counts.featureClasses`, and `counts.items.filegdb-feature-class` all count
emitted `filegdb-feature-class` records.

### Diagnostic

Typed, prospect-safe diagnostic record. `additionalProperties: false`.

| Field      | Required | Type    | Description                                                                                 |
|------------|----------|---------|---------------------------------------------------------------------------------------------|
| `code`     | yes      | enum    | One of the codes in the [diagnostic code catalog](#diagnostic-code-catalog).                |
| `severity` | yes      | enum    | `info`, `warn`, or `error`.                                                                 |
| `message`  | yes      | string  | Human-readable summary. **Must not contain raw stack traces, credentials, or on-prem paths.**|
| `scope`    | yes      | string  | Identifier of the affected area — usually `source.kind`, a folder, or an `EsriItem` id.     |
| `hint`     | no       | string  | Optional remediation hint surfaced to the prospect.                                         |

### Reusable `$defs`

#### RFC3339

`string`, format `date-time`, with an explicit `Z` suffix. The local
validation harness supplies a strict format checker so invalid calendar
values are rejected, not only strings that miss the timestamp shape.

#### SemVer

`string` matching the SemVer 2.0 grammar.

#### SpatialReference

Esri publishes `wkid`, `latestWkid`, and `wkt` inconsistently. The schema
requires **at least one** via `anyOf`. Consumers cannot rely on a single
canonical SR field — handle all three.

| Field        | Required | Type     | Description                                |
|--------------|----------|----------|--------------------------------------------|
| `wkid`       | one of   | integer  | Well-known spatial reference id.           |
| `latestWkid` | one of   | integer  | Latest WKID published by Esri.             |
| `wkt`        | one of   | string   | OGC WKT spatial reference string.          |

#### Extent

| Field  | Required | Type                                       | Description                                  |
|--------|----------|--------------------------------------------|----------------------------------------------|
| `bbox` | yes      | `[xmin, ymin, xmax, ymax]` of 4 numbers    | Bounding box in `crs` coordinates.           |
| `crs`  | yes      | [`SpatialReference`](#spatialreference)    | Coordinate system for `bbox`.                |

#### GeometryType

Either an Esri geometry type tag (`esriGeometryPoint`,
`esriGeometryMultipoint`, `esriGeometryPolyline`, `esriGeometryPolygon`,
`esriGeometryEnvelope`) or `null` for tables and non-spatial items.

#### FieldDescriptor

| Field      | Required | Type    | Description                                                |
|------------|----------|---------|------------------------------------------------------------|
| `name`     | yes      | string  | Field name.                                                |
| `type`     | yes      | string  | Esri field type tag (e.g. `esriFieldTypeOID`).             |
| `nullable` | no       | boolean | Whether the field permits NULL.                            |

## Diagnostic code catalog

The diagnostic vocabulary is **locked at v0.1**. Adding a code requires a
v0.2 bump; clarifying an existing code is a v0.1.x doc bump.

| Code                    | Typical severity | When to emit                                                                                  |
|-------------------------|------------------|-----------------------------------------------------------------------------------------------|
| `rate-limited`          | info / warn      | The source throttled the scanner; coverage may be partial when the throttled endpoint cannot be read. |
| `partial-coverage`      | warn             | The scanner could not enumerate a region of the source (timeout, pagination ceiling, etc.).   |
| `missing-permission`    | warn             | The scanner credential cannot read part of the source. Surface a hint with the required role. |
| `unresolved-reference`  | warn             | An item references another item that the scanner could not find or could not read.            |
| `unsupported-item-type` | info             | The source exposes an item type the scanner does not model at v0.1.                           |
| `redacted-field`        | info             | The scanner deliberately omitted a field to keep the artifact prospect-safe.                  |

Expected FileGDB diagnostic cases at v0.1:

- Missing optional reader dependency, missing/unreadable workspace, or layer
  list failure: `partial-coverage` with `severity: "error"`.
- Per-layer metadata read failure: `partial-coverage` with
  `severity: "warn"`; the unreadable layer is skipped.
- Unsupported geometry label: `unsupported-item-type` with
  `severity: "info"` and `geometryType: null`.

## Canonical sample

This sample is identical to
[`tests/fixtures/esri-footprint-sample.json`](../../tests/fixtures/esri-footprint-sample.json)
and is exercised by `tests/test_esri_footprint_schema.py`.

```json
{
  "schemaVersion": "v0.1",
  "generatedAt": "2026-05-22T14:08:33Z",
  "tool": {
    "name": "honua-esri-assess",
    "version": "0.1.0"
  },
  "source": {
    "kind": "arcgis-online",
    "locator": "example.maps.arcgis.com/0123ABCDEF456789",
    "capturedAt": "2026-05-22T14:02:11Z"
  },
  "portal": {
    "orgId": "0123ABCDEF456789",
    "orgUrl": "https://example.maps.arcgis.com",
    "itemCounts": {
      "Feature Service": 2,
      "Web Map": 1
    },
    "sharingSummary": {
      "private": 1,
      "org": 1,
      "public": 1,
      "shared": 0
    }
  },
  "inventory": [
    {
      "kind": "portal-item",
      "id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
      "type": "Feature Service",
      "owner": "gis.admin",
      "title": "Parcels",
      "sharing": "org",
      "modified": "2026-04-18T09:12:00Z",
      "extent": {
        "bbox": [-122.52, 47.43, -122.18, 47.74],
        "crs": { "wkid": 4326 }
      },
      "dependencies": []
    },
    {
      "kind": "portal-item",
      "id": "b2c3d4e5f6071829a3b4c5d6e7f80910",
      "type": "Feature Service",
      "owner": "field.crew",
      "title": "Hydrants",
      "sharing": "private",
      "modified": "2026-05-01T16:40:22Z",
      "extent": {
        "bbox": [-122.49, 47.45, -122.22, 47.71],
        "crs": { "wkid": 4326 }
      }
    },
    {
      "kind": "portal-item",
      "id": "c3d4e5f60718293a4b5c6d7e8f901122",
      "type": "Web Map",
      "owner": "gis.admin",
      "title": "Public Asset Viewer",
      "sharing": "public",
      "modified": "2026-05-10T11:00:00Z",
      "dependencies": [
        "a1b2c3d4e5f60718293a4b5c6d7e8f90",
        "b2c3d4e5f6071829a3b4c5d6e7f80910"
      ]
    }
  ],
  "counts": {
    "items": {
      "portal-item": 3,
      "server-service": 0,
      "filegdb-feature-class": 0
    },
    "layers": 0,
    "featureClasses": 0
  },
  "diagnostics": [
    {
      "code": "missing-permission",
      "severity": "warn",
      "message": "Skipped 2 items the scanner credential cannot read.",
      "scope": "arcgis-online",
      "hint": "Re-run with a credential that has read access to the GIS Admin group."
    },
    {
      "code": "rate-limited",
      "severity": "info",
      "message": "Sharing API throttled the scan for 3.2s.",
      "scope": "arcgis-online"
    }
  ]
}
```

## Out of scope at v0.1

These items are deliberately deferred so the v0.1 contract stays focused on
read-only inventory and typed diagnostics. They are candidates for v0.2 once
the closed migration product ingests real fixture-backed footprints.

- Per-item readiness or risk flags.
- Explicit dependency edges across kinds (webmap → service → layer).
- Scanner timing or performance metrics.
- Any field that hints at write or migrate semantics.
- Telemetry, upload manifests, or scanner-phone-home shapes.

## Validating an artifact

```bash
python -m pip install -e ".[dev]"
pytest
```

The test suite loads the schema and the canonical sample with
`jsonschema.Draft202012Validator` plus the project UTC timestamp format
checker, asserts `schemaVersion == "v0.1"`, and asserts that every
`diagnostics[].code` lives in the locked v0.1 enum.
Consumers validating outside this test suite should enable `date-time`
format assertions or an equivalent RFC3339 UTC check.
