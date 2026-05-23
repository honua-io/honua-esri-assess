# Handoff Contract: `EsriFootprint.json`

This document is the short, prospect-facing summary of what flows between the
open-source `honua-esri-assess` tool and the closed Honua migration product.

For semver rules, deprecation policy, and full producer/consumer contracts,
see [versioning.md](./versioning.md). The published JSON Schema body for the
current `0.1.x` line lives in
[`docs/schemas/esri-footprint.v0.1.md`](./esri-footprint.v0.1.md)
(schema file: [`schemas/esri-footprint-v0.1.json`](../../schemas/esri-footprint-v0.1.json),
canonical sample: [`docs/samples/esri-footprint.sample.json`](../samples/esri-footprint.sample.json)).

## The sole handoff

`EsriFootprint.json` is the **only** supported handoff into the closed Honua
migration product.

- No side-channel data exchange. The closed product does not call the
  customer's Esri systems on its own, does not consume scanner logs, and does
  not read CLI exit codes as a signal.
- No alternate entitlement handoff. The Python entitlement collectors
  (`honua_esri_assess.entitlements`) emit a facet-compatible JSON fragment for
  validation and prospective scanner integration, but the closed product does
  not ingest that fragment directly. The standalone `entitlements` CLI was
  retired in E9.
- No network telemetry. The scanner does not phone home; the artifact carries
  no callback URLs. Any future telemetry will be explicit, opt-in, and
  documented.
- No credentials. The artifact never contains tokens, cookies, passwords, or
  session IDs.

If a future deliverable needs to flow from the assessor to the closed
product, it either lands inside `EsriFootprint.json` (with a schema bump) or
it does not flow. There is no "small exception."

The Markdown readiness report produced by `honua-esri-assess report` is a
human-readable derivative of the footprint. It is not a closed-product input and
does not extend the handoff contract.

## What each side declares

**Producer (`honua-esri-assess`)** writes a top-level header on every emit:

```json
{
  "schemaVersion": "v0.1",
  "tool": { "name": "honua-esri-assess", "version": "<cli version>" },
  "generatedAt": "<RFC3339 UTC>",
  "source": { "kind": "arcgis-online|arcgis-server|filegdb", "locator": "<prospect-safe id>", "capturedAt": "<RFC3339 UTC>" }
}
```

At v0.1 the in-band `schemaVersion` is the literal major.minor `"v0.1"`;
the full SemVer for the schema build lives in the schema's `$id`. The
producer also writes a single matching facet (`portal`, `server`, or
`filegdb`) based on `source.kind`; sibling facets are schema-rejected
(see [Discriminator rules](./esri-footprint.v0.1.md#discriminator-rules)).
For Portal and Server footprints, the matching facet may include an optional
`licensing` block with read-only entitlement observations. Missing licensing
means the producer did not include entitlement enumeration in that footprint;
empty required arrays inside a present licensing block mean nothing was
observed or enumerable with the current credential.

For ArcGIS Server scans in the v0.1 line, the producer records a
credential-free services root in `source.locator` and writes the ArcGIS
Server details in the matching `server` facet:

```json
{
  "source": {
    "kind": "arcgis-server",
    "locator": "https://gis.example.com/arcgis/rest/services",
    "capturedAt": "2026-05-22T14:02:11Z"
  },
  "server": {
    "folders": ["Utilities", "Planning"],
    "serviceCounts": { "FeatureServer": 3, "MapServer": 9 },
    "version": "11.2"
  }
}
```

`source.locator` and each `ServerService.serviceUrl` strip URL userinfo,
query strings, and fragments before they can enter the artifact. Root-level
services are represented in `inventory[]` with `folder: ""`; folder services
carry their folder name. Each server service inventory record has
`kind: "server-service"`, raw `serviceType`, credential-free `serviceUrl`,
and `layerCount`. `server.folders` contains the folder names visited by the
scan. Version metadata sourced from `/arcgis/rest/info` is recorded in
`server.version` when available.

**Consumer (closed migration product)** pins to an exact `major.minor`
while the schema is pre-1.0, with a wildcard patch:

```
accepted_schema = "0.1.x"
```

The `x` is a literal wildcard. The consumer reads `schemaVersion` first
and rejects documents whose major differs from its pin; pre-1.0, the same
exact-match rule applies to `minor`, so a `0.1.x` pin rejects both higher
(`v0.2`) and lower (e.g. `v0.0`) minors. Any patch within the pinned minor
is accepted; patch is not carried in-band. See
[Closed-product pinning (v0.x)](./versioning.md#closed-product-pinning-v0x)
for the full state machine.

## What the closed product needs from each release line

Per release line, the closed product receives:

1. A tagged release of `honua-esri-assess` with a `schemaVersion` matching
   the release line (e.g., the `0.1.x` line emits `schemaVersion: "v0.1"`;
   patch lives in the schema `$id` and `tool.version`).
2. The JSON Schema body for that line under
   [`docs/schemas/`](./esri-footprint.v0.1.md) (published for v0.1).
3. A `CHANGELOG.md` entry summarizing what changed, including any
   deprecations and their planned removal window.
4. At least one canonical sample footprint under
   [`docs/samples/`](../samples/esri-footprint.sample.json)
   that the closed product can use as a conformance check, plus fixture
   corpora and golden expectations under `tests/smoke/` for scanner-backed
   conformance checks. Scanner-specific unit fixtures may live under
   `tests/<scanner>/` when they cover producer behavior that is not part of
   the cross-backend smoke corpus.

## Verifying a footprint before handoff

A prospect or the closed product can verify a footprint locally:

1. Check it parses as JSON.
2. Check `schemaVersion` matches the line the consumer accepts.
3. Validate against the published JSON Schema for that version
   ([`schemas/esri-footprint-v0.1.json`](../../schemas/esri-footprint-v0.1.json)
   for the current `0.1.x` line), with `date-time` format assertions or
   equivalent RFC3339 checks enabled. The bundled CLI exposes this directly:
   `honua-esri-assess schema validate EsriFootprint.json` exits `0` on a
   conforming footprint and `30` with a typed `schema-validation-failed`
   stderr diagnostic otherwise.
4. Inspect `diagnostics[]`. Treat `error`-severity entries as a failed
   scan; treat `warn`-severity entries as actionable but non-blocking.
   The v0.1 vocabulary is locked — see the
   [v0.1 diagnostic code catalog](./esri-footprint.v0.1.md#diagnostic-code-catalog).
5. Confirm `tool.name == "honua-esri-assess"` and the `source.kind`
   matches the target system the customer expected to scan.

No part of this verification requires contacting a Honua-operated service.
The Markdown report generated by `honua-esri-assess report` is a derivative
human-readable view; it is not part of the handoff contract and is not
ingested by the closed product.

## FileGDB footprint path

`scan filegdb --target <path> --output <file>` produces the FileGDB variant of
the sole handoff artifact. It reads a local descriptor — either a directory
containing `_inventory.json` or a descriptor file supplied directly — and emits
the same v0.1 FileGDB artifact shape. The CLI never touches the network.

The `pyogrio`/GDAL FileGDB workspace scanner is exposed as the
`honua_esri_assess.filegdb.scan_filegdb_workspace` Python library function.
It accepts `path_hash_salt` and `force_feature_count` options and returns the
same v0.1 footprint shape. The workspace scanner is library-only in the
current release; embedding it behind a CLI surface is a follow-on.

The emitted `source.kind` is `"filegdb"` and the only source-specific facet
is `filegdb`; `portal` and `server` facets are schema-rejected. The raw
workspace path is never published. `source.locator` and
`filegdb.pathHash` carry the same salted `sha256:<64 hex>` value. Set
`HONUA_ESRI_ASSESS_PATH_HASH_SALT` (or pass `path_hash_salt` to the library
function) when stable path hashes are needed across runs; otherwise a
per-run random salt is used.

FileGDB inventory records use `kind == "filegdb-feature-class"` and include
the reader's layer name, normalized Esri geometry type, spatial reference,
and any returned field or feature-count metadata. `filegdb.featureClassCount`,
`counts.items["filegdb-feature-class"]`, and `counts.featureClasses` all
count emitted FileGDB inventory records.

## Read-only stance

The producer is read-only against the customer's Esri systems. This is a
constraint of the assessment tool itself, not just a property of the
artifact:

- No write APIs are called against ArcGIS Online, ArcGIS Server, or any
  FileGDB.
- The AGOL producer uses Portal Sharing REST `GET` calls only. It normalizes
  organization URLs and `/sharing/rest` URLs, then reads `portals/self`,
  `community/groups`, `search`, and `community/users` when token-authenticated.
  The AGOL CLI also supports a per-request `--timeout`; that timeout only limits
  local waiting and does not change the handoff artifact shape.
- Pre-existing AGOL tokens are passed as query-string credentials to Esri only;
  they are redacted from diagnostics, logs, and the emitted footprint.
- No field in the artifact records or implies a write.
- The closed product is expected to honor the same read-only stance on
  any subsequent assessment passes that share this contract.

## Diagnostics, not stack traces

Recoverable failures during a successful scan are surfaced as typed entries in
`diagnostics[]` inside the artifact, not as Python tracebacks in the CLI output
or the footprint. If the CLI cannot produce or save the artifact, it exits
nonzero with a prospect-safe typed diagnostic on stderr. The
artifact diagnostic shape is fixed by the[versioning policy](./versioning.md#diagnostics-surface); the vocabulary is
closed per release line. At v0.1 the catalog is locked to six codes; see the
[v0.1 diagnostic code catalog](./esri-footprint.v0.1.md#diagnostic-code-catalog).

For the FileGDB workspace library function, missing optional reader
dependencies, invalid workspaces, layer-listing failures, and per-layer
metadata failures are reported with the locked v0.1 diagnostic vocabulary.

CLI process-level stderr diagnostics (`scanner-error`, `output-write-failed`,
`schema-validation-failed`, `report.input.*`, `report.schema.invalid`,
`report.render.internal`, `internal-error`) are **not** part of the schema enum.
They describe local CLI process state and never appear inside
`EsriFootprint.json`. The closed product reads the artifact and ignores CLI
stderr.

`honua-esri-assess schema validate EsriFootprint.json` is the supported local
validation command for prospects and for the closed product's ingest path. It
prints `valid: <path>` on success and exits with a typed process diagnostic on
schema or JSON-read failure.

## Readiness report

The Markdown readiness report is a human-facing companion to
`EsriFootprint.json`, not a second machine handoff contract. It is generated
from a parsed footprint and summarizes header metadata, schema warnings,
service inventory, layer counts, complexity, manual-review items, migration
ordering, and diagnostics without contacting Esri systems.

The renderer is a pure deterministic API: parsed `EsriFootprint.json` dict in,
Markdown string out. File reads, file writes, schema validation, and
stdout/stderr are owned by the CLI layer, not by
`honua_esri_assess.report.render()`.

`honua-esri-assess report` accepts `--input` as a path or `-` for stdin.
`--output` defaults to stdout and accepts `-` for stdout. The CLI validates
with the packaged v0.1 schema and runtime `jsonschema` dependency. By default,
schema validation failures or validation-unavailable notices are rendered as a
`Schema Warnings` section so a prospect can still review the footprint;
`--strict` fails the command with the typed `report.schema.invalid` error
instead. Input/output and JSON parsing failures use typed `report.input.*`
errors, and renderer failures use `report.render.internal`.

The sample report is published at
[`docs/samples/readiness-report.sample.md`](../samples/readiness-report.sample.md).
The renderer is deterministic, performs no I/O, and the test suite compares
the committed sample report byte-for-byte with freshly rendered output.

The `honua-esri-assess report` CLI handles JSON parsing, packaged v0.1 schema
validation, stdin/stdout, file output, local logging, and typed prospect-safe
errors. By default, validation issues are rendered into a `Schema Warnings`
section and the command exits successfully; with `--strict`, invalid v0.1
input exits with `report.schema.invalid`. The report guide documents the full
CLI response contract and the v0.1 report heuristics:
[`docs/readiness-report.md`](../readiness-report.md).

## Pointers

- Versioning policy: [versioning.md](./versioning.md)
- Schema body for v0.1: [`docs/schemas/esri-footprint.v0.1.md`](./esri-footprint.v0.1.md)
- Entitlement enumeration: [`../entitlements.md`](../entitlements.md)
- JSON Schema file: [`schemas/esri-footprint-v0.1.json`](../../schemas/esri-footprint-v0.1.json)
- Canonical sample: [`docs/samples/esri-footprint.sample.json`](../samples/esri-footprint.sample.json)
- Sample readiness report: [`docs/samples/readiness-report.sample.md`](../samples/readiness-report.sample.md)
- Readiness report guide: [`docs/readiness-report.md`](../readiness-report.md)
- Repository landing page: [`../../README.md`](../../README.md)
