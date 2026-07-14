import { execFileSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import { runEsriCompatCodemod } from "../src/migration/codemod.js";
import { buildJsMigrationReport } from "../src/migration/report.js";
import { scanArcGisUsage } from "../src/migration/scanner.js";

// End-to-end migration harness. Takes the hand-written ArcGIS sample app at
// `examples/arcgis-source-app/`, runs the codemod against a copy in a tempdir,
// verifies the readiness gate is green, every expected rewrite landed, and
// the migrated source typechecks against the workspace `src/esri-compat/`
// entry point via tsconfig `paths` (so `@arcgis/core` doesn't need to be
// installed). This is the e2e demo conversion called out in
// `docs/migration-punch-list.md` as previously not shipped.

const tempDirs: string[] = [];

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-arcgis-e2e-"));
  tempDirs.push(dir);
  return dir;
}

function repoRoot(): string {
  return fileURLToPath(new URL("../", import.meta.url));
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("e2e ArcGIS sample app conversion", () => {
  it("migrates examples/arcgis-source-app/ to a typechecking honua-compat app", () => {
    const sampleSource = path.join(repoRoot(), "examples", "arcgis-source-app");
    const tempRoot = makeTempDir();
    const workingCopy = path.join(tempRoot, "arcgis-source-app");
    fs.cpSync(sampleSource, workingCopy, { recursive: true });

    const scanReport = scanArcGisUsage(workingCopy);
    const codemodResult = runEsriCompatCodemod({
      rootDir: workingCopy,
      write: true,
      target: "honua-compat",
    });
    const report = buildJsMigrationReport(workingCopy, codemodResult, scanReport);

    expect(report.readiness).toBe("ready");
    expect(report.gates.every((gate) => gate.passed)).toBe(true);
    expect(codemodResult.manualTodos).toEqual([]);
    expect(report.unhandledArcGisModules).toEqual([]);

    expect(codemodResult.metrics.byKind["feature-layer"]).toEqual({
      total: 2,
      autoMigrated: 2,
      manual: 0,
    });
    expect(codemodResult.metrics.byKind.map).toEqual({
      total: 2,
      autoMigrated: 2,
      manual: 0,
    });
    expect(codemodResult.metrics.byKind["map-view"]).toEqual({
      total: 2,
      autoMigrated: 2,
      manual: 0,
    });
    expect(codemodResult.metrics.byKind["feature-table-widget"]).toEqual({
      total: 1,
      autoMigrated: 1,
      manual: 0,
    });
    expect(codemodResult.metrics.byKind["popup-widget"]).toEqual({ total: 1, autoMigrated: 1, manual: 0 });
    expect(codemodResult.metrics.byKind["layer-list"]).toEqual({ total: 1, autoMigrated: 1, manual: 0 });

    const migratedMain = fs.readFileSync(path.join(workingCopy, "src", "main.ts"), "utf8");

    // Compat import landed with the three rewritten constructors.
    expect(migratedMain).toContain(
      'import { FeatureLayerCompat, MapCompat, MapViewCompat } from "@honua/sdk-esri-compat";',
    );

    // Constructors rewritten.
    expect(migratedMain).toContain("new FeatureLayerCompat({");
    expect(migratedMain).toContain('new MapCompat({ basemap: "streets" })');
    expect(migratedMain).toContain("new MapViewCompat({");

    // popupTemplate option preserved verbatim on the rewritten FeatureLayer.
    expect(migratedMain).toContain('title: "Parcel {PARCEL_ID}"');
    expect(migratedMain).toContain("Owner: {OWNER}");

    // Event-name remap: "layerview-create" -> "layer-view-created".
    expect(migratedMain).toContain('parcels.on("layer-view-created"');
    expect(migratedMain).not.toContain('parcels.on("layerview-create"');

    // Untouched event: "click" stays.
    expect(migratedMain).toContain('view.on("click"');

    // Original ArcGIS default imports are gone ? they have no remaining
    // references after the constructors are rewritten and the type
    // annotations were authored as `unknown`.
    expect(migratedMain).not.toContain("@arcgis/core/layers/FeatureLayer");
    expect(migratedMain).not.toContain("@arcgis/core/Map");
    expect(migratedMain).not.toContain("@arcgis/core/views/MapView");

    // tsc the migrated app against a tsconfig that resolves
    // @honua/sdk-esri-compat to the workspace shim entry.
    writeMigratedTsConfig(workingCopy);

    const tscBin = resolveTscBin();
    expect(fs.existsSync(tscBin)).toBe(true);

    const tscResult = execFileSync(
      process.execPath,
      [tscBin, "--noEmit", "--project", path.join(workingCopy, "tsconfig.migrated.json")],
      { cwd: workingCopy, stdio: "pipe", encoding: "utf8" },
    );

    // tsc emits nothing to stdout on success; if we got here, exit was 0.
    expect(tscResult).toBe("");
  }, 60_000);
});

function resolveTscBin(): string {
  // Resolve TypeScript's CLI script through Node's resolver so we don't
  // assume a particular node_modules layout (the worktree shares with the
  // main checkout; CI installs at the repo root). We invoke the resolved
  // JS with `process.execPath` to stay portable across platforms.
  const require_ = createRequire(import.meta.url);
  const pkgJsonPath = require_.resolve("typescript/package.json");
  const pkg = JSON.parse(fs.readFileSync(pkgJsonPath, "utf8")) as { bin?: Record<string, string> | string };
  const binEntry = typeof pkg.bin === "string" ? pkg.bin : pkg.bin?.tsc;
  if (!binEntry) {
    throw new Error("Unable to locate the typescript/tsc bin entry.");
  }
  return path.join(path.dirname(pkgJsonPath), binEntry);
}

function writeMigratedTsConfig(workingCopy: string): void {
  const compatEntry = path.join(repoRoot(), "src", "esri-compat-entry.ts");
  // Use a path relative to the working copy so the tsconfig stays portable.
  const compatEntryRelative = path.relative(workingCopy, compatEntry).split(path.sep).join("/");
  const tsconfig = {
    compilerOptions: {
      target: "ES2022",
      module: "ESNext",
      moduleResolution: "Bundler",
      strict: true,
      noEmit: true,
      skipLibCheck: true,
      allowSyntheticDefaultImports: true,
      esModuleInterop: true,
      verbatimModuleSyntax: false,
      baseUrl: ".",
      paths: {
        "@honua/sdk-esri-compat": [compatEntryRelative],
      },
      types: [],
    },
    include: ["src/**/*.ts"],
  };
  fs.writeFileSync(path.join(workingCopy, "tsconfig.migrated.json"), `${JSON.stringify(tsconfig, null, 2)}\n`, "utf8");
}
