# ArcGIS Migration Workbench

This sample presents the committed, deterministic artifacts produced by the
repository's `honua-migrate` CLI for the Honua-authored `arcgis-source-app`
fixture. It is an evidence viewer and browser runtime proof, not a second
migration engine.

The workbench:

- loads the versioned JSON report, widget guidance, MapLibre assessment,
  manifest, and patch from `public/artifacts/v1`;
- imports the committed generated target, which uses the public
  `@honua/sdk-js/esri-compat` entry point;
- compares the generated target's browser observations with every stored
  expected behavior assertion;
- retains zero-count, manual, unsupported, failed-gate, and alternative
  MapLibre findings instead of filtering them out; and
- exposes the exact fixed-argument CLI commands, SHA-256 manifest entries, and
  source/target patch.

It does not accept files, upload source, read browser credentials, invoke a
transform, or perform a cloud import. Artifact generation remains a repository
build step owned by Slice 1:

```bash
npm run demo:migration-workbench:artifacts:check
```

Run the workbench locally:

```bash
npm run demo:migration-workbench
```

Focused validation:

```bash
npm test -- test/migration-workbench-model.test.ts
npm run demo:migration-workbench:typecheck
npm run demo:migration-workbench:build
```

The adapted `test/fixtures/esri-demo-feature-table-relates-app` fixture is not
used or exposed here because public license evidence for it was not established.
The artifact manifest records that exclusion and the Apache-2.0 scope of the
Honua-authored source fixture.
