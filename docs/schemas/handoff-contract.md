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
- No alternate entitlement handoff. The interim `entitlements` CLI prints a
  facet-compatible JSON fragment for validation, but the closed product does
  not ingest that fragment directly.
- No network telemetry. The scanner does not phone home; the artifact carries
  no callback URLs. Any future telemetry will be explicit, opt-in, and
  documented.
- No credentials. The artifact never contains tokens, cookies, passwords, or
  session IDs.

If a future deliverable needs to flow from the assessor to the closed
product, it either lands inside `EsriFootprint.json` (with a schema bump) or
it does not flow. There is no "small exception."

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
   equivalent RFC3339 checks enabled.
4. Inspect `diagnostics[]`. Treat `error`-severity entries as a failed
   scan; treat `warn`-severity entries as actionable but non-blocking.
   The v0.1 vocabulary is locked — see the
   [v0.1 diagnostic code catalog](./esri-footprint.v0.1.md#diagnostic-code-catalog).
5. Confirm `tool.name == "honua-esri-assess"` and the `source.kind`
   matches the target system the customer expected to scan.

No part of this verification requires contacting a Honua-operated service.

## FileGDB footprint path

The FileGDB scanner reads a local `.gdb` directory through the optional
`pyogrio`/GDAL metadata backend and writes the same sole handoff artifact:

```bash
python -m pip install -e ".[filegdb]"
honua-esri-assess filegdb /path/to/customer.gdb --output EsriFootprint.json
```

The command writes `EsriFootprint.json` by default; `--output -` writes the
same artifact to stdout. `--force-feature-count` asks the read-only backend
to compute `featureCount` values even when counting may be expensive.

The older `scan filegdb --target <path> --output <file>` surface is retained
for the fixture-backed descriptor scanner used by the smoke tests. It reads a
local `_inventory.json` descriptor and emits the same v0.1 FileGDB artifact
shape, but the production FileGDB metadata path is the top-level `filegdb`
command above.

The emitted `source.kind` is `"filegdb"` and the only source-specific facet
is `filegdb`; `portal` and `server` facets are schema-rejected. The raw
workspace path is never published. `source.locator` and
`filegdb.pathHash` carry the same salted `sha256:<64 hex>` value. Set
`HONUA_ESRI_ASSESS_PATH_HASH_SALT` or pass `--path-hash-salt` when stable
path hashes are needed across runs; otherwise the CLI uses a per-run random
salt.

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
  `community/groups`, `search`, `community/users` when token-authenticated,
  and optional ArcGIS Online hosted service metadata when `--deep` is enabled.
  The AGOL CLI also supports a per-request `--timeout`; that timeout only
  limits local waiting and does not change the handoff artifact shape.
- Pre-existing AGOL tokens are passed as query-string credentials to Esri only;
  they are redacted from diagnostics, logs, and the emitted footprint.
- No field in the artifact records or implies a write.
- The closed product is expected to honor the same read-only stance on
  any subsequent assessment passes that share this contract.

## Diagnostics, not stack traces

Recoverable failures during scanning are surfaced as typed entries in
`diagnostics[]` inside the artifact, not as Python tracebacks in the CLI output
or the footprint. A command can exit nonzero after writing an artifact when
the artifact contains `error`-severity diagnostics; the artifact remains the
handoff contract and should be inspected locally before upload. If the CLI
cannot produce or write the artifact, it exits nonzero with one prospect-safe
typed error line on stderr. Raw tracebacks are developer-only behavior behind
an explicit debug option, not the default customer surface. The artifact
diagnostic shape is fixed by the
[versioning policy](./versioning.md#diagnostics-surface); the vocabulary is
closed per release line. At v0.1 the catalog is locked to six codes; see the
[v0.1 diagnostic code catalog](./esri-footprint.v0.1.md#diagnostic-code-catalog).

For the FileGDB path, missing optional reader dependencies, invalid
workspaces, layer-listing failures, and per-layer metadata failures are
reported with the locked v0.1 diagnostic vocabulary. Exit-code meanings are
CLI-surface specific: the top-level `filegdb` workspace command exits `1`
after writing an artifact with any `error`-severity diagnostic and exits `2`
when it cannot produce or write a footprint. Older `scan ...` and `report`
surfaces also return nonzero on command-level failures, but callers should
treat `diagnostics[]` in the artifact as the authoritative failure surface
whenever an artifact exists.

## Readiness report

The Markdown readiness report is a human-facing companion to
`EsriFootprint.json`, not a second machine handoff contract. It is generated
from a parsed footprint and summarizes header metadata, schema warnings,
service inventory, layer counts, complexity, manual-review items, migration
ordering, and diagnostics without contacting Esri systems.

The renderer is a pure deterministic API: parsed `EsriFootprint.json` dict in,
Markdown string out. File reads, file writes, schema validation, stdout/stderr,
and local logging are owned by the CLI layer, not by
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
