# Markdown readiness report

The readiness report is the human-readable companion to
`EsriFootprint.json`. It helps a prospect review inventory, rough migration
complexity, manual-review flags, suggested sequencing, and diagnostics before
the footprint is handed to Honua.

It is **not** a second handoff contract. `EsriFootprint.json` remains the sole
machine-readable contract consumed by the closed Honua migration product. The
report is read-only by construction: it is rendered from an already captured
footprint and does not contact ArcGIS Online, ArcGIS Server, FileGDB paths,
Honua services, or any telemetry endpoint.

## Renderer contract

`honua_esri_assess.report.render()` accepts a parsed footprint mapping and
returns deterministic Markdown.

- The renderer performs no file, network, logging, or Esri-system I/O.
- The renderer does not validate or mutate the input footprint.
- The CLI owns JSON parsing, optional schema validation, input/output paths,
  logging, and prospect-safe error handling.
- The report wording, heading layout, and heuristic thresholds are not schema
  versioned. Changes to those surfaces do not change `schemaVersion`.

The committed sample report is generated from the canonical footprint:

- Footprint: [`docs/samples/esri-footprint.sample.json`](./samples/esri-footprint.sample.json)
- Report: [`docs/samples/readiness-report.sample.md`](./samples/readiness-report.sample.md)

The test suite compares the sample report byte-for-byte with freshly rendered
output.

## CLI usage

```bash
honua-esri-assess report \
  --input EsriFootprint.json \
  --output readiness-report.md

honua-esri-assess report \
  --input docs/samples/esri-footprint.sample.json \
  --output -

honua-esri-assess report --input - --output -
honua-esri-assess report --input EsriFootprint.json --strict
```

| Flag | Required | Description |
| --- | --- | --- |
| `--input` | yes | Path to `EsriFootprint.json`, or `-` to read JSON from stdin. |
| `--output` | no | Markdown output path, or `-` for stdout. Defaults to stdout. |
| `--strict` | no | Exit with a typed schema error when v0.1 validation fails. |
| `--verbose` | no | Enable local info logging. |
| `--debug` | no | Enable local debug logging and include tracebacks on errors. |

Schema validation uses the v0.1 schema packaged with the CLI and the runtime
`jsonschema` dependency. The published schema also remains available for audit
at [`schemas/esri-footprint-v0.1.json`](../schemas/esri-footprint-v0.1.json).

Without `--strict`, validation failures are rendered into a `Schema Warnings`
section and the report still exits successfully. If validation cannot run
because the installed package is incomplete, the validation-unavailable notice
is also rendered as a schema warning. `--strict` fails invalid footprints and
also fails with a typed schema error when validation cannot run.

For prospect-facing runs, leave `--debug` off so the stderr surface remains
typed and sanitized. The report command does not write customer Esri systems or
send network telemetry.

## Renderer API

```python
from honua_esri_assess.report import RenderOptions, render

markdown = render(footprint, options=RenderOptions(max_inventory_rows=500))
```

`RenderOptions` controls:

- `include_diagnostics`: include the diagnostics summary section.
- `max_inventory_rows`: cap visible inventory rows and show a hidden-row note.
- `complexity_thresholds`: override item and layer thresholds for tests or
  future callers.
- `schema_warnings`: warnings to render under `Schema Warnings`.

## CLI response contract

The report command prints sanitized, typed errors. It does not print raw Python
tracebacks unless `--debug` is set.

| Condition | Exit code | Output |
| --- | ---: | --- |
| Report rendered successfully | `0` | Markdown is written to `--output`; stdout is used only when `--output -`. |
| Input read, JSON parse, non-object JSON, or output write failure | `2` | `stderr` starts with `error: [report.input.read]`, `error: [report.input.parse]`, or `error: [report.input.write]`. |
| `--strict` schema validation failure | `3` | `stderr` starts with `error: [report.schema.invalid]`. |
| Renderer or unexpected internal failure | `4` | `stderr` starts with `error: [report.render.internal]`. |

Local logs are allowed through `--verbose` and `--debug`.

## Report sections

| Section | Purpose | Source fields |
| --- | --- | --- |
| Header | Identifies schema version, generation time, source, locator, capture time, and scanner build. | `schemaVersion`, `generatedAt`, `source`, `tool` |
| Schema Warnings | Lists validation issues or skipped-validation notices from the CLI. | CLI validation result |
| Service Inventory | Groups captured inventory by source family and item kind, then renders a stable table per group. | `inventory[]` |
| Layer Count | Shows total inventory records, server layers, FileGDB feature classes, and source/type breakdowns. | `counts`, facets, `inventory[]` |
| Complexity Estimate | Assigns a Small, Medium, Large, or Very Large bucket and explains the rationale. | `counts`, `inventory[]`, `diagnostics[]` |
| Manual Review Items | Flags entries that likely need human planning before migration. | `inventory[]`, scoped `diagnostics[]` |
| Migration Ordering | Suggests a deterministic high-level migration sequence. | `inventory[]` |
| Diagnostics Summary | Groups diagnostics by severity and code, then lists sanitized detail lines. | `diagnostics[]` |

## Complexity heuristic

The bucket is the higher of the item-count band and server-layer band.
Feature-class count, complex portal types, multiple source families, and
diagnostic volume are included in the rationale but do not raise the bucket by
themselves.

| Bucket | Inventory records | Server layers |
| --- | ---: | ---: |
| Small | `0-50` | `0-200` |
| Medium | `51-500` | `201-2,000` |
| Large | `501-5,000` | `2,001-20,000` |
| Very Large | `>5,000` | `>20,000` |

## Manual-review reasons

| Reason code | When it appears |
| --- | --- |
| `flagged-by-diagnostic` | A `warn` or `error` diagnostic is scoped to the item's `id`, `title`, `serviceUrl`, or `name`. |
| `complex-item-type` | A portal item is a specialized type such as `Experience`, `Geocoding Service`, `Geoprocessing Service`, `Insights Workbook`, `Locator Package`, `Notebook`, `Solution`, `Survey123 Form`, or `Workforce Project`. |
| `unknown-item-type` | A portal item type is `Other`, `Unknown`, `Unsupported`, or `Unsupported Item Type`. |
| `missing-spatial-reference` | A FileGDB feature class has no `wkid`, `latestWkid`, or `wkt` in its spatial reference. |
| `legacy-spatial-reference` | A FileGDB feature class uses a v0.1 watchlist WKID: `26711`, `32040`, or `102671`. |
| `unsupported-service-type` | An ArcGIS Server service type is outside `FeatureServer`, `ImageServer`, `MapServer`, or `VectorTileServer`. |

## Migration ordering

The ordering is advisory and deterministic. It helps readers plan review
passes; it does not add write or migration semantics to the footprint.

| Order | Group | Matching items |
| ---: | --- | --- |
| 1 | FileGDB feature classes | `filegdb-feature-class` |
| 2 | ArcGIS Server feature services | `server-service` with `serviceType: "FeatureServer"` |
| 3 | ArcGIS Server map and image services | `server-service` with `serviceType: "MapServer"` or `"ImageServer"` |
| 4 | AGOL hosted feature services | `portal-item` with `type: "Feature Service"` |
| 5 | AGOL hosted tile and vector tile services | `portal-item` with `type: "Tile Service"` or `"Vector Tile Service"` |
| 6 | AGOL web maps | `portal-item` with `type: "Web Map"` |
| 7 | AGOL web apps, dashboards, and experiences | `portal-item` with `type: "Dashboard"`, `"Experience"`, or `"Web Mapping Application"` |
| 8 | AGOL notebooks, solutions, workforce, survey, and insights | Portal items in the specialized manual-review set. |
| 9 | Other or unknown item types | Any remaining inventory item. |

## Samples and tests

- Canonical footprint:
  [`docs/samples/esri-footprint.sample.json`](./samples/esri-footprint.sample.json)
- Sample report:
  [`docs/samples/readiness-report.sample.md`](./samples/readiness-report.sample.md)
- Schema reference:
  [`docs/schemas/esri-footprint.v0.1.md`](./schemas/esri-footprint.v0.1.md)
- Handoff contract:
  [`docs/schemas/handoff-contract.md`](./schemas/handoff-contract.md)

The renderer golden test compares the committed sample report with freshly
rendered output so section order and deterministic formatting stay stable.
