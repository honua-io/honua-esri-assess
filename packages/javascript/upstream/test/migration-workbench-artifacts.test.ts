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
  hashRegularTree,
  verifyMigrationPatch,
} from "../scripts/lib/migration-workbench-artifacts.mjs";
import { verifyPreparedSdkArtifact } from "../scripts/lib/prepared-sdk-artifact.mjs";

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

function sourceSnapshotDigest(fixtureTreeSha256: string, expectedBehaviorSha256: string): string {
  const digest = createHash("sha256");
  for (const value of [
    Buffer.from("honua.migration-workbench.source-snapshot.v1", "utf8"),
    Buffer.from(fixtureTreeSha256, "ascii"),
    Buffer.from(expectedBehaviorSha256, "ascii"),
  ]) {
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(value.length));
    digest.update(length);
    digest.update(value);
  }
  return digest.digest("hex");
}

function preparedDistSrcDigest(entries: Array<{ path: string; bytes: number; sha256: string }>): {
  sha256: string;
  fileCount: number;
} {
  const distSrcEntries = entries
    .filter((entry) => entry.path.startsWith("dist/src/"))
    .sort((left, right) => Buffer.compare(Buffer.from(left.path), Buffer.from(right.path)));
  const digest = createHash("sha256");
  for (const value of [
    Buffer.from("honua.migration-workbench.prepared-dist-src.v1", "utf8"),
    Buffer.from(String(distSrcEntries.length), "ascii"),
    ...distSrcEntries.flatMap((entry) => [
      Buffer.from(entry.path, "utf8"),
      Buffer.from(String(entry.bytes), "ascii"),
      Buffer.from(entry.sha256, "ascii"),
    ]),
  ]) {
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(value.length));
    digest.update(length);
    digest.update(value);
  }
  return { sha256: digest.digest("hex"), fileCount: distSrcEntries.length };
}

function executionHarnessDigest(files: Array<{ repositoryPath: string; byteLength: number; sha256: string }>): string {
  const digest = createHash("sha256");
  for (const value of [
    Buffer.from("honua.migration-workbench.execution-harness.v1", "utf8"),
    ...files.flatMap((file) => [
      Buffer.from(file.repositoryPath, "utf8"),
      Buffer.from(String(file.byteLength), "ascii"),
      Buffer.from(file.sha256, "ascii"),
    ]),
  ]) {
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(value.length));
    digest.update(length);
    digest.update(value);
  }
  return digest.digest("hex");
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
    const preparedSdk = verifyPreparedSdkArtifact({ projectRoot: repositoryRoot });
    const distSrcIdentity = preparedDistSrcDigest(preparedSdk.dist.entries);
    expect(migration.provenance.transformationEngine).toEqual({
      path: "dist/src/migration/cli.js",
      preparedArtifactFormat: preparedSdk.format,
      buildInputsSha256: preparedSdk.inputs.sha256,
      buildInputFileCount: preparedSdk.inputs.fileCount,
      distSrcSha256: distSrcIdentity.sha256,
      distSrcFileCount: distSrcIdentity.fileCount,
      digestScope:
        "Complete prepared SDK build inputs plus verified canonical dist/src transformation entries; " +
        "adopted outputs outside dist/src are excluded.",
    });
    expect(migration.provenance.transformationEngine).not.toHaveProperty("sha256");
    expect(migration.provenance.transformationEngine).not.toHaveProperty("distSha256");
    expect(migration.provenance.transformationEngine).not.toHaveProperty("distFileCount");
    const expectedBehaviorBytes = fs.readFileSync(
      path.join(repositoryRoot, "examples/migration-workbench/fixtures/expected-behavior.v1.json"),
    );
    const expectedBehaviorSha256 = createHash("sha256").update(expectedBehaviorBytes).digest("hex");
    const fixtureTreeSha256 = hashRegularTree(path.join(repositoryRoot, "examples/arcgis-source-app"));
    expect(migration.provenance.sourceSnapshot).toEqual({
      fixtureTreeSha256,
      expectedBehaviorPath: "examples/migration-workbench/fixtures/expected-behavior.v1.json",
      expectedBehaviorSha256,
      combinedSha256: sourceSnapshotDigest(fixtureTreeSha256, expectedBehaviorSha256),
    });
    expect(migration.provenance.generatedTargetExecution).toMatchObject({
      processBoundary: "separate Node.js process",
      inheritedEnvironment: "fixed non-secret allowlist",
      trustBoundary: "repository-controlled generated target; this guard is not an arbitrary-code security sandbox",
      protocolNoncePurpose: "parent/runner response correlation, not same-process code authentication",
      guardedNetworkApiAttemptsObserved: 0,
    });
    const executionHarness = migration.provenance.generatedTargetExecution.executionHarness as {
      combinedSha256: string;
      runner: { repositoryPath: string; byteLength: number; sha256: string };
      networkGuard: { repositoryPath: string; byteLength: number; sha256: string };
    };
    const executionHarnessFiles = [executionHarness.runner, executionHarness.networkGuard];
    for (const file of executionHarnessFiles) {
      const bytes = fs.readFileSync(path.join(repositoryRoot, file.repositoryPath));
      expect(file.byteLength).toBe(bytes.length);
      expect(file.sha256).toBe(createHash("sha256").update(bytes).digest("hex"));
    }
    expect(executionHarness.combinedSha256).toBe(executionHarnessDigest(executionHarnessFiles));
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

  it("prepares and verifies the SDK manifest before standalone artifact generation", () => {
    const scripts = JSON.parse(fs.readFileSync(path.join(repositoryRoot, "package.json"), "utf8")).scripts as Record<
      string,
      string
    >;
    for (const name of ["demo:migration-workbench:artifacts:write", "demo:migration-workbench:artifacts:check"]) {
      expect(scripts[name]).toMatch(/^npm run prepare:test-sdk --silent && node /);
      expect(scripts[name]).not.toContain("npm run build");
    }
  });

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
    expect(isolated.evidence.guardedNetworkApiAttemptsObserved).toBe(0);
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
