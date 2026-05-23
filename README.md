# honua-esri-assess

Open-source Esri footprint assessment tooling for Honua migration discovery.

This repository owns the read-only scanner and report generator that produce a
versioned `EsriFootprint.json` artifact for the closed Honua migration product.
The tool is Apache-2.0 by design so prospects can audit the code before running
it against ArcGIS Online, ArcGIS Server, or FileGDB inventories.

## Current status

Shipped in this contract pass:

- `EsriFootprint.json` v0.1 JSON Schema and reference documentation.
- Canonical sample footprint and fixture-backed schema validation tests.
- Bootstrap `honua-esri-assess` CLI with `--version`.

Planned scanner and reporting work:

- Fixture-backed read-only ArcGIS Online Portal Sharing API smoke scanner.
- Fixture-backed read-only ArcGIS Server REST smoke scanner.
- Fixture-backed FileGDB inventory path using license-compatible dependencies.
- Markdown readiness report renderer smoke coverage.

## Command-line usage

The `honua-esri-assess` console script (and `python -m honua_esri_assess`)
exposes a `scan` subcommand per backend plus a `report` subcommand that
renders the resulting `EsriFootprint.json` to Markdown. Every subcommand is
**read-only** against the target Esri system — the CLI never issues a write,
posts telemetry, or contacts a Honua-operated service.

```
# ArcGIS Online (Portal Sharing REST base — the scanner appends portals/self,
# search, content/items/<id> directly to this URL).
honua-esri-assess scan agol \
  --target https://yourorg.maps.arcgis.com/sharing/rest \
  --output EsriFootprint.json

# ArcGIS Server REST endpoint.
honua-esri-assess scan server \
  --target https://gis.example.com/arcgis/rest \
  --output EsriFootprint.json

# FileGDB inventory (directory containing `_inventory.json`, or a descriptor file).
honua-esri-assess scan filegdb \
  --target ./sample.gdb \
  --output EsriFootprint.json

# Render the Markdown readiness report from a footprint.
honua-esri-assess report \
  --input EsriFootprint.json \
  --output report.md
```

The AGOL `--target` must be the Portal Sharing REST base (typically the URL
ending in `/sharing/rest`). The scanner appends endpoint paths (`portals/self`,
`community/groups`, `search`, `content/items/<id>`) directly to that base, so
passing a higher-level portal URL will produce `partial-coverage` diagnostics
instead of an inventory.

### Exit codes and failure surface

- Exit `0` — the scanner completed and the CLI wrote `EsriFootprint.json`.
  Any per-endpoint failure (HTTP 403/429, unreachable host, unsupported item
  type) is downgraded to a typed entry in `diagnostics[]` and also mirrored to
  stderr as `<code>: <message> [scope=<label>]`. Empty or partial inventories
  are still successful runs.
- Exit `1` — the scanner failed before returning a result or could not write
  the output file, such as on a read-only filesystem or permission-denied
  path. A single
  `partial-coverage: <typed message>` line is printed to stderr; no stack
  trace, internal path, or credential is leaked.
- Exit `2` — missing or invalid arguments (e.g., `scan` without a backend).

Diagnostics are always typed and prospect-safe; the CLI does not emit Python
tracebacks at any exit code.

## Schema and handoff

`EsriFootprint.json` is the sole supported handoff into the closed Honua
migration product. The v0.1 contract is published in this repository:

- Schema: [`schemas/esri-footprint-v0.1.json`](schemas/esri-footprint-v0.1.json)
- Reference: [`docs/schemas/esri-footprint.v0.1.md`](docs/schemas/esri-footprint.v0.1.md)
- Canonical sample: [`tests/fixtures/esri-footprint-sample.json`](tests/fixtures/esri-footprint-sample.json)

`$id`: `https://schemas.honua.io/esri-footprint/v0.1.0/esri-footprint.json`

The smoke suite validates every emitted footprint against that checked-in
schema using `jsonschema.Draft202012Validator`.

v0.x is unstable. Breaking changes are permitted between minor bumps; v1.0
is the first stable promise. See the reference doc for the stability
policy and the locked diagnostic code catalog.

Two policy docs govern the broader contract:

- [`docs/schemas/versioning.md`](docs/schemas/versioning.md) — semver
  interpretation, deprecation policy, producer guarantees, and consumer
  expectations for the artifact.
- [`docs/schemas/handoff-contract.md`](docs/schemas/handoff-contract.md) —
  prospect-facing summary of what flows between this tool and the closed
  product, and how to verify a footprint locally.

The schema body for the current `0.1.x` line is tracked under
[honua-io/honua-esri-assess#2](https://github.com/honua-io/honua-esri-assess/issues/2).

### Diagnostic code enum (v0.1)

`diagnostics[].code` is locked to the enum below in v0.1 — adding a new code
requires a schema bump and a parallel update to
`src/honua_esri_assess/diagnostics.py`:

- `rate-limited` — upstream returned HTTP 429; partial inventory returned.
- `partial-coverage` — endpoint unreachable, non-JSON, or otherwise refused.
- `missing-permission` — upstream returned HTTP 403 or an equivalent error
  envelope.
- `unresolved-reference` — referenced item could not be resolved.
- `unsupported-item-type` — item or service kind not modeled by v0.1.
- `redacted-field` — a field was withheld because it was sensitive.

## Running the smoke suite

The fixture-backed smoke suite under `tests/smoke/` exercises the full
`scan → EsriFootprint.json → Markdown report` pipeline without touching a live
Esri system. It is the contract guard that keeps the assessment tool aligned
with the `EsriFootprint.json` v0.1 schema between scanner edits.

```
python -m pip install -e ".[smoke]"
pytest tests/smoke -v
```

There are 9 tests covering the three scanner backends (AGOL happy +
diagnostics, ArcGIS Server happy + diagnostics, FileGDB happy), the Markdown
report renderer, the no-network guard, and a console-script smoke check. The
current corpus runs in well under a second on a developer laptop — the
sub-30-second wall-clock budget is the CI ceiling, not the target.

The suite uses `responses` to intercept the `requests` session and
`tests/smoke/test_no_network.py` monkeypatches `socket.socket.__init__` to
fail any outbound `AF_INET`/`AF_INET6` connection. That socket guard is the
structural enforcement of the "network telemetry must be explicit and off by
default" project constraint — fixtures alone would catch a scanner that hit
the wrong URL, but only the socket guard catches a scanner that bypassed the
mocked session entirely.

The CI workflow runs the smoke suite as a separate job so a smoke failure is
distinguishable from a unit-test failure in the PR status. See
[`tests/smoke/fixtures/README.md`](tests/smoke/fixtures/README.md) for the
fixture layout and refresh protocol.

## Decisions

- Language: Python.
- License: Apache-2.0.
- Runtime writes to customer Esri systems are out of scope.
- `EsriFootprint.json` follows semver, with a pre-1.0 stance that lets minor
  bumps break and guarantees no breaks within a minor line. See
  [`docs/schemas/versioning.md`](docs/schemas/versioning.md).

## Validating the schema locally

```bash
python -m pip install -e ".[dev]"
pytest
```

The test suite validates the published schema, the canonical sample, the
source-kind discriminator rules, prospect-safe URL/path constraints, and strict
RFC3339 UTC timestamps.
