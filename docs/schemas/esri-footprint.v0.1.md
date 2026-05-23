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
- **No credentials or raw on-prem paths.** `source.locator` and
  `filegdb.pathHash` are designed so a published footprint never reveals a
  prospect's secrets or filesystem layout. FileGDB paths are surfaced as a
  salted `sha256:` hash.

## Stability policy

| Range  | Stability                                                          |
|--------|--------------------------------------------------------------------|
| v0.x   | **Unstable.** Breaking changes are permitted between minor bumps.  |
| v0.1.x | Patch bumps are documentation or clarification only.               |
| v0.2.0 | May break v0.1 consumers (e.g. expand the diagnostic enum).        |
| v1.0   | First stable promise. Breaking changes require a v2 bump.          |

The artifact carries `schemaVersion: "v0.1"` (major.minor) in-band. The
full SemVer (`v0.1.0`) lives in `$id`. Consumers should pin on
`schemaVersion` and treat unknown patch versions as compatible.

## Top-level shape

The top-level object uses `additionalProperties: false` — adding a new
top-level key is a deliberate schema bump. Facet objects (`portal`,
`server`, `filegdb`) and each `EsriItem` variant accept additional
properties so scanners can attach vendor-specific extras within v0.1.
**Extras are non-load-bearing.** The migration product must not require
any field outside this contract.

| Field           | Required | Type                              | Description                                                                                                  |
|-----------------|----------|-----------------------------------|--------------------------------------------------------------------------------------------------------------|
| `schemaVersion` | yes      | const `"v0.1"`                    | Contract major.minor carried in-band.                                                                        |
| `generatedAt`   | yes      | RFC3339 UTC                       | When the scanner finished producing this artifact.                                                           |
| `tool`          | yes      | [`ToolProvenance`](#toolprovenance) | Scanner provenance.                                                                                          |
| `source`        | yes      | [`Source`](#source)               | Identifies the scanned Esri source.                                                                          |
| `portal`        | no       | [`PortalFacet`](#portalfacet)     | Present when `source.kind == "arcgis-online"`.                                                               |
| `server`        | no       | [`ServerFacet`](#serverfacet)     | Present when `source.kind == "arcgis-server"`.                                                               |
| `filegdb`       | no       | [`FileGdbFacet`](#filegdbfacet)   | Present when `source.kind == "filegdb"`.                                                                     |
| `inventory`     | yes      | [`EsriItem[]`](#esriitem)         | Normalized records discriminated by `kind`. Empty array is valid.                                            |
| `counts`        | yes      | [`Counts`](#counts)               | Aggregate roll-up.                                                                                           |
| `diagnostics`   | yes      | [`Diagnostic[]`](#diagnostic)     | Typed, prospect-safe diagnostics. Empty array is valid.                                                      |

### ToolProvenance

| Field     | Required | Type                          | Description                                                       |
|-----------|----------|-------------------------------|-------------------------------------------------------------------|
| `name`    | yes      | const `"honua-esri-assess"`   | Only `honua-esri-assess` is part of the contract at v0.1.         |
| `version` | yes      | SemVer string                 | Scanner build that produced this artifact (e.g. `"0.1.0"`).       |

### Source

`source.kind` discriminates which facet (`portal`, `server`, `filegdb`)
should be populated and which `EsriItem` variants a scanner is expected to
emit.

| Field        | Required | Type        | Description                                                                                                                                 |
|--------------|----------|-------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| `kind`       | yes      | enum        | One of `arcgis-online`, `arcgis-server`, `filegdb`.                                                                                          |
| `locator`    | yes      | string      | Prospect-safe identifier (host + org id for AGOL, base services URL for Server, `sha256:` salted hash for FileGDB). Never includes credentials. |
| `capturedAt` | yes      | RFC3339 UTC | When the scan against this source began.                                                                                                    |

### PortalFacet

Present iff `source.kind == "arcgis-online"`. Extras allowed.

| Field            | Required | Type                                                | Description                                              |
|------------------|----------|-----------------------------------------------------|----------------------------------------------------------|
| `orgId`          | yes      | string                                              | ArcGIS Online organization id.                           |
| `orgUrl`         | yes      | URI                                                 | Organization base URL.                                   |
| `itemCounts`     | yes      | `{ [itemType: string]: integer }`                   | Roll-up by Esri item type (e.g. `Feature Service`).      |
| `sharingSummary` | no       | `{ private, org, public, shared: integer }`         | Roll-up of sharing levels across portal items.           |

### ServerFacet

Present iff `source.kind == "arcgis-server"`. Extras allowed.

| Field           | Required | Type                                    | Description                                                                 |
|-----------------|----------|-----------------------------------------|-----------------------------------------------------------------------------|
| `folders`       | yes      | string[]                                | Top-level service folder names. Empty array if all services live at the root.|
| `serviceCounts` | yes      | `{ [serviceType: string]: integer }`    | Roll-up by Esri service type (e.g. `MapServer`).                            |
| `version`       | no       | string                                  | Reported ArcGIS Server version (e.g. `"11.2"`).                             |

### FileGdbFacet

Present iff `source.kind == "filegdb"`. Extras allowed.

| Field               | Required | Type                              | Description                                                          |
|---------------------|----------|-----------------------------------|----------------------------------------------------------------------|
| `pathHash`          | yes      | `sha256:<64 hex>`                 | Salted hash of the FileGDB path. The raw path is never published.    |
| `featureClassCount` | yes      | integer ≥ 0                       | Number of feature classes discovered.                                |
| `version`           | no       | string                            | FileGDB format version reported by the reader, when available.       |

### EsriItem

Discriminated union via `kind`. Three variants — `portal-item`,
`server-service`, `filegdb-feature-class`. Each variant accepts additional
properties so scanners can attach vendor-specific extras within v0.1;
**extras are non-load-bearing**.

Consumers must `switch (item.kind)` rather than treating items uniformly.
Per-item readiness/risk flags and explicit dependency edges across types
are deliberately out of scope at v0.1 (see [Out of scope](#out-of-scope-at-v01)).

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
| `serviceUrl`   | yes      | URI                               | Fully-qualified service URL. **Credentials must never appear in this field.**|
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

### Counts

`additionalProperties: false`. Adding a new aggregate is a deliberate
schema bump.

| Field                            | Required | Type        | Description                                          |
|----------------------------------|----------|-------------|------------------------------------------------------|
| `items.portal-item`              | yes      | integer ≥ 0 | Count of `portal-item` records in `inventory`.       |
| `items.server-service`           | yes      | integer ≥ 0 | Count of `server-service` records in `inventory`.    |
| `items.filegdb-feature-class`    | yes      | integer ≥ 0 | Count of `filegdb-feature-class` records.            |
| `layers`                         | yes      | integer ≥ 0 | Sum of `layerCount` across `server-service` items.   |
| `featureClasses`                 | yes      | integer ≥ 0 | Count of `filegdb-feature-class` records.            |

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

`string`, format `date-time`. RFC3339 UTC timestamp.

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
| `rate-limited`          | info / warn      | The source throttled the scanner; coverage is still complete but the scan took longer.        |
| `partial-coverage`      | warn             | The scanner could not enumerate a region of the source (timeout, pagination ceiling, etc.).   |
| `missing-permission`    | warn             | The scanner credential cannot read part of the source. Surface a hint with the required role. |
| `unresolved-reference`  | warn             | An item references another item that the scanner could not find or could not read.            |
| `unsupported-item-type` | info             | The source exposes an item type the scanner does not model at v0.1.                           |
| `redacted-field`        | info             | The scanner deliberately omitted a field to keep the artifact prospect-safe.                  |

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
        "crs": { "wkid": 102100, "latestWkid": 3857 }
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

These items are deliberately deferred so the contract can ship before the
scanners are wired. They are candidates for v0.2 once the closed
migration product ingests a real footprint.

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
`jsonschema.Draft202012Validator`, asserts `schemaVersion == "v0.1"`, and
asserts that every `diagnostics[].code` lives in the locked v0.1 enum.
