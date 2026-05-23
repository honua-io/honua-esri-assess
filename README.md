# honua-esri-assess

Open-source Esri footprint assessment tooling for Honua migration discovery.

This repository owns the read-only scanner and report generator that produce a
versioned `EsriFootprint.json` artifact for the closed Honua migration product.
The tool is Apache-2.0 by design so prospects can audit the code before running
it against ArcGIS Online, ArcGIS Server, or FileGDB inventories.

## Initial Scope

- `EsriFootprint.json` v0.1 JSON Schema and reference documentation.
- Read-only ArcGIS Online Portal Sharing API scanner.
- Read-only ArcGIS Server REST scanner.
- FileGDB inventory path using license-compatible dependencies.
- Markdown readiness report and sample output.
- Fixture-backed CI smoke test.

## Schema and handoff

`EsriFootprint.json` is the sole supported handoff into the closed Honua
migration product. Two policy docs govern that contract:

- [`docs/schemas/versioning.md`](docs/schemas/versioning.md) — semver
  interpretation, deprecation policy, producer guarantees, and consumer
  expectations for the artifact.
- [`docs/schemas/handoff-contract.md`](docs/schemas/handoff-contract.md) —
  prospect-facing summary of what flows between this tool and the closed
  product, and how to verify a footprint locally.

The schema body for the current `0.1.x` line is tracked under
[honua-io/honua-esri-assess#2](https://github.com/honua-io/honua-esri-assess/issues/2).

## Decisions

- Language: Python.
- License: Apache-2.0.
- Runtime writes to customer Esri systems are out of scope.
