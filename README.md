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

## Decisions

- Language: Python.
- License: Apache-2.0.
- Runtime writes to customer Esri systems are out of scope.
