# honua-esri-assess

Open-source Esri footprint assessment tooling for Honua migration discovery.

This repository owns the read-only scanner and report generator that produce a
versioned `EsriFootprint.json` artifact for the closed Honua migration product.
The tool is Apache-2.0 by design so prospects can audit the code before running
it against ArcGIS Online, ArcGIS Server, or FileGDB inventories.

## Current status

Shipped in the current contract line:

- `EsriFootprint.json` v0.1 JSON Schema and reference documentation.
- Canonical sample footprint and fixture-backed schema validation tests.
- Typer-based `honua-esri-assess` CLI with `scan`, `schema`, `report`, and
  `version` commands.
- Fixture-backed read-only ArcGIS Online Portal Sharing API smoke scanner.
- Fixture-backed read-only ArcGIS Server REST smoke scanner.
- Fixture-backed FileGDB inventory descriptor scanner used by `scan filegdb`.
- `pyogrio`/GDAL FileGDB workspace scanner exposed as the
  `honua_esri_assess.filegdb` Python library (`scan_filegdb_workspace`).
- Markdown readiness report renderer smoke coverage.
- Separate CI smoke job that runs the fixture-backed pipeline without a live
  Esri system.
- Read-only entitlement enumeration available as a Python library
  (`honua_esri_assess.entitlements`) for prospective `scan` integration.
- PyPI release path through release-please and Trusted Publishing.
Still out of scope for this line:

- CI fixture refreshes against a live demo org or live ArcGIS Server.
- Any handoff artifact other than `EsriFootprint.json`.
- Network telemetry unless a future release adds an explicit opt-in control.
- Automatic attachment of entitlement observations to `scan agol` or
  `scan server` outputs. The v0.1 schema supports optional licensing blocks
  and the entitlements library is available for integration; the standalone
  `entitlements` CLI was retired alongside the E9 CLI consolidation.
- A dedicated CLI surface for the `pyogrio` FileGDB workspace scanner. The
  workspace scanner remains a library import; the `scan filegdb` CLI handler
  reads the fixture-backed `_inventory.json` descriptor path only.

## Quick start

Install the console script in an isolated Python 3.11+ environment:

```bash
pipx install honua-esri-assess
```

Run a read-only ArcGIS Online assessment and save the sole handoff artifact:

```bash
export AGOL_TOKEN="..."
honua-esri-assess scan agol \
  --target https://yourorg.maps.arcgis.com/sharing/rest \
  --token-env AGOL_TOKEN \
  --output EsriFootprint.json \
  --validate
```

Inspect or validate the bundled schema:

```bash
honua-esri-assess schema show
honua-esri-assess schema validate EsriFootprint.json
```
## Supported sources

| Source | CLI surface | Extra dependencies | Notes |
|--------|-------------|--------------------|-------|
| ArcGIS Online | `scan agol --target <portal-url-or-sharing-rest-url> --output EsriFootprint.json` | none | Uses the Portal Sharing REST API read-only. |
| ArcGIS Server | `scan server --target <rest-url> --output EsriFootprint.json` | none | Uses ArcGIS Server REST service metadata read-only. |
| FileGDB (descriptor) | `scan filegdb --target <path> --output EsriFootprint.json` | none | Reads `<path>/_inventory.json` when `<path>` is a directory, or the descriptor file directly. |
| FileGDB (workspace, library only) | `from honua_esri_assess.filegdb import scan_filegdb_workspace` | `filegdb` extra (`pyogrio`) | `pyogrio`/GDAL metadata calls against a local `.gdb` directory; no CLI surface yet. |

## Command-line usage

The `honua-esri-assess` console script (and `python -m honua_esri_assess`)
exposes a `scan` subcommand per backend plus `schema`, `report`, and `version`
subcommands. Every subcommand is **read-only** against the target Esri system.
The CLI never mutates Esri systems, posts telemetry, or contacts a
Honua-operated service.

```bash
# ArcGIS Online (Portal Sharing REST base — the scanner appends portals/self,
# search, content/items/<id> directly to this URL).
honua-esri-assess scan agol \
  --target https://yourorg.maps.arcgis.com/sharing/rest \
  --token-env AGOL_TOKEN \
  --output EsriFootprint.json

# ArcGIS Server REST endpoint.
honua-esri-assess scan server \
  --target https://gis.example.com/arcgis \
  --output EsriFootprint.json

# Fixture/descriptor FileGDB path used by the smoke harness.
honua-esri-assess scan filegdb \
  --target ./sample.gdb \
  --output EsriFootprint.json

# Render the Markdown readiness report from a footprint to a file.
honua-esri-assess report \
  --input EsriFootprint.json \
  --output readiness-report.md

# Render from stdin to stdout (default --output is `-`).
cat EsriFootprint.json | honua-esri-assess report --input -

# Fail instead of rendering schema findings as report warnings.
honua-esri-assess report \
  --input EsriFootprint.json \
  --strict
```

`scan` writes to `./EsriFootprint.json` by default. Pass `--validate` when the
CLI should validate the generated footprint against the bundled schema before
writing it; `schema validate EsriFootprint.json` performs the same validation
after the fact. `schema show` prints the bundled JSON Schema to stdout, and
`version` (or the root `--version` flag) prints both the package version and
bundled schema line (e.g., `honua-esri-assess 0.1.0` /
`EsriFootprint schema v0.1`).

Credential material is accepted only through `--token-env VAR`; the CLI reads
the named environment variable into memory for the selected backend and logs
the variable name, never the token value. There is intentionally no plaintext
`--token` option on the `scan` commands.

The AGOL `--target` must be the Portal Sharing REST base (typically the URL
ending in `/sharing/rest`). The scanner appends endpoint paths (`portals/self`,
`community/groups`, `search`, `content/items/<id>`) directly to that base, so
passing a higher-level portal URL will produce `partial-coverage` diagnostics
instead of an inventory.

The ArcGIS Server `--target` must be the REST base whose `services` child lists
the service catalog, typically `https://host/arcgis/rest`. The scanner appends
`services`, folder names, and service probes below that base.

The FileGDB `scan` handler reads a local descriptor only: either a directory
containing `_inventory.json` or a descriptor file supplied directly. It never
touches the network. The `pyogrio`/GDAL workspace scanner is exposed as the
`honua_esri_assess.filegdb.scan_filegdb_workspace` library function — it is not
wired to a CLI command in this release.

### Exit codes and failure surface

- Exit `0` — the scanner completed and the CLI wrote `EsriFootprint.json`,
  the report renderer wrote Markdown, or `schema validate` confirmed a
  footprint. Any per-endpoint failure (HTTP 403/429, unreachable host,
  unsupported item type) is downgraded to a typed entry in `diagnostics[]`
  inside the artifact and mirrored to stderr as a typed, prospect-safe
  diagnostic. Empty or partial inventories are still successful runs.
- Exit `2` — missing or invalid arguments, or report input/output/JSON handling
  failed with a typed `report.input.*` error.
- Exit `3` — `report --strict` rejected an invalid footprint
  (`report.schema.invalid`).
- Exit `4` — report rendering failed after input parsing succeeded
  (`report.render.internal`).
- Exit `10` or a backend-specific scanner exit — an expected scanner failure
  occurred before a requested output could be produced (`scanner-error`,
  `portal.*`, `server.*`).
- Exit `20` — the CLI could not save the requested output artifact
  (`output-write-failed`).
- Exit `30` — schema validation failed for `scan --validate` or
  `schema validate` (`schema-validation-failed`).
- Exit `1` — an unexpected internal error occurred (`internal-error`). Raw
  exception details are not printed.

Diagnostics are always typed and prospect-safe; the CLI does not emit Python
tracebacks at any exit code. CLI stderr diagnostics are process diagnostics
such as `scanner-error`, `output-write-failed`, `schema-validation-failed`,
`report.input.*`, `report.schema.invalid`, `report.render.internal`, and
`internal-error`; they are separate from the locked `EsriFootprint.json`
`diagnostics[].code` enum documented below.

## Telemetry

`honua-esri-assess` does not send network telemetry by default. The E9 CLI has
no usage ping, crash upload, or update-check sink. Local stderr logs can be
formatted as text or JSON with `--log-format`; typed diagnostics remain stderr
diagnostic lines. Both stay on the machine running the command.

`--no-network-telemetry-confirm` is an audit-friendly acknowledgement that the
invocation does not enable network telemetry. It is not a telemetry opt-in and
does not change scanner behavior.

Crash dumps are also off by default. Setting
`HONUA_ESRI_ASSESS_CRASH_DUMPS=1` allows the CLI to record a local redacted
diagnostic file under `~/.cache/honua-esri-assess/crashes/` after an unexpected
internal error.
## Schema and handoff

`EsriFootprint.json` is the sole supported handoff into the closed Honua
migration product. The v0.1 contract is published in this repository:

- Schema: [`schemas/esri-footprint-v0.1.json`](schemas/esri-footprint-v0.1.json)
- Reference: [`docs/schemas/esri-footprint.v0.1.md`](docs/schemas/esri-footprint.v0.1.md)
- Canonical sample: [`docs/samples/esri-footprint.sample.json`](docs/samples/esri-footprint.sample.json)
- Sample readiness report: [`docs/samples/readiness-report.sample.md`](docs/samples/readiness-report.sample.md)
- Readiness report guide: [`docs/readiness-report.md`](docs/readiness-report.md)

`$id`: `https://schemas.honua.io/esri-footprint/v0.1.0/esri-footprint.json`

The smoke suite validates every emitted footprint against that checked-in
schema using `jsonschema.Draft202012Validator`.

v0.x is unstable. Breaking changes are permitted between minor bumps; v1.0
is the first stable promise. See the reference doc for the stability policy
and the locked diagnostic code catalog.

Two policy docs govern the broader contract:

- [`docs/schemas/versioning.md`](docs/schemas/versioning.md) — semver
  interpretation, deprecation policy, producer guarantees, and consumer
  expectations for the artifact.
- [`docs/schemas/handoff-contract.md`](docs/schemas/handoff-contract.md) —
  prospect-facing summary of what flows between this tool and the closed
  product, and how to verify a footprint locally.

## ArcGIS Online scan

The AGOL scanner uses the documented Portal Sharing REST API in read-only mode.
It only issues `GET` requests against Esri systems and writes the local
`EsriFootprint.json` artifact.

Anonymous scans enumerate publicly visible content in the target org:

```shell
honua-esri-assess scan agol \
  --target https://example.maps.arcgis.com/sharing/rest \
  --output EsriFootprint.json
```

Token scans use a pre-existing ArcGIS Online token as a query-string
credential. The token is not written to the footprint, diagnostics, cache keys,
or logs. Supply the token through an environment variable:

```shell
export AGOL_TOKEN="..."
honua-esri-assess scan agol \
  --target https://example.maps.arcgis.com/sharing/rest \
  --token-env AGOL_TOKEN \
  --output EsriFootprint.json
```

The AGOL footprint emits `source.kind: "arcgis-online"`, a `portal` facet, and
`portal-item` inventory records. The current v0.1 emitter records item id, type,
owner, title, sharing, modified timestamp, optional extent, and an empty
`dependencies` list for scanned items. It does not expose AGOL service or layer
records in the artifact.

Anonymous scans skip organization-user enumeration and can emit an informational
`partial-coverage` diagnostic. Both anonymous and token scans attempt readable
group enumeration for coverage checks, but group records are not exposed as a
v0.1 artifact field. Token scans additionally attempt user counts under the
token's readable scope.

### Diagnostic code enum (v0.1)

Artifact `diagnostics[].code` is locked to the enum below in v0.1 — adding a
new code requires a schema bump and a parallel update to
`src/honua_esri_assess/diagnostics.py` and
`src/honua_esri_assess/entitlements/diagnostics.py`, plus any scanner emitter
mapping that normalizes subsystem-specific diagnostics into this vocabulary:

- `rate-limited` — upstream returned HTTP 429; partial inventory returned.
- `partial-coverage` — endpoint unreachable, non-JSON, or otherwise refused.
- `missing-permission` — upstream returned HTTP 403 or an equivalent error
  envelope.
- `unresolved-reference` — referenced item could not be resolved.
- `unsupported-item-type` — item or service kind not modeled by v0.1.
- `redacted-field` — a field was withheld because it was sensitive.

## Scanning an ArcGIS Server

The CLI exposes a `scan server` subcommand that walks the documented
ArcGIS Server REST API in read-only mode and writes `EsriFootprint.json`:

```
honua-esri-assess scan server \
    --target https://gis.example.com/arcgis \
    [--token-env SERVER_TOKEN] \
    [--output EsriFootprint.json] \
    [--timeout 30] \
    [--max-retries 3] \
    [--user-agent honua-esri-assess/0.1.0] \
    [--validate]
```

`--target` accepts any of `https://host`, `https://host/arcgis`,
`https://host/arcgis/rest`, or `https://host/arcgis/rest/services`; the
client canonicalizes to `<host>/arcgis/rest/services` internally. For custom
mounts, the supplied path is preserved and the `/rest/services` suffix is
appended when needed.

Behavior the scanner guarantees:

- **Read-only.** No `POST`/`PUT`/`DELETE` is issued against the target
  server. The HTTP wrapper exposes no write helpers; every call is a
  `GET` of the documented REST surface.
- **Two auth modes.** Anonymous (default), or a caller-supplied
  pre-existing ArcGIS Server token via `--token-env`. Tokens are appended as
  the outbound `token=` query param, redacted from log records, and never
  written into the footprint or stderr summary. URL userinfo, query
  strings, and fragments are stripped before writing `source.locator` or
  `ServerService.serviceUrl`.
- **Bounded retries.** Transient HTTP status (`429`, `502`, `503`, `504`)
  triggers exponential backoff for up to `--max-retries` retries after the
  first attempt. Retry sleep time is capped at 30 seconds; the per-request
  timeout is controlled separately by `--timeout`. A `Retry-After` header is
  honored within the retry sleep budget.
- **Two diagnostic surfaces.**
  - The CLI renders top-level failures as a single `error[code]` message
    line on stderr with a deterministic exit code (`server.auth`,
    `server.forbidden`, `server.not-found`, `server.rate-limited`,
    `server.connection`, `server.api`, `server.schema`). Python tracebacks
    are not printed in default mode.
  - Partial failures during the walk (forbidden folder, malformed
    service entry, failed service probe) emit prospect-safe records into the
    footprint's `diagnostics[]` block using the locked v0.1 diagnostic
    vocabulary (`missing-permission`, `partial-coverage`,
    `unsupported-item-type`, `rate-limited`); the scan continues where it
    can.
- **Service probe scope.** Service probes run by default to populate
  `inventory[].layerCount`. Supported probe types are `MapServer`,
  `FeatureServer`, `ImageServer`, `SceneServer`, and `StreamServer`; other
  types are recorded from the catalog walk only and emit `layerCount: 0`.
  The v0.1 footprint does not emit service capabilities, table counts, or
  the internal service-kind bucket.
- **No network telemetry.** Local logs (stderr) are structured;
  `--log-format` and `--log-level` control local process logs. No host other
  than the user-supplied `--target` is ever called.

`--output` defaults to `./EsriFootprint.json`; after writing the artifact, the
CLI prints a one-line scanned-item summary to stderr.

### ArcGIS Server footprint contract

A successful server scan emits `EsriFootprint.json` v0.1 with:

- `source.kind == "arcgis-server"`.
- `source.locator` set to the credential-free services-root URL
  (`https://host/arcgis/rest/services` for standard mounts) and
  `source.capturedAt` set to the scan timestamp.
- `server.folders[]` as the visited top-level folder names.
- `server.serviceCounts` keyed by raw ArcGIS Server service type and
  `server.version` when `/arcgis/rest/info` exposes it.
- `inventory[]` entries with `kind == "server-service"`, credential-free
  canonical `serviceUrl`, raw `serviceType`, `folder` (empty string for
  root services), and `layerCount`.
- `counts.items["server-service"]`, `counts.layers`, and
  `counts.featureClasses` roll-ups. `counts.featureClasses` remains `0`
  for ArcGIS Server footprints; it is reserved for FileGDB feature-class
  records.
- `diagnostics[]` typed entries for partial scan issues.

The v0.1 server scanner internally classifies raw ArcGIS Server service
types as follows for diagnostics and future emitters. The footprint does
not include a `serviceKind` field; consumers should read the raw
`serviceType`.

| Raw service type | Internal bucket | Deep probe |
| --- | --- | --- |
| `MapServer` | `mapService` | yes |
| `FeatureServer` | `featureService` | yes |
| `ImageServer` | `imageService` | yes |
| `SceneServer` | `sceneService` | yes |
| `StreamServer` | `streamService` | yes |
| `VectorTileServer` | `vectorTileService` | no |
| `GPServer` | `geoprocessingService` | no |
| `GeocodeServer` | `geocodeService` | no |
| `NAServer` | `networkAnalysisService` | no |
| `GeometryServer` | `geometryService` | no |
| `GlobeServer` | `globeService` | no |
| `MobileServer` | `mobileService` | no |
| anything else | `other` | no |

The emitter validates against the packaged copy of the published JSON Schema
at [`schemas/esri-footprint-v0.1.json`](schemas/esri-footprint-v0.1.json).
If validation rejects the output, or the declared schema cannot be loaded,
`scan server` exits non-zero before writing an artifact.

## Running the smoke suite

The fixture-backed smoke suite under `tests/smoke/` exercises the full
`scan → EsriFootprint.json → Markdown report` pipeline without touching a live
Esri system. It is the contract guard that keeps the assessment tool aligned
with the `EsriFootprint.json` v0.1 schema between scanner edits.

```bash
python -m pip install -e ".[smoke]"
pytest tests/smoke -v
```

There are 9 tests covering the three scanner backends (AGOL happy +
diagnostics, ArcGIS Server happy + diagnostics, FileGDB happy), the Markdown
report renderer, the no-network guard, and a console-script smoke check. The
current corpus runs in well under a second on a developer laptop — the
sub-30-second wall-clock budget is the CI ceiling, not the target.
The HTTP smoke tests use `responses` to intercept the `requests` session and
assert the registered fixture routes were exercised. The dedicated no-network
tests in `tests/smoke/test_no_network.py` also monkeypatch
`socket.socket.__init__` to fail outbound `AF_INET`/`AF_INET6` connections
while running a representative AGOL scan and the FileGDB path. Together those
checks enforce the "network telemetry must be explicit and off by default"
project constraint for the fixture-backed suite.

The CI workflow runs the smoke suite as a separate job so a smoke failure is
distinguishable from a unit-test failure in the PR status. See
[`tests/smoke/fixtures/README.md`](tests/smoke/fixtures/README.md) for the
fixture layout and refresh protocol.

## Decisions

- Language: Python.
- License: Apache-2.0.
- Runtime writes to customer Esri systems are out of scope.
- FileGDB metadata reads use the optional `pyogrio` backend (`MIT` license)
  through GDAL/OGR read-only metadata calls; no ELv2 closed-product code is
  vendored. The workspace scanner stays library-only in this release; the
  fixture-backed descriptor scanner remains the only FileGDB CLI surface.
- Network telemetry, usage pings, crash uploads, and update checks are off by
  default.
- `EsriFootprint.json` follows semver, with a pre-1.0 stance that lets minor
  bumps break and guarantees no breaks within a minor line. See
  [`docs/schemas/versioning.md`](docs/schemas/versioning.md).

## Validating the schema locally

```bash
python3 -m pip install -e ".[dev]"
pytest
```

The test suite validates the published schema, the canonical sample, the
source-kind discriminator rules, prospect-safe URL/path constraints, strict
RFC3339 UTC timestamps, the fixture-backed entitlement collectors, and the
readiness report renderer (heuristics, CLI failure surface, and the
byte-for-byte sample report golden file).

## Rendering a readiness report

```bash
honua-esri-assess report --input docs/samples/esri-footprint.sample.json
```

The report is a human-readable companion to `EsriFootprint.json`, not a second
handoff contract for the closed migration product. The renderer is pure: it
turns a parsed footprint dictionary into deterministic Markdown and performs no
file, network, logging, or Esri-system I/O. The CLI owns JSON parsing, packaged
schema validation, stdin/stdout support, and typed prospect-safe errors.

Use `--strict` to fail when the input does not validate against the published
v0.1 schema packaged with the CLI. Without `--strict`, schema validation
findings or validation-unavailable notices are rendered as a `Schema Warnings`
section so the report can still be reviewed.

The report includes a header, optional schema warnings, service inventory,
layer count, complexity estimate, manual-review items, migration ordering, and
diagnostics summary. See [`docs/readiness-report.md`](docs/readiness-report.md)
for CLI exit codes, report-section details, and v0.1 heuristics.
