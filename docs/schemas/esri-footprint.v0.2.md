# EsriFootprint.json v0.2

`esri-footprint/v0.2` is an **additive, back-compatible** revision of
[`v0.1`](./esri-footprint.v0.1.md). It populates the dependency edges the v0.1
schema reserved but left empty so batch orchestration can order migrations
(webmap → service → layer). Everything documented for v0.1 still applies;
this page covers only the delta.

The canonical schema lives at
[`schemas/esri-footprint-v0.2.json`](../../schemas/esri-footprint-v0.2.json),
mirrored as a package resource at
`src/honua_esri_assess/schemas/esri-footprint-v0.2.json`.

## What changed from v0.1

| Change | Detail |
|--------|--------|
| `schemaVersion` | Now accepts `"v0.1"` **or** `"v0.2"`. v0.2 producers emit `"v0.2"`; v0.1 artifacts still validate against the v0.2 reader. |
| `dependencyEdges` | New **optional** top-level array of [`DependencyEdge`](#dependencyedge). Absent or empty when no edges resolve. |

No fields were removed, renamed, or made stricter. A v0.1 artifact is a valid
v0.2 artifact, and a v0.1 reader can ignore the unknown `dependencyEdges` key,
so the bump is back-compatible in both directions.

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
