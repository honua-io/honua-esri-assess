import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { runEsriCompatCodemod } from "../src/migration/codemod.js";

const tempDirs: string[] = [];

function makeTempProject(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-geometry-engine-"));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("runEsriCompatCodemod ? geometryEngine mapping", () => {
  it("rewrites a default geometryEngine import to the compat shim and leaves covered ops untouched", () => {
    const root = makeTempProject();
    const file = path.join(root, "measure.ts");
    fs.writeFileSync(
      file,
      [
        "import geometryEngine from '@arcgis/core/geometry/geometryEngine';",
        "export function measure(a: unknown, b: unknown) {",
        "  const merged = geometryEngine.union([a, b]);",
        "  const acres = geometryEngine.planarArea(merged, 'acres');",
        "  return { merged, acres };",
        "}",
      ].join("\n"),
      "utf8",
    );

    const result = runEsriCompatCodemod({
      rootDir: root,
      write: true,
      compatImportPath: "@honua/sdk-esri-compat",
    });

    expect(result.metrics.byKind["geometry-engine"]).toEqual({ total: 1, autoMigrated: 1, manual: 0 });
    expect(result.manualTodos).toEqual([]);

    const nextSource = fs.readFileSync(file, "utf8");
    expect(nextSource).toContain('import { geometryEngineCompat as geometryEngine } from "@honua/sdk-esri-compat";');
    // Covered op call sites are left as-is (they resolve to the shim).
    expect(nextSource).toContain("geometryEngine.union([a, b])");
    expect(nextSource).toContain("geometryEngine.planarArea(merged, 'acres')");
    expect(nextSource).not.toContain("@arcgis/core/geometry/geometryEngine");
  });

  it("keeps a manual TODO for uncovered ops while still migrating the import", () => {
    const root = makeTempProject();
    const file = path.join(root, "densify.ts");
    fs.writeFileSync(
      file,
      [
        "import geometryEngine from '@arcgis/core/geometry/geometryEngine';",
        "export function work(line: unknown) {",
        "  const dense = geometryEngine.geodesicDensify(line, 100, 'meters');",
        "  const buffered = geometryEngine.buffer(dense, 5, 'meters');",
        "  return buffered;",
        "}",
      ].join("\n"),
      "utf8",
    );

    const result = runEsriCompatCodemod({
      rootDir: root,
      write: true,
      annotateTodos: true,
      compatImportPath: "@honua/sdk-esri-compat",
    });

    // One covered op (buffer) auto-migrated + one uncovered op (geodesicDensify) flagged.
    expect(result.metrics.byKind["geometry-engine"]).toEqual({ total: 2, autoMigrated: 1, manual: 1 });
    expect(result.manualTodos).toHaveLength(1);
    expect(result.manualTodos[0]).toMatchObject({ kind: "geometry-engine" });
    expect(result.manualTodos[0].reason).toContain("geodesicDensify");

    const nextSource = fs.readFileSync(file, "utf8");
    expect(nextSource).toContain('import { geometryEngineCompat as geometryEngine } from "@honua/sdk-esri-compat";');
    expect(nextSource).toContain("TODO(honua-migrate)[geometry-engine]");
  });

  it("maps geometryEngineAsync to the async compat shim", () => {
    const root = makeTempProject();
    const file = path.join(root, "async.ts");
    fs.writeFileSync(
      file,
      [
        "import geometryEngineAsync from '@arcgis/core/geometry/geometryEngineAsync';",
        "export async function measure(a: unknown, b: unknown) {",
        "  return geometryEngineAsync.union([a, b]);",
        "}",
      ].join("\n"),
      "utf8",
    );

    const result = runEsriCompatCodemod({
      rootDir: root,
      write: true,
      compatImportPath: "@honua/sdk-esri-compat",
    });

    expect(result.metrics.byKind["geometry-engine"]).toEqual({ total: 1, autoMigrated: 1, manual: 0 });
    const nextSource = fs.readFileSync(file, "utf8");
    expect(nextSource).toContain(
      'import { geometryEngineAsyncCompat as geometryEngineAsync } from "@honua/sdk-esri-compat";',
    );
  });
});
