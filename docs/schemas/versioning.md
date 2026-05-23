# `EsriFootprint.json` Versioning Policy

Status: pre-1.0 (current line: `0.1.x`).
Companion: [Handoff contract](./handoff-contract.md).
Schema body: [`docs/schemas/esri-footprint.v0.1.md`](./esri-footprint.v0.1.md)
(JSON Schema at [`schemas/esri-footprint-v0.1.json`](../../schemas/esri-footprint-v0.1.json)).

## Scope

This policy governs the `EsriFootprint.json` artifact emitted by
`honua-esri-assess`. It is the sole supported handoff into the closed Honua
migration product.

The policy does **not** govern:

- CLI flags, argument names, or shell-level UX of `honua-esri-assess`.
- The CLI process-level stderr diagnostic codes (e.g. `scanner-error`,
  `output-write-failed`, `schema-validation-failed`, `report-input-failed`,
  `internal-error`). These describe local CLI process state and are separate
  from the locked artifact `diagnostics[].code` enum.
- The internal Python API (anything importable from `honua_esri_assess.*`).
- The layout, headings, or wording of the human-readable Markdown readiness
  report. The report is a derivative view of `EsriFootprint.json`, not a
  second handoff contract.
- Local log line formats.

Those surfaces may change without a schema version bump.

## Versioning model

The artifact carries a mandatory top-level field:

```json
{ "schemaVersion": "v0.1", "...": "..." }
```

`schemaVersion` is the contract `MAJOR.MINOR` line, carried in-band as a
literal (e.g. `"v0.1"`). The full SemVer for the specific schema build
(e.g. `0.1.0`) lives in the schema's `$id`; it is not duplicated in-band.
`schemaVersion` is set by the producer at emission time and is the single
source of truth for what shape the rest of the document takes.

### What bumps what

| Change | Pre-1.0 (`0.x.y`) | Post-1.0 (`>=1.0.0`) |
| --- | --- | --- |
| Doc-only clarification of an existing field | PATCH | PATCH |
| New optional key inside an explicitly open map | PATCH | MINOR |
| New field on the top-level artifact or any closed object | MINOR (breaking for strict v0.1 validators) | MINOR |
| New enum value the consumer is already required to tolerate | PATCH | PATCH |
| New required field | MINOR (breaking) | MAJOR |
| Field rename | MINOR (breaking) | MAJOR |
| Type narrowing (e.g., `string` → enum) | MINOR (breaking) | MAJOR |
| Removing a deprecated field after its notice window | MINOR (breaking) | MAJOR |
| Any change a strict consumer cannot ignore | MINOR (breaking) | MAJOR |

PATCH bumps are always non-breaking for a conforming consumer at every
release line, including pre-1.0.

### Pre-1.0 (v0.x) stance

Until the schema reaches `1.0.0`:

- **Minor bumps may break.** A move from `0.1.x` to `0.2.0` is allowed to
  rename fields, narrow types, or add required fields.
- **Patch bumps never break** within a minor line. `0.1.0` → `0.1.5` only
  clarifies docs, fixes producer bugs, or adds keys inside maps the v0.1
  schema already leaves open such as count-by-type maps.
- **Closed objects stay closed within a minor line.** Adding a new
  top-level field, facet field, inventory field, or diagnostic field would
  be rejected by a strict `0.1.x` validator and therefore requires the next
  minor line.
- **The producer guarantees no breaking changes within a minor line.** A
  consumer pinned to `0.1.x` will not be surprised by `0.1.5`.

This stance is intentionally honest: at v0.x we are still discovering the
shape of the artifact, and we would rather rev the minor than lock in a
mistake.

## Closed-product pinning (v0.x)

The closed Honua migration product declares the schema line it accepts by
pinning to an **exact `major.minor`** with a wildcard patch:

```
accepted_schema = "0.1.x"
```

The `x` is a literal wildcard, not a placeholder for a specific patch. Any
patch within the line is accepted, because the producer guarantees no
breaking changes within a minor line
(see [Pre-1.0 (v0.x) stance](#pre-10-v0x-stance)).

Behavior the closed product implements:

- Read `schemaVersion` from the incoming footprint. At v0.1 the literal
  in-band value is `"v0.1"`; the closed product compares it to its pinned
  major.minor directly.
- If the document's `major.minor` does not match the pinned `major.minor`,
  reject with a typed error. Pre-1.0, any minor mismatch — higher *or*
  lower — is incompatible: a `v0.2` document is not acceptable to a
  `0.1.x` pin. (Post-1.0, the same exact-match rule applies to `major`
  only; consumers accept any minor at or above the floor they choose.)
- Otherwise, accept the document. Patch differences are non-breaking by
  guarantee, so no patch-level state is encoded in the pin and patch is
  not carried in-band.

If a consumer needs to require a specific producer build (for example, to
guarantee a recent scanner-bug fix), it should read `tool.version` from
the artifact rather than encode a patch into the schema pin. The schema pin
is for shape compatibility only.

Adopting a new minor (`0.2.x`) is **opt-in** for the consumer; the producer
will keep publishing the previous line until the closed product is ready.

## Deprecation policy

A field is deprecated, not removed, on its first negative change. Lifecycle:

1. **Announce.** The schema marks the field with the JSON Schema
   `deprecated: true` annotation and a `description` that names the
   replacement (if any) and the earliest release that may remove it.
2. **Notice window.** The deprecated field stays in the schema for **at
   least one full minor release** beyond the release that announced the
   deprecation (e.g., deprecated in `0.1.4` → earliest removal is `0.3.0`,
   because `0.2.x` must carry it through).
3. **Runtime signal.** When the scanner would have populated a deprecated
   field, it emits a structured diagnostic into the footprint's
   `diagnostics[]` block (shape below). The field is still populated until
   removal. v0.1 ships with a locked vocabulary that does not yet include a
   deprecation-specific code — see [Diagnostics surface](#diagnostics-surface);
   a dedicated code (e.g. `schema.deprecation`) lands when the first
   deprecation does, on the same minor bump that opens the vocabulary.
4. **CHANGELOG entry.** Every deprecation and every removal lands as a
   dedicated `CHANGELOG.md` entry under the relevant release.
5. **Remove.** Removal lands on a MINOR (pre-1.0) or MAJOR (post-1.0) bump.

Deprecation enforcement is convention-only at v0.x. A CI gate that diffs
schemas across tags is a follow-on for the 1.0 milestone (see
[Follow-ons](#follow-ons)).

## Producer guarantees

Every `EsriFootprint.json` emitted by this tool:

- **Validates** against the JSON Schema published in this repo for its
  declared `schemaVersion`.
- **Identifies itself.** Top-level metadata, present on every footprint:
  - `schemaVersion` — major.minor of the contract, carried in-band as a
    literal (at v0.1, `"v0.1"`). Full SemVer is in the schema's `$id`.
  - `tool` — object with `name` (always `"honua-esri-assess"`) and
    `version` (the installed CLI build, as a SemVer string).
  - `generatedAt` — RFC3339 UTC timestamp of emission.
  - `source` — object identifying the Esri system kind: `kind` is one of
    `"arcgis-online"`, `"arcgis-server"`, `"filegdb"`, plus a
    prospect-safe `locator`. The block never contains credentials,
    tokens, cookies, session IDs, or raw on-prem paths; FileGDB locators
    are surfaced as a salted `sha256:<64 hex>` hash.
    ArcGIS Server v0.1 scans additionally record visited top-level service
    folder names and service counts by raw Esri service type in the
    `server` facet, and credential-free canonical service URLs in
    `inventory[].serviceUrl`. For filtered server scans, the folder list
    reflects the visited subset.
- **Comes from read-only access.** The producer never writes to the
  customer's Esri systems. No field in the artifact implies, records, or
  enables a write.
- **Carries no telemetry callback.** The artifact never embeds a callback
  URL, beacon, or remote logging endpoint. Network telemetry from the
  scanner itself is explicit and off by default; see
  [Network telemetry](#network-telemetry).

## Consumer expectations

A consumer of `EsriFootprint.json` (the closed migration product, or any
third-party reader) MUST:

- **Reject on incompatible major.** Refuse documents whose
  `schemaVersion` major differs from the pinned major. Pre-1.0, apply the
  same exact-match rule to `minor` — any minor mismatch (higher *or* lower)
  is incompatible. See
  [Closed-product pinning (v0.x)](#closed-product-pinning-v0x).
- **Tolerate unknown keys only in documented open maps.** At v0.1, unknown
  keys are allowed in count-by-type maps such as `portal.itemCounts` and
  `server.serviceCounts`; consumers must not treat those keys as
  load-bearing contract fields. Unknown top-level, facet, inventory,
  diagnostic, spatial-reference, extent, or field-descriptor fields are
  schema-rejected and require the next minor line.
- **Honor the source discriminator.** At v0.1, `source.kind` selects
  exactly one facet (`portal` | `server` | `filegdb`) and constrains the
  `inventory[]` variant. Sibling facets and mismatched inventory variants
  are schema-rejected. See
  [Discriminator rules](./esri-footprint.v0.1.md#discriminator-rules).
- **Not depend on object key ordering.** JSON object key order is not
  part of the contract.
- **Honor `diagnostics[]`.** Surface `warn`- and `error`-severity
  diagnostics to its own users; do not silently drop them.

## Diagnostics surface

Recoverable errors and warnings observed during scanning are surfaced inside
a successful footprint, not as raw exceptions or stack traces. The shape is a
top-level array of typed entries:

```json
{
  "diagnostics": [
    {
      "code": "missing-permission",
      "severity": "warn",
      "message": "Skipped 2 items the scanner credential cannot read.",
      "scope": "arcgis-online",
      "hint": "Re-run with a credential that has read access to the GIS Admin group."
    }
  ]
}
```

Each diagnostic carries:

- `code` — stable identifier drawn from a vocabulary fixed per release
  line. At v0.1 the vocabulary is **closed** (six codes; see the
  [v0.1 diagnostic code catalog](./esri-footprint.v0.1.md#diagnostic-code-catalog)).
  Adding a code requires a minor bump (a v0.2 vocabulary expansion);
  clarifying an existing code is a v0.1.x doc bump. This policy fixes the
  **shape** of a diagnostic; the **vocabulary** is owned by each release
  line's schema body.
- `severity` — one of `"info"`, `"warn"`, `"error"`.
- `message` — prospect-safe sentence. No tracebacks, no internal paths.
- `scope` — required identifier of the affected area (usually
  `source.kind`, a folder, or an `EsriItem` id).
- `hint` (optional) — remediation hint surfaced to the prospect.

The CLI never prints raw Python tracebacks to a customer. If a scanner returns
a result, the CLI exits `0`, writes `EsriFootprint.json`, and mirrors each
diagnostic to stderr as a typed line, even when the resulting inventory is
empty or partial. If a scanner fails before returning a result, or if the CLI
cannot read or save the requested artifact, it exits nonzero with a
prospect-safe typed diagnostic on stderr.

The stderr process-diagnostic vocabulary is deliberately separate from the
artifact `diagnostics[].code` vocabulary. Process codes such as
`scanner-error`, `report-input-failed`, `output-write-failed`,
`schema-validation-failed`, and `internal-error` describe command execution,
not source inventory observations, and are not valid values inside
`EsriFootprint.json`.
## Network telemetry

- **Off by default.** The scanner does not phone home, beacon, or post
  metrics to a remote endpoint as part of normal operation.
- **Explicit opt-in only.** Any future telemetry must be a documented
  CLI flag or environment variable, off by default, and disclosed in the
  README and this document.
- **Local logs are allowed.** Structured local logs on stderr and explicitly
  requested local output files are part of the normal operating surface and are
  not considered telemetry.
- **No telemetry inside the artifact.** `EsriFootprint.json` never
  carries a callback URL or remote endpoint.

## Follow-ons

The schema body for the current `0.1.x` line is published — see
[`docs/schemas/esri-footprint.v0.1.md`](./esri-footprint.v0.1.md) for the
field-by-field reference, the discriminator rules, and the locked v0.1
diagnostic code catalog. Remaining follow-ons:

- CI gate that diffs the published schema across tags and fails on an
  undeclared breaking change. Tracked for the 1.0 milestone.
- Field-level removal-eligible window stated in calendar time once we
  have a release cadence to anchor it to.
