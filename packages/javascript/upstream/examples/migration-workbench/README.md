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
npm run test:playwright:migration-workbench
```

The Vite configuration uses the shared sample SDK resolver and declares only
the public `@honua/sdk-js/esri-compat` entry point. The focused Playwright proof
runs unchanged in source or packed mode:

```bash
HONUA_SAMPLE_SDK_MODE=source npm run test:playwright:migration-workbench
HONUA_SAMPLE_SDK_MODE=packed \
  HONUA_SAMPLE_SDK_DIR=/absolute/path/to/extracted/package \
  npm run test:playwright:migration-workbench
```

The loopback-only browser proof checks every rendered metric against the
committed model, re-hashes all five manifest files from their served bytes,
confirms all generated-target assertions, retains every residual and guide,
runs Axe and keyboard/responsive workflows, captures desktop/mobile evidence,
enforces deterministic ready-time and decoded-byte budgets, and proves
idempotent runtime and fixture teardown. The mock server can emit its bounded
fixture receipt independently:

```bash
npm run demo:migration-workbench:mock -- --evidence-once
```

The adapted `test/fixtures/esri-demo-feature-table-relates-app` fixture is not
used or exposed here because public license evidence for it was not established.
The artifact manifest records that exclusion and the Apache-2.0 scope of the
Honua-authored source fixture.
