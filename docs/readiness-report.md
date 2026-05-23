# Markdown Readiness Report

The readiness report is the human-readable companion to
`EsriFootprint.json`. It is not a second handoff contract for the closed Honua
migration product. The only machine contract remains the JSON footprint and
its published v0.1 schema.

The report is read-only by construction: it is rendered from an already
captured footprint and does not contact ArcGIS Online, ArcGIS Server, FileGDB
paths, Honua services, or any telemetry endpoint.

## CLI usage

```bash
honua-esri-assess report \
  --input EsriFootprint.json \
  --output readiness-report.md

honua-esri-assess report \
  --input docs/samples/esri-footprint.sample.json \
  --output -

cat EsriFootprint.json | honua-esri-assess report --input - --output -
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

By default, validation findings are rendered as a `Schema Warnings` section and
the report still exits successfully. If validation cannot run because the
installed package is incomplete, that validation-unavailable notice is also
rendered as a schema warning. Use `--strict` when an invalid footprint or
unavailable validator should fail before rendering:

```bash
honua-esri-assess report --input EsriFootprint.json --strict
```

For prospect-facing runs, leave `--debug` off so the stderr surface remains
typed and sanitized. The report command does not write customer Esri systems or
send network telemetry.

## Renderer API

```python
from honua_esri_assess.report import RenderOptions, render

markdown = render(footprint, options=RenderOptions(max_inventory_rows=500))
```

`render()` is a pure deterministic function: parsed footprint mapping in,
Markdown string out. It performs no file I/O, network I/O, logging, schema
loading, or schema validation. The CLI owns reading, writing, stdout/stderr,
logging setup, and validation.

`RenderOptions` controls:

- `include_diagnostics`: include the diagnostics summary section.
- `max_inventory_rows`: cap visible inventory rows and show a hidden-row note.
- `complexity_thresholds`: override item and layer thresholds for tests or
  future callers.
- `schema_warnings`: warnings to render under `Schema Warnings`.

## Report sections

The renderer emits these sections when data is available:

- `Honua Esri Readiness Report`: schema, source, capture time, and scanner
  provenance.
- `Schema Warnings`: best-effort validation findings supplied by the CLI.
- `Service Inventory`: grouped inventory rows for portal items, server
  services, or FileGDB feature classes.
- `Layer Count`: inventory total, server layer total, FileGDB feature class
  total, and source/type breakdowns.
- `Complexity Estimate`: Small, Medium, Large, or Very Large bucket with
  rationale.
- `Manual Review Items`: items flagged by v0.1 review heuristics.
- `Migration Ordering`: deterministic recommended ordering groups.
- `Diagnostics Summary`: diagnostic counts by severity/code plus detail lines.

## Heuristics

Complexity uses the highest bucket from inventory-record count and server-layer
count:

| Bucket | Inventory records | Server layers |
| --- | ---: | ---: |
| Small | <= 50 | <= 200 |
| Medium | <= 500 | <= 2,000 |
| Large | <= 5,000 | <= 20,000 |
| Very Large | > 5,000 | > 20,000 |

FileGDB feature class count, complex portal item types, diagnostic volume, and
multi-source inventory are reported in the rationale but do not raise the
complexity bucket by themselves.

Manual review reason codes are:

- `flagged-by-diagnostic`
- `complex-item-type`
- `unknown-item-type`
- `missing-spatial-reference`
- `legacy-spatial-reference`
- `unsupported-service-type`

Migration ordering is deterministic and groups data-like sources before
dependent maps, apps, dashboards, and specialized portal content:

1. FileGDB feature classes.
2. ArcGIS Server feature services.
3. ArcGIS Server map and image services.
4. AGOL hosted feature services.
5. AGOL hosted tile and vector tile services.
6. AGOL web maps.
7. AGOL web apps, dashboards, and experiences.
8. AGOL notebooks, solutions, workforce, survey, and insights.
9. Other or unknown item types.

## Failure contract

The report CLI emits typed, prospect-safe stderr lines. It does not expose raw
stack traces, credentials, customer paths, or internal exception text in the
default user-facing surface. `--debug` is a local development switch and may
include tracebacks.

| Exit | Meaning |
| ---: | --- |
| 0 | Report rendered successfully. Non-strict schema findings appear in `Schema Warnings`. |
| 2 | Input read, JSON parse, top-level shape, or output write failure. |
| 3 | `--strict` schema validation failure (`report.schema.invalid`). |
| 4 | Renderer/internal failure after input parsing succeeded (`report.render.internal`). |

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
