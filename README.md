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

- Read-only ArcGIS Online Portal Sharing API scanner.
- Read-only ArcGIS Server REST scanner.
- FileGDB inventory path using license-compatible dependencies.
- Markdown readiness report and sample output.

## Schema and handoff

`EsriFootprint.json` is the sole supported handoff into the closed Honua
migration product. The v0.1 contract is published in this repository:

- Schema: [`schemas/esri-footprint-v0.1.json`](schemas/esri-footprint-v0.1.json)
- Reference: [`docs/schemas/esri-footprint.v0.1.md`](docs/schemas/esri-footprint.v0.1.md)
- Canonical sample: [`tests/fixtures/esri-footprint-sample.json`](tests/fixtures/esri-footprint-sample.json)

`$id`: `https://schemas.honua.io/esri-footprint/v0.1.0/esri-footprint.json`

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
