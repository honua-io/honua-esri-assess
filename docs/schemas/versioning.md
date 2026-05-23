# `EsriFootprint.json` Versioning Policy

Status: pre-1.0 (current line: `0.1.x`).
Companion: [Handoff contract](./handoff-contract.md).
Schema body: `docs/schemas/esri-footprint.v0.1.md` (planned, see
honua-io/honua-esri-assess#2).

## Scope

This policy governs the `EsriFootprint.json` artifact emitted by
`honua-esri-assess`. It is the sole supported handoff into the closed Honua
migration product.

The policy does **not** govern:

- CLI flags, argument names, or shell-level UX of `honua-esri-assess`.
- The internal Python API (anything importable from `honua_esri_assess.*`).
- The layout, headings, or wording of the human-readable Markdown readiness
  report.
- Local log line formats.

Those surfaces may change without a schema version bump.

## Versioning model

The artifact carries a mandatory top-level field:

```json
{ "schemaVersion": "0.1.0", "...": "..." }
```

`schemaVersion` is a [semver](https://semver.org/) string `MAJOR.MINOR.PATCH`.
It is set by the producer at emission time and is the single source of truth
for what shape the rest of the document takes.

### What bumps what

| Change | Pre-1.0 (`0.x.y`) | Post-1.0 (`>=1.0.0`) |
| --- | --- | --- |
| Doc-only clarification of an existing field | PATCH | PATCH |
| New optional field with a safe default | PATCH | MINOR |
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
  adds optional fields, clarifies docs, or fixes producer bugs.
- **The producer guarantees no breaking changes within a minor line.** A
  consumer pinned to `0.1.x` will not be surprised by `0.1.5`.

This stance is intentionally honest: at v0.x we are still discovering the
shape of the artifact, and we would rather rev the minor than lock in a
mistake.

## Closed-product pinning (v0.x)

The closed Honua migration product declares the schema line it accepts by
pinning to an **exact minor**:

```
accepted_schema = "0.1.x"
```

Behavior the closed product implements:

- Read `schemaVersion` from the incoming footprint.
- If `major` is higher than the pinned major, reject with a typed error.
  (Pre-1.0, treat `minor` mismatch the same way: a `0.2.0` document is not
  acceptable to a `0.1.x` pin.)
- If `major.minor` matches the pin and `patch` is `>=` the pinned patch,
  accept.
- If `patch` is lower than the pinned patch, accept but log a warning; the
  producer is older than the consumer expects and may be missing optional
  diagnostics.

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
   field, it emits a structured diagnostic with code `schema.deprecation`
   into the footprint's `diagnostics[]` block (shape below). The field is
   still populated until removal.
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
  - `schemaVersion` — semver string, e.g. `"0.1.0"`.
  - `producer` — object with `name` (always `"honua-esri-assess"`) and
    `version` (the installed CLI version).
  - `generatedAt` — UTC ISO-8601 timestamp of emission.
  - `source` — object identifying the Esri system kind: `kind` is one of
    `"agol"`, `"arcgis-server"`, `"filegdb"`, plus a non-sensitive
    identifier (e.g., portal URL or FileGDB path basename). The block
    never contains credentials, tokens, cookies, or session IDs.
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
  `schemaVersion` major exceeds the pinned major. Pre-1.0, apply the same
  rule to `minor`.
- **Tolerate unknown additive fields** within a supported minor line. New
  optional fields are a PATCH-level change and may appear without notice.
- **Treat missing optional sections as absent**, not as an error. The
  scanner may omit sections it could not populate (e.g., `arcgisServer`
  on an AGOL-only scan).
- **Not depend on object key ordering.** JSON object key order is not
  part of the contract.
- **Honor `diagnostics[]`.** Surface deprecation and warning diagnostics
  to its own users; do not silently drop them.

## Diagnostics surface

Errors and warnings observed during scanning are surfaced inside the
footprint, not as raw exceptions or stack traces. The shape is a top-level
array of typed entries:

```json
{
  "diagnostics": [
    {
      "code": "schema.deprecation",
      "severity": "warning",
      "message": "Field `source.portalUrl` is deprecated; use `source.portal.url`.",
      "field": "source.portalUrl"
    }
  ]
}
```

Each diagnostic carries:

- `code` — stable, dotted identifier (e.g., `schema.deprecation`,
  `scan.partial`, `auth.scope.insufficient`). Codes are owned by the
  emitting scanner ticket; this policy only fixes the **shape**.
- `severity` — one of `"info"`, `"warning"`, `"error"`.
- `message` — prospect-safe sentence. No tracebacks, no internal paths.
- `field` (optional) — JSON pointer or dotted path to the affected
  field, when applicable.

The CLI never prints raw Python tracebacks to a customer; unrecoverable
failures still emit a footprint with `diagnostics[]` and a terminating
`error`-severity entry whenever the producer can do so safely.

## Network telemetry

- **Off by default.** The scanner does not phone home, beacon, or post
  metrics to a remote endpoint as part of normal operation.
- **Explicit opt-in only.** Any future telemetry must be a documented
  CLI flag or environment variable, off by default, and disclosed in the
  README and this document.
- **Local logs are allowed.** Structured local logs (stderr or
  `reports/`) are part of the normal operating surface and are not
  considered telemetry.
- **No telemetry inside the artifact.** `EsriFootprint.json` never
  carries a callback URL or remote endpoint.

## Follow-ons

- CI gate that diffs the published schema across tags and fails on an
  undeclared breaking change. Tracked for the 1.0 milestone.
- Field-level removal-eligible window stated in calendar time once we
  have a release cadence to anchor it to.
- The schema body itself, including the `schemaVersion` field and the
  `diagnostics[]` JSON Schema definition, lands under
  [honua-io/honua-esri-assess#2](https://github.com/honua-io/honua-esri-assess/issues/2).
