# honua-esri-assess

Open-source Esri footprint assessment tooling for Honua migration discovery.

This repository owns the read-only scanner and report generator that produce a
versioned `EsriFootprint.json` artifact for the closed Honua migration product.
The tool is Apache-2.0 by design so prospects can audit the code before running
it against ArcGIS Online, ArcGIS Server, or FileGDB inventories.

## Current status

Shipped in the current contract line:

| Area | Status | Contract surface |
| --- | --- | --- |
| Schema | `EsriFootprint.json` v0.1 schema and reference docs | Sole handoff artifact |
| Canonical sample | Single-source-of-truth footprint plus rendered readiness report | [`docs/samples/esri-footprint.sample.json`](docs/samples/esri-footprint.sample.json), [`docs/samples/readiness-report.sample.md`](docs/samples/readiness-report.sample.md) |
| Scanner CLI | Read-only AGOL Portal Sharing API, ArcGIS Server, and FileGDB scans | Full `EsriFootprint.json` |
| FileGDB workspace CLI | Read-only `pyogrio`/GDAL inventory of a local `.gdb` | Full `EsriFootprint.json` |
| Report CLI | Pure deterministic Markdown readiness report renderer with smoke coverage | Human-readable companion (no second machine contract) |
| Smoke CI | Separate fixture-backed job without live Esri access | Local contract guard |
| Entitlements | Read-only library and interim `entitlements` CLI for Portal and Server licensing | Facet-compatible JSON fragment |

Still out of scope for this line:

- CI fixture refreshes against a live demo org or live ArcGIS Server.
- Any handoff artifact other than `EsriFootprint.json`.
- Network telemetry unless a future release adds an explicit opt-in control.
- Automatic attachment of entitlement observations to `scan agol` or
  `scan server` outputs. The v0.1 schema supports optional licensing blocks,
  and the interim `entitlements` CLI validates that shape until scanner
  integration lands.
- Any write, mutate, migrate, or publish operation against Esri systems.

## Supported sources

| Source | CLI surface | Extra dependencies | Notes |
|--------|-------------|--------------------|-------|
| ArcGIS Online | `scan agol --target <portal-url-or-sharing-rest-url> --output EsriFootprint.json` | none | Uses the Portal Sharing REST API read-only. |
| ArcGIS Server | `scan server --target <rest-url> --output EsriFootprint.json` | none | Uses ArcGIS Server REST service metadata read-only. |
| FileGDB | `filegdb <workspace.gdb> --output EsriFootprint.json` | `filegdb` extra | Uses `pyogrio`/GDAL metadata calls against a local `.gdb` directory. |

Compatibility note: `scan filegdb --target <path> --output <file>` remains
available for the fixture-backed descriptor scanner used by the smoke harness.
It reads `<path>/_inventory.json` when `<path>` is a directory, or treats
`<path>` as the descriptor file when it is a file. For real FileGDB
inventories, use the top-level `filegdb` command above.

## Command-line usage

The `honua-esri-assess` console script (and `python -m honua_esri_assess`)
exposes `scan`, `filegdb`, `report`, and interim `entitlements` subcommands.
The tool is read-only against Esri systems: the scanner and entitlement
collectors issue GET requests only, never write to ArcGIS Online / Enterprise
Portal or ArcGIS Server, and never contact a Honua-operated service. The
report subcommand is purely a local renderer; it does not contact Esri or
Honua endpoints.

```bash
# ArcGIS Online. Target may be the org URL or its /sharing/rest URL.
honua-esri-assess scan agol \
  --target https://yourorg.maps.arcgis.com \
  --output EsriFootprint.json

# ArcGIS Online with a pre-existing token and optional hosted-service probes.
honua-esri-assess scan agol \
  --target https://yourorg.maps.arcgis.com \
  --token "$AGOL_TOKEN" \
  --deep \
  --output EsriFootprint.json

# ArcGIS Server REST endpoint.
honua-esri-assess scan server \
  --target https://gis.example.com/arcgis/rest \
  --output EsriFootprint.json

# FileGDB inventory from a local .gdb directory.
python -m pip install -e ".[filegdb]"
honua-esri-assess filegdb ./sample.gdb \
  --output EsriFootprint.json

# FileGDB inventory to stdout.
honua-esri-assess filegdb ./sample.gdb --output -

# Fixture/descriptor compatibility path used by the smoke harness.
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

The AGOL `scan` target accepts either the organization base URL
(`https://yourorg.maps.arcgis.com`) or the Portal Sharing REST base ending in
`/sharing/rest`. The scanner normalizes that target before issuing GET-only
requests to `portals/self`, `community/groups`, `search`, and, for token
scans, `community/users`. With `--deep`, it may also GET hosted service URLs
under ArcGIS Online; external service URLs are not fetched. AGOL `--output`
defaults to stdout, and `--timeout` controls the per-request Portal timeout.

The top-level `filegdb` command requires a local directory whose name ends in
`.gdb`. The raw workspace path is never published. `source.locator` and
`filegdb.pathHash` are the same salted `sha256:<64 hex>` value. Set
`HONUA_ESRI_ASSESS_PATH_HASH_SALT` or pass `--path-hash-salt` when stable
hashes are needed across runs; without a salt, the command uses a random
in-memory salt for that run. Pass `--force-feature-count` to ask the
read-only backend to calculate feature counts even when the backend considers
that expensive.

FileGDB inventory records use `kind: "filegdb-feature-class"` and include the
feature class `name`, `geometryType`, spatial reference (`sr`), optional
`featureCount`, and optional minimal `fields` metadata. Reader dependency,
workspace, and per-layer failures are emitted as typed, prospect-safe
`diagnostics[]`; raw paths, credentials, stack traces, and raw exception text
are not copied into the artifact.

The `report` command accepts `--input` as a path or `-` for stdin. `--output`
defaults to stdout and also accepts `-` for stdout. `--strict` fails when the
input does not validate against the published v0.1 schema packaged with the
CLI; without `--strict`, schema validation findings or validation-unavailable
notices are rendered in a `Schema Warnings` section so the report can still be
reviewed. `--verbose` enables local info logging. `--debug` is a local
development switch that enables debug logging and may include tracebacks on
errors; leave it off for prospect-facing runs. The renderer never contacts
Esri systems or sends network telemetry.

See [`docs/readiness-report.md`](docs/readiness-report.md) for the full report
section catalog, heuristics (complexity buckets, manual-review reason codes,
migration ordering), renderer API, and failure contract.

## Entitlement enumeration

E6 adds read-only entitlement collection for Esri license and extension data.
The standalone CLI is an interim validation surface: it prints a JSON fragment
whose nested `portal.licensing` or `server.licensing` object matches the
`EsriFootprint.json` v0.1 schema, but the JSON printed by this command is not
itself the closed-product handoff contract.

```bash
# ArcGIS Online / Enterprise Portal. The target is the portal base URL, not
# the /sharing/rest base used by scan agol.
honua-esri-assess entitlements agol \
  --target https://www.arcgis.com \
  --token "$ESRI_TOKEN"

# Anonymous mode skips token-required subscription/user-license endpoints and
# records missing-permission diagnostics.
honua-esri-assess entitlements agol \
  --target https://www.arcgis.com \
  --anonymous

# ArcGIS Server. The target is the ArcGIS Server root.
honua-esri-assess entitlements server \
  --target https://gis.example.com/arcgis \
  --token "$ESRI_TOKEN"

# Limit service-extension enumeration to known services, or skip it entirely.
honua-esri-assess entitlements server \
  --target https://gis.example.com/arcgis \
  --service Hosted/Parcels.MapServer \
  --service World.MapServer

honua-esri-assess entitlements server \
  --target https://gis.example.com/arcgis \
  --no-service-extensions
```

The response shape is:

```json
{
  "target": "agol",
  "licensing": {
    "portal": {
      "licensing": {
        "tier": "online",
        "subscriptionType": "Subscription",
        "userTypes": [{ "name": "creatorUT", "total": 50, "assigned": 32 }],
        "premiumContent": {
          "creditsEnabled": true,
          "allowedAddOns": ["hub", "premiumContent"]
        },
        "extensionsObserved": [
          {
            "code": "Spatial",
            "name": "Spatial Analyst",
            "status": "licensed",
            "source": "portal-subscription"
          }
        ]
      }
    }
  },
  "diagnostics": []
}
```

For Server targets the response uses `licensing.server.licensing` with
`productName`, `currentVersion`, `edition`, `extensions`, and
`serviceExtensions`. Optional scalar fields are omitted when the Esri endpoint
does not expose them. Required arrays are present and may be empty when
nothing is observed, permission is missing, or service-extension lookup is
disabled.

Detailed endpoint coverage and developer integration notes are in
[`docs/entitlements.md`](docs/entitlements.md).

### Exit codes and failure surface

Exit codes are an operator convenience, not the handoff contract. The closed
product should inspect `EsriFootprint.json` and `diagnostics[]`, not infer
contract state from a shell status.

### Scanner exit codes and failure surface

- Exit `0` - the scanner completed and wrote `EsriFootprint.json`. Recoverable
  per-endpoint failures (HTTP 403/429, unreachable host, unsupported item
  type) are downgraded to typed entries in `diagnostics[]` and mirrored to
  stderr as `<code>: <message> [scope=<label>]`. Empty or partial inventories
  are still successful runs.
- Exit `1` - the scanner failed before returning a result or could not write
  the output file, such as on a read-only filesystem or permission-denied
  path. A single `partial-coverage: <typed message>` line is printed to
  stderr; no stack trace, internal path, or credential is leaked.
- Exit `2` - missing or invalid arguments, such as `scan` without a backend.
- Exit `20`-`27` - the AGOL scanner failed before producing a footprint with
  a typed Portal error (`portal.error`, `portal.auth`, `portal.forbidden`,
  `portal.not-found`, `portal.rate-limited`, `portal.connection`,
  `portal.api`, or `portal.schema`).

### FileGDB workspace exit codes and failure surface

- Exit `0` - the top-level `filegdb` workspace command wrote
  `EsriFootprint.json` without `error`-severity diagnostics.
- Exit `1` - the command wrote an artifact that contains at least one
  `error`-severity diagnostic. The artifact remains the handoff contract.
- Exit `2` - the command could not produce or write a footprint.

### Report exit codes and failure surface

The report CLI emits typed, prospect-safe stderr lines of the form
`error: [<code>] <message>`. `--debug` is a local development switch and may
include tracebacks; default runs never expose stack traces, credentials, or
internal paths.

- Exit `0` - the report rendered successfully. Non-strict schema findings are
  included in the Markdown under `Schema Warnings`.
- Exit `2` - the input footprint could not be read (`report.input.read`), the
  input was not JSON, the top-level JSON value was not an object
  (`report.input.parse`), or the rendered report could not be written
  (`report.input.write`).
- Exit `3` - `--strict` was set and v0.1 schema validation failed
  (`report.schema.invalid`).
- Exit `4` - rendering failed after input parsing succeeded
  (`report.render.internal`).

### Entitlements exit codes and failure surface

- Exit `0` - the entitlement collector wrote JSON to stdout. Recoverable
  observations land in `diagnostics[]` inside the fragment.
- Exit `1` - unexpected failure before producing an output. Stderr stays
  prospect-safe.
- Exit `2` - missing or invalid arguments, such as `entitlements` without
  `agol` or `server`.
- Exit `3` - typed hard failure such as auth, forbidden, not found, rate
  limit, connection, API, or schema parse failure. The stderr message is
  prospect-safe; `--debug` re-raises for local development.

Diagnostics are always typed and prospect-safe across all CLI surfaces.
Customer-facing runs do not emit Python tracebacks, credentials, or raw
filesystem paths.

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

- [`docs/schemas/versioning.md`](docs/schemas/versioning.md) - semver
  interpretation, deprecation policy, producer guarantees, and consumer
  expectations for the artifact.
- [`docs/schemas/handoff-contract.md`](docs/schemas/handoff-contract.md) -
  prospect-facing summary of what flows between this tool and the closed
  product, and how to verify a footprint locally.

## ArcGIS Online scan

The AGOL scanner uses the documented Portal Sharing REST API in read-only mode.
It only issues `GET` requests against Esri systems and writes the local
`EsriFootprint.json` artifact, or stdout when `--output` is omitted or set to
`-`.

Anonymous scans enumerate publicly visible content in the target org:

```shell
honua-esri-assess scan agol \
  --target https://example.maps.arcgis.com \
  --output EsriFootprint.json
```

Token scans use a pre-existing ArcGIS Online token as a query-string
credential. The token is not written to the footprint, diagnostics, cache keys,
or logs:

```shell
honua-esri-assess scan agol \
  --target https://example.maps.arcgis.com \
  --token "$AGOL_TOKEN" \
  --output EsriFootprint.json
```

The AGOL footprint emits `source.kind: "arcgis-online"`, a `portal` facet, and
`portal-item` inventory records. The current v0.1 emitter records item id, type,
owner, title, sharing, modified timestamp, optional extent, and an empty
`dependencies` list for scanned items. It does not expose AGOL service or layer
records in the artifact; `--deep` only performs read-only hosted-service probes
for scanner coverage and diagnostics.

Anonymous scans skip organization-user enumeration and can emit an informational
`partial-coverage` diagnostic. Both anonymous and token scans attempt readable
group enumeration for coverage checks, but group records are not exposed as a
v0.1 artifact field. Token scans additionally attempt user counts under the
token's readable scope.

### Diagnostic code enum (v0.1)

`diagnostics[].code` is locked to the enum below in v0.1. Adding a new code
requires a schema bump and a parallel update to
`src/honua_esri_assess/diagnostics.py` and
`src/honua_esri_assess/entitlements/diagnostics.py`, plus any scanner emitter
mapping that normalizes subsystem-specific diagnostics into this vocabulary:

- `rate-limited` - upstream returned HTTP 429; partial inventory returned.
- `partial-coverage` - endpoint unreachable, non-JSON, or otherwise refused.
- `missing-permission` - upstream returned HTTP 403 or an equivalent error
  envelope.
- `unresolved-reference` - referenced item could not be resolved.
- `unsupported-item-type` - item or service kind not modeled by v0.1.
- `redacted-field` - a field was withheld because it was sensitive.

## Running the smoke suite

The fixture-backed smoke suite under `tests/smoke/` exercises the full
`scan -> EsriFootprint.json -> Markdown report` pipeline without touching a
live Esri system. It is the contract guard that keeps the assessment tool
aligned with the `EsriFootprint.json` v0.1 schema between scanner edits.

```bash
python -m pip install -e ".[smoke]"
pytest tests/smoke -v
```

There are 9 tests covering the three scanner backends (AGOL happy plus
diagnostics, ArcGIS Server happy plus diagnostics, FileGDB happy), the
Markdown report renderer, the no-network guard, and a console-script smoke
check. The current corpus runs in well under a second on a developer laptop;
the sub-30-second wall-clock budget is the CI ceiling, not the target.

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
  vendored.
- `EsriFootprint.json` follows semver, with a pre-1.0 stance that lets minor
  bumps break and guarantees no breaks within a minor line. See
  [`docs/schemas/versioning.md`](docs/schemas/versioning.md).

## Validating locally

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
schema validation, stdin/stdout support, local logging flags, and typed
prospect-safe errors.

Use `--strict` to fail when the input does not validate against the published
v0.1 schema packaged with the CLI. Without `--strict`, schema validation
findings or validation-unavailable notices are rendered as a `Schema Warnings`
section so the report can still be reviewed.

The report includes a header, optional schema warnings, service inventory,
layer count, complexity estimate, manual-review items, migration ordering, and
diagnostics summary. See [`docs/readiness-report.md`](docs/readiness-report.md)
for CLI exit codes, report-section details, and v0.1 heuristics.
