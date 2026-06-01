# EsriFootprint.json v0.2

`esri-footprint/v0.2` is an **additive, back-compatible** revision of
[`v0.1`](./esri-footprint.v0.1.md). It populates the dependency edges the v0.1
schema reserved but left empty so batch orchestration can order migrations
(webmap → service → layer), and it classifies portal items by functional
content type so migration effort reflects what users actually touch.
Everything documented for v0.1 still applies; this page covers only the delta.

The canonical schema lives at
[`schemas/esri-footprint-v0.2.json`](../../schemas/esri-footprint-v0.2.json),
mirrored as a package resource at
`src/honua_esri_assess/schemas/esri-footprint-v0.2.json`.

## What changed from v0.1

| Change | Detail |
|--------|--------|
| `schemaVersion` | Now accepts `"v0.1"` **or** `"v0.2"`. v0.2 producers emit `"v0.2"`; v0.1 artifacts still validate against the v0.2 reader. |
| `dependencyEdges` | New **optional** top-level array of [`DependencyEdge`](#dependencyedge). Absent or empty when no edges resolve. |
| `portal.contentTypeCounts` | New **optional** `EsriTypeCountMap` of [functional content category](#portal-content-type-classification) → count, alongside the existing raw `portal.itemCounts`. |
| `PortalItem.contentCategory` | New **optional** per-item string drawn from the functional-category enum. |

No fields were removed, renamed, or made stricter. A v0.1 artifact is a valid
v0.2 artifact, and a v0.1 reader can ignore the unknown `dependencyEdges`,
`contentTypeCounts`, and `contentCategory` keys, so the bump is back-compatible
in both directions.

## Portal content-type classification

Portal items carry a coarse Esri `type` plus a `typeKeywords` list. Several
distinct products share one `type` (Web AppBuilder, Experience Builder, Instant
Apps, and StoryMaps all surface as `Web Mapping Application`), so the raw
`itemCounts` under-reports what a shop runs. v0.2 derives a stable functional
**content category** from `type` + `typeKeywords` and reports it two ways:

- `portal.contentTypeCounts` — a roll-up of category → count.
- `PortalItem.contentCategory` — the category on each inventory record.

Classification is shallow: it consumes only the `type` and `typeKeywords`
already returned by `search` / `content/items/<id>` and never fetches or parses
per-app configuration. Unrecognized content is recorded explicitly as
`unknown` rather than dropped.

| Category | Example sources |
|----------|-----------------|
| `web-map`, `web-scene` | `Web Map`, `Web Scene` |
| `dashboard` | `Dashboard` |
| `storymap` | `StoryMap`, or `Web Mapping Application` with a `storymap` keyword |
| `experience-builder`, `instant-app`, `web-appbuilder`, `web-app` | `Web Mapping Application` / `Application`, disambiguated by `typeKeywords` |
| `survey123-form` | `Form` |
| `field-maps`, `workforce`, `quickcapture` | field-operations apps |
| `notebook` | `Notebook` |
| `hosted-feature-layer` vs `referenced-feature-layer` | `Feature Service` with/without the `Hosted Service` keyword |
| `hosted-tile-layer`, `tile-layer`, `vector-tile-layer`, `image-layer`, `scene-layer`, `map-service` | tile / imagery / scene / map services |
| `unknown` | any unrecognized but well-formed item |

## DependencyEdge

A directed edge `{from, to, relation}`. `from` depends on / references `to`, so
`to` must be migrated **before** `from`.

| Field      | Required | Type   | Description |
|------------|----------|--------|-------------|
| `from`     | yes      | string | Node id that depends on `to`. |
| `to`       | yes      | string | Node id that must be migrated first. |
| `relation` | yes      | enum   | `webmap-references-service` or `service-contains-layer`. |

### Node identity

Edge endpoints are prospect-safe identifiers that already appear in (or are
derivable from) `inventory[]`:

- **Portal item** — the portal item id.
- **Server service** — the credential-free `serviceUrl`.
- **Server layer** — `"<serviceUrl>#<layerId>"`.

Edges never carry credentials, query strings, or raw on-prem paths.

## Producer behaviour

- **ArcGIS Online** — for each `Web Map` item, one `webmap-references-service`
  edge is emitted per dependency that resolves to another scanned portal item
  id. Edges to unscanned ids are dropped so every node stays present in the
  artifact.
- **ArcGIS Server** — for each retained service, one `service-contains-layer`
  edge per observed layer (`serviceUrl#<layerId>`).

Edges are de-duplicated and sorted deterministically. Sources with no
resolvable edges omit `dependencyEdges` entirely.

## Consuming edges for ordering

`honua_esri_assess.report.heuristics` exposes:

- `dependency_edges(footprint)` — validated edge mappings.
- `dependency_order(footprint)` — a deterministic Kahn topological sort of the
  node ids such that every `to` node precedes the `from` node that references
  it. Cycles are appended in sorted order rather than dropped, so the result
  always covers every referenced node.
