import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterAll, describe, expect, it } from "vitest";

import {
  MIGRATION_WORKBENCH_ARTIFACT_PATHS,
  buildMigrationWorkbenchArtifacts,
  defaultRepositoryRoot,
  executeIsolatedGeneratedModule,
  verifyMigrationPatch,
} from "../scripts/lib/migration-workbench-artifacts.mjs";

const repositoryRoot = defaultRepositoryRoot();
const tempDirs: string[] = [];

function makeTempDir(label: string): string {
  const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), `${label}-`));
  tempDirs.push(temporaryRoot);
  return temporaryRoot;
}

function parseArtifact(artifacts: Map<string, Buffer>, repositoryPath: string): Record<string, any> {
  const bytes = artifacts.get(repositoryPath);
  if (!bytes) {
    throw new Error(`Artifact ${repositoryPath} was not generated.`);
  }
  return JSON.parse(bytes.toString("utf8")) as Record<string, any>;
}

afterAll(() => {
  for (const temporaryRoot of tempDirs) {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

describe("migration workbench artifact supply chain", () => {
  it("is byte-deterministic across different temporary roots and matches committed output", async () => {
    const firstRoot = makeTempDir("honua-workbench-first");
    const secondRoot = makeTempDir("honua-workbench-second");
    const first = await buildMigrationWorkbenchArtifacts({
      repositoryRoot,
      temporaryRoot: firstRoot,
    });
    const second = await buildMigrationWorkbenchArtifacts({
      repositoryRoot,
      temporaryRoot: secondRoot,
    });

    expect([...first.artifacts.keys()].sort()).toEqual([...MIGRATION_WORKBENCH_ARTIFACT_PATHS].sort());
    expect([...second.artifacts.keys()].sort()).toEqual([...MIGRATION_WORKBENCH_ARTIFACT_PATHS].sort());

    for (const [repositoryPath, firstBytes] of first.artifacts) {
      const secondBytes = second.artifacts.get(repositoryPath);
      expect(secondBytes, repositoryPath).toBeDefined();
      expect(secondBytes?.equals(firstBytes), repositoryPath).toBe(true);
      expect(fs.readFileSync(path.join(repositoryRoot, repositoryPath)).equals(firstBytes), repositoryPath).toBe(true);

      const artifactText = firstBytes.toString("utf8");
      expect(artifactText, repositoryPath).not.toContain(firstRoot);
      expect(artifactText, repositoryPath).not.toContain(secondRoot);
      expect(artifactText, repositoryPath).not.toContain(repositoryRoot);
    }
  }, 60_000);

  it("records exact byte counts and SHA-256 digests for every non-manifest artifact", async () => {
    const result = await buildMigrationWorkbenchArtifacts({
      repositoryRoot,
      temporaryRoot: makeTempDir("honua-workbench-manifest"),
    });
    const manifest = parseArtifact(
      result.artifacts,
      "examples/migration-workbench/public/artifacts/v1/manifest.v1.json",
    );

    expect(manifest.files).toHaveLength(result.artifacts.size - 1);
    for (const file of manifest.files as Array<{ repositoryPath: string; bytes: number; sha256: string }>) {
      const bytes = result.artifacts.get(file.repositoryPath);
      expect(bytes, file.repositoryPath).toBeDefined();
      expect(file.bytes, file.repositoryPath).toBe(bytes?.length);
      expect(file.sha256, file.repositoryPath).toBe(
        createHash("sha256")
          .update(bytes as Buffer)
          .digest("hex"),
      );
    }
  }, 60_000);

  it("keeps CLI guidance, zero counts, failures, TODOs, and unsupported modules intact", async () => {
    const result = await buildMigrationWorkbenchArtifacts({
      repositoryRoot,
      temporaryRoot: makeTempDir("honua-workbench-truth"),
    });
    const migration = parseArtifact(
      result.artifacts,
      "examples/migration-workbench/public/artifacts/v1/migration-report.v1.json",
    );
    const widgets = parseArtifact(
      result.artifacts,
      "examples/migration-workbench/public/artifacts/v1/widget-readiness.v1.json",
    );
    const maplibre = parseArtifact(
      result.artifacts,
      "examples/migration-workbench/public/artifacts/v1/maplibre-assessment.v1.json",
    );

    expect(migration.demo.migration.readiness).toBe("ready");
    expect(migration.demo.migration.codemodResult.metrics.manualCallSites).toBe(0);
    expect(migration.demo.migration.manualTodos).toEqual([]);
    expect(migration.demo.migration.unhandledArcGisModules).toEqual([]);
    expect(migration.commands[0].argv).toEqual(
      expect.arrayContaining(["demo", "--target", "honua-compat", "--skip-import", "--skip-reconcile"]),
    );
    expect(JSON.stringify(migration.commands)).not.toMatch(/admin-api-key|credential|token/i);
    expect(migration.provenance.transformationEngine).toEqual({
      path: "dist/src/migration/cli.js",
      sha256: createHash("sha256")
        .update(fs.readFileSync(path.join(repositoryRoot, "dist/src/migration/cli.js")))
        .digest("hex"),
      digestScope: "Entry module bytes only; transitive imports are not covered by this digest.",
    });
    expect(migration.provenance.generatedTargetExecution).toMatchObject({
      processBoundary: "separate Node.js process",
      inheritedEnvironment: "fixed non-secret allowlist",
      externalNetworkAttemptsObserved: 0,
    });
    expect(migration.provenance).not.toHaveProperty("externalNetworkRequests");

    expect(widgets.report.summary).toMatchObject({
      totalSites: 3,
      automatedSites: 2,
      assistedSites: 1,
      manualSites: 0,
      manualWidgets: 0,
    });
    expect(widgets.report.widgets).toHaveLength(3);
    expect(
      (widgets.report.widgets as Array<{ guideLink: string }>).every((row) =>
        row.guideLink.startsWith("docs/widget-survival-guide.md#"),
      ),
    ).toBe(true);

    expect(maplibre.report.readiness).toBe("assisted");
    expect(maplibre.report.gates).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ gate: "no-manual-todos", passed: false }),
        expect.objectContaining({ gate: "no-unhandled-modules", passed: false }),
      ]),
    );
    expect(maplibre.residuals.errors).toEqual([]);
    expect(maplibre.residuals.manualTodos).toHaveLength(4);
    expect(maplibre.residuals.unsupportedModules).toHaveLength(3);
    expect(maplibre.residuals).toEqual({
      errors: maplibre.report.codemodResult.errors ?? [],
      manualTodos: maplibre.report.manualTodos,
      unsupportedModules: maplibre.report.unhandledArcGisModules,
    });
  }, 60_000);

  it("executes generated behavior against independent expectations", async () => {
    const expected = JSON.parse(
      fs.readFileSync(
        path.join(repositoryRoot, "examples/migration-workbench/fixtures/expected-behavior.v1.json"),
        "utf8",
      ),
    ) as { expected: unknown };
    const generatedPath = path.join(repositoryRoot, "examples/migration-workbench/src/generated/migrated-main.js");
    const isolated = executeIsolatedGeneratedModule({
      repositoryRoot,
      generatedTargetBytes: fs.readFileSync(generatedPath),
    });

    expect(isolated.value).toEqual(expected.expected);
    expect(isolated.evidence.externalNetworkAttemptsObserved).toBe(0);
  });

  it("passes git apply --check and recreates the complete CLI target tree", async () => {
    const temporaryRoot = makeTempDir("honua-workbench-patch");
    const result = await buildMigrationWorkbenchArtifacts({
      repositoryRoot,
      temporaryRoot,
      keepWorkspace: true,
    });
    const patchBytes = result.artifacts.get("examples/migration-workbench/public/artifacts/v1/migration.v1.patch");
    if (!patchBytes) {
      throw new Error("Migration patch was not generated.");
    }

    const verification = verifyMigrationPatch({
      sourceTreePath: result.workspace.sourceTreePath,
      targetTreePath: result.workspace.targetTreePath,
      patchBytes,
      temporaryRoot,
    });

    expect(verification.applyCheckPassed).toBe(true);
    expect(verification.targetTreeEqual).toBe(true);
    expect(verification.directEntryComparisonPassed).toBe(true);
    expect(verification.applyCheckCommand.argv).toEqual(
      expect.arrayContaining(["color.ui=false", "core.quotePath=true", "apply", "--check", "--binary"]),
    );
    expect(verification.applyCommand.argv).toEqual(
      expect.arrayContaining(["diff.algorithm=myers", "apply", "--binary", "--whitespace=nowarn"]),
    );
    expect(verification.appliedTreeSha256).toBe(verification.targetTreeSha256);
    expect(verification.sourceTreeSha256).not.toBe(verification.targetTreeSha256);
  }, 60_000);
});
