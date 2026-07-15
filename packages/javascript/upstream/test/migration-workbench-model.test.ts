import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  parseManifest,
  parseMapLibreAssessment,
  parseMigrationReport,
  parseWidgetReadiness,
} from "../examples/migration-workbench/src/artifacts.js";
import { createMigrationWorkbenchViewModel, formatArtifactCommand } from "../examples/migration-workbench/src/model.js";
import type {
  MigrationWorkbenchArtifactSet,
  MigrationWorkbenchViewModel,
} from "../examples/migration-workbench/src/types.js";
import { createAssertionMatrix, readJsonPath } from "../examples/migration-workbench/src/workflow.js";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const artifactRoot = path.join(repositoryRoot, "examples/migration-workbench/public/artifacts/v1");

describe("migration workbench artifact model", () => {
  it("projects the committed compat report without inventing non-zero residuals", () => {
    const artifacts = readCommittedArtifacts();
    const model = createMigrationWorkbenchViewModel(artifacts, artifacts.migrationReport.behaviorProof.observations);

    expect(model.fixture).toBe(artifacts.manifest.fixture);
    expect(model.target).toBe("honua-compat");
    expect(metricValue(model.compatibility.metrics, "auto-migrated")).toBe(
      artifacts.migrationReport.demo.migration.codemodResult.metrics.autoMigratedCallSites,
    );
    expect(metricValue(model.compatibility.metrics, "manual-call-sites")).toBe(0);
    expect(metricValue(model.compatibility.metrics, "unsupported-modules")).toBe(0);
    expect(metricValue(model.compatibility.metrics, "blocking-flags")).toBe(0);
    expect(model.compatibility.manualTodos).toEqual([]);
    expect(model.compatibility.unsupportedModules).toEqual([]);
    expect(model.compatibility.gates.every((gate) => gate.passed)).toBe(true);
  });

  it("retains every zero codemod category and the complete MapLibre alternative", () => {
    const artifacts = readCommittedArtifacts();
    const model = createMigrationWorkbenchViewModel(artifacts, artifacts.migrationReport.behaviorProof.observations);
    const compatByKind = artifacts.migrationReport.demo.migration.codemodResult.metrics.byKind;
    const maplibreByKind = artifacts.maplibreAssessment.report.codemodResult.metrics.byKind;

    expect(model.compatibility.mappings).toHaveLength(Object.keys(compatByKind).length);
    expect(model.compatibility.mappings.filter((mapping) => mapping.total === 0).length).toBeGreaterThan(0);
    expect(model.maplibre.mappings).toHaveLength(Object.keys(maplibreByKind).length);
    expect(model.maplibre.manualTodos).toEqual(artifacts.maplibreAssessment.residuals.manualTodos);
    expect(model.maplibre.unsupportedModules).toEqual(artifacts.maplibreAssessment.residuals.unsupportedModules);
    expect(metricValue(model.maplibre.metrics, "manual-call-sites")).toBe(4);
    expect(metricValue(model.maplibre.metrics, "unsupported-modules")).toBe(3);
    expect(metricValue(model.maplibre.metrics, "blocking-flags")).toBe(0);
    expect(model.maplibre.gates.some((gate) => !gate.passed)).toBe(true);
  });

  it("projects widget guidance and preserves its zero manual category", () => {
    const artifacts = readCommittedArtifacts();
    const model = createMigrationWorkbenchViewModel(artifacts, artifacts.migrationReport.behaviorProof.observations);

    expect(model.widgets.summary.manualSites).toBe(0);
    expect(model.widgets.summary.automatedSites).toBe(2);
    expect(model.widgets.summary.assistedSites).toBe(1);
    expect(model.widgets.widgets.map((widget) => widget.guideLink)).toEqual(
      artifacts.widgetReadiness.report.widgets.map((widget) => widget.guideLink),
    );
  });

  it("rechecks every stored behavior assertion against generated browser observations", () => {
    const artifacts = readCommittedArtifacts();
    const observations = artifacts.migrationReport.behaviorProof.observations;
    const model = createMigrationWorkbenchViewModel(artifacts, observations);

    expect(model.assertions).toHaveLength(23);
    expect(model.assertions.every((assertion) => assertion.passed)).toBe(true);
    expect(model.assertions.every((assertion) => assertion.browserPassed)).toBe(true);
    expect(model.browserProofPassed).toBe(true);
    expect(readJsonPath(observations, "$.selection.objectIds[0]")).toBe(41);

    const changed = structuredClone(observations) as Record<string, unknown>;
    changed.table = { countBeforeFilter: 999 };
    const matrix = createAssertionMatrix(artifacts.migrationReport.behaviorProof.assertions, changed);
    expect(matrix.some((assertion) => !assertion.browserPassed)).toBe(true);
  });

  it("keeps commands, patch, downloads, and hashes tied to the manifest", () => {
    const artifacts = readCommittedArtifacts();
    const model = createMigrationWorkbenchViewModel(artifacts, artifacts.migrationReport.behaviorProof.observations);

    expect(model.commands).toEqual(artifacts.manifest.commands);
    expect(formatArtifactCommand(model.commands[0]?.executable ?? "", model.commands[0]?.argv ?? [])).toContain(
      '"dist/src/migration/cli.js"',
    );
    expect(model.diff).toBe(fs.readFileSync(path.join(artifactRoot, "migration.v1.patch"), "utf8"));
    expect(model.files).toHaveLength(artifacts.manifest.files.length);
    expect(model.files.find((file) => file.repositoryPath.endsWith("migration.v1.patch"))?.href).toBe(
      "/artifacts/v1/migration.v1.patch",
    );
    expect(model.files.find((file) => file.repositoryPath.endsWith("migrated-main.js"))?.href).toBe(
      "/artifacts/v1/migrated-main.js",
    );
    expect(model.files.every((file) => /^[a-f0-9]{64}$/u.test(file.sha256))).toBe(true);
    expect(model.patchProof.applyCheckPassed).toBe(true);
    expect(model.patchProof.targetTreeEqual).toBe(true);
  });

  it("rejects an artifact with the wrong schema instead of rendering plausible data", () => {
    expect(() => parseManifest({ schemaVersion: "honua.migration-workbench.manifest.v0" })).toThrow(
      "unsupported schemaVersion",
    );
    expect(() => parseMigrationReport({ schemaVersion: "honua.migration-workbench.report.v1" })).toThrow(
      "migration report.demo",
    );
  });

  it("removes credential configuration, cloud import, and fabricated fixture modules", () => {
    const sourceRoot = path.join(repositoryRoot, "examples/migration-workbench/src");
    expect(fs.existsSync(path.join(sourceRoot, "config.ts"))).toBe(false);
    expect(fs.existsSync(path.join(sourceRoot, "fixtures.ts"))).toBe(false);

    const presentationSource = ["main.ts", "model.ts", "artifacts.ts", "workflow.ts", "types.ts"]
      .map((file) => fs.readFileSync(path.join(sourceRoot, file), "utf8"))
      .join("\n");
    expect(presentationSource).not.toContain("VITE_");
    expect(presentationSource).not.toContain("adminApiKey");
    expect(presentationSource).not.toContain("Cloud import");
    expect(presentationSource).not.toContain("runEsriCompatCodemod");
  });
});

function readCommittedArtifacts(): MigrationWorkbenchArtifactSet {
  return {
    manifest: parseManifest(readJson("manifest.v1.json")),
    migrationReport: parseMigrationReport(readJson("migration-report.v1.json")),
    widgetReadiness: parseWidgetReadiness(readJson("widget-readiness.v1.json")),
    maplibreAssessment: parseMapLibreAssessment(readJson("maplibre-assessment.v1.json")),
    diff: fs.readFileSync(path.join(artifactRoot, "migration.v1.patch"), "utf8"),
  };
}

function readJson(filename: string): unknown {
  return JSON.parse(fs.readFileSync(path.join(artifactRoot, filename), "utf8"));
}

function metricValue(
  metrics: MigrationWorkbenchViewModel["compatibility"]["metrics"],
  id: string,
): number | string | undefined {
  return metrics.find((metric) => metric.id === id)?.value;
}
