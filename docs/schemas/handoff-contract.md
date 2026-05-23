# Handoff Contract: `EsriFootprint.json`

This document is the short, prospect-facing summary of what flows between the
open-source `honua-esri-assess` tool and the closed Honua migration product.

For semver rules, deprecation policy, and full producer/consumer contracts,
see [versioning.md](./versioning.md). The JSON Schema body lives in
`docs/schemas/esri-footprint.v0.1.md` (planned, see
honua-io/honua-esri-assess#2).

## The sole handoff

`EsriFootprint.json` is the **only** supported handoff into the closed Honua
migration product.

- No side-channel data exchange. The closed product does not call the
  customer's Esri systems on its own, does not consume scanner logs, and does
  not read CLI exit codes as a signal.
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
  "schemaVersion": "0.1.0",
  "producer": { "name": "honua-esri-assess", "version": "<cli version>" },
  "generatedAt": "<UTC ISO-8601>",
  "source": { "kind": "agol|arcgis-server|filegdb", "...": "..." }
}
```

**Consumer (closed migration product)** pins to an exact minor while the
schema is pre-1.0:

```
accepted_schema = "0.1.x"
```

The consumer reads `schemaVersion` first and rejects documents whose major
(or pre-1.0, minor) exceeds its pin. See
[Closed-product pinning (v0.x)](./versioning.md#closed-product-pinning-v0x)
for the full state machine.

## What the closed product needs from each release line

Per release line, the closed product receives:

1. A tagged release of `honua-esri-assess` with a `schemaVersion` matching
   the release line (e.g., the `0.1.x` line emits `0.1.*`).
2. The JSON Schema body for that line under `docs/schemas/` (planned for
   v0.1 via #2).
3. A `CHANGELOG.md` entry summarizing what changed, including any
   deprecations and their planned removal window.
4. Sample footprints under `tests/fixtures/` (planned per the scanner
   tickets) that the closed product can use as conformance checks.

## Verifying a footprint before handoff

A prospect or the closed product can verify a footprint locally:

1. Check it parses as JSON.
2. Check `schemaVersion` matches the line the consumer accepts.
3. Validate against the published JSON Schema for that version (see #2).
4. Inspect `diagnostics[]`. Treat `error`-severity entries as a failed
   scan; treat `warning`-severity entries (including
   `schema.deprecation`) as actionable but non-blocking.
5. Confirm `producer.name == "honua-esri-assess"` and the `source.kind`
   matches the target system the customer expected to scan.

No part of this verification requires contacting a Honua-operated service.

## Read-only stance

The producer is read-only against the customer's Esri systems. This is a
constraint of the assessment tool itself, not just a property of the
artifact:

- No write APIs are called against ArcGIS Online, ArcGIS Server, or any
  FileGDB.
- No field in the artifact records or implies a write.
- The closed product is expected to honor the same read-only stance on
  any subsequent assessment passes that share this contract.

## Diagnostics, not stack traces

Failures during scanning are surfaced as typed entries in `diagnostics[]`
inside the artifact, not as Python tracebacks in the CLI output or the
footprint. The shape is fixed by the schema; codes are owned by the
emitting scanner. See
[Diagnostics surface](./versioning.md#diagnostics-surface).

## Pointers

- Versioning policy: [versioning.md](./versioning.md)
- Schema body for v0.1: planned, see
  [honua-io/honua-esri-assess#2](https://github.com/honua-io/honua-esri-assess/issues/2)
- Repository landing page: [`../../README.md`](../../README.md)
