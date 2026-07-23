import type {
  ArtifactManifestFile,
  CodemodKindMetric,
  EvidenceMetric,
  MigrationReportBody,
  MigrationWorkbenchArtifactSet,
  MigrationWorkbenchViewModel,
} from "./types.js";
import { createAssertionMatrix } from "./workflow.js";

const PUBLIC_ARTIFACT_PREFIX = "examples/migration-workbench/public/";
const GENERATED_TARGET_PATH = "examples/migration-workbench/src/generated/migrated-main.js";
const GENERATED_TARGET_HREF = "/artifacts/v1/migrated-main.js";

export function createMigrationWorkbenchViewModel(
  artifacts: MigrationWorkbenchArtifactSet,
  browserObservations: unknown,
): MigrationWorkbenchViewModel {
  assertArtifactSetCoherence(artifacts);

  const compatibility = artifacts.migrationReport.demo.migration;
  const maplibre = artifacts.maplibreAssessment.report;
  const assertions = createAssertionMatrix(artifacts.migrationReport.behaviorProof.assertions, browserObservations);

  return {
    fixture: artifacts.manifest.fixture,
    target: artifacts.migrationReport.target,
    artifactSet: artifacts.manifest.artifactSet,
    generatedAt: artifacts.migrationReport.demo.generatedAt,
    source: {
      path: artifacts.manifest.provenance.fixture,
      authorship: artifacts.manifest.provenance.authorship,
      licenseScope: artifacts.manifest.provenance.licenseScope,
      sourceUpload: artifacts.manifest.provenance.sourceUpload,
      credentialsRequired: artifacts.manifest.provenance.credentialsRequired,
    },
    compatibility: {
      readiness: compatibility.readiness,
      passed: artifacts.migrationReport.demo.passed,
      metrics: migrationMetrics(compatibility),
      gates: compatibility.gates,
      mappings: mappingRows(compatibility.codemodResult.metrics.byKind),
      manualTodos: compatibility.manualTodos,
      unsupportedModules: compatibility.unhandledArcGisModules,
    },
    widgets: artifacts.widgetReadiness.report,
    maplibre: {
      readiness: maplibre.readiness,
      metrics: migrationMetrics(maplibre),
      gates: maplibre.gates,
      mappings: mappingRows(maplibre.codemodResult.metrics.byKind),
      manualTodos: artifacts.maplibreAssessment.residuals.manualTodos,
      unsupportedModules: artifacts.maplibreAssessment.residuals.unsupportedModules,
    },
    assertions,
    browserProofPassed:
      artifacts.migrationReport.behaviorProof.passed &&
      assertions.length > 0 &&
      assertions.every((assertion) => assertion.passed && assertion.browserPassed),
    patchProof: artifacts.migrationReport.patchProof,
    commands: artifacts.manifest.commands,
    files: artifacts.manifest.files.map((file) => ({ ...file, href: publicHref(file) })),
    diff: artifacts.diff,
    provenance: artifacts.manifest.provenance,
  };
}

export function formatArtifactCommand(executable: string, argv: readonly string[]): string {
  return [executable, ...argv].map((part) => JSON.stringify(part)).join(" ");
}

function migrationMetrics(migration: MigrationReportBody): readonly EvidenceMetric[] {
  const metrics = migration.codemodResult.metrics;
  return [
    {
      id: "files-scanned",
      label: "Files scanned",
      value: migration.scanReport.filesScanned,
      tone: "neutral",
      scope: "CLI scan report",
    },
    {
      id: "auto-migrated",
      label: "Auto migrated",
      value: metrics.autoMigratedCallSites,
      tone: "good",
      scope: "Codemod-scoped call sites",
    },
    {
      id: "manual-call-sites",
      label: "Manual call sites",
      value: metrics.manualCallSites,
      tone: metrics.manualCallSites === 0 ? "good" : "warning",
      scope: "Codemod-scoped call sites",
    },
    {
      id: "unsupported-modules",
      label: "Unsupported modules",
      value: migration.unhandledArcGisModules.length,
      tone: migration.unhandledArcGisModules.length === 0 ? "good" : "danger",
      scope: "Discovered ArcGIS modules outside codemod scope",
    },
    {
      id: "blocking-flags",
      label: "Blocking scan flags",
      value: migration.scanReport.flags.length,
      tone: migration.scanReport.flags.length === 0 ? "good" : "danger",
      scope: "CLI scan flags",
    },
  ];
}

function mappingRows(
  byKind: Readonly<Record<string, CodemodKindMetric>>,
): readonly ({ readonly kind: string } & CodemodKindMetric)[] {
  return Object.entries(byKind)
    .map(([kind, metric]) => ({ kind, ...metric }))
    .sort((left, right) => left.kind.localeCompare(right.kind));
}

function publicHref(file: ArtifactManifestFile): string | undefined {
  if (file.repositoryPath === GENERATED_TARGET_PATH) return GENERATED_TARGET_HREF;
  if (!file.repositoryPath.startsWith(PUBLIC_ARTIFACT_PREFIX)) return undefined;
  return `/${file.repositoryPath.slice(PUBLIC_ARTIFACT_PREFIX.length)}`;
}

function assertArtifactSetCoherence(artifacts: MigrationWorkbenchArtifactSet): void {
  const fixtures = [
    artifacts.manifest.fixture,
    artifacts.migrationReport.fixture,
    artifacts.widgetReadiness.fixture,
    artifacts.maplibreAssessment.fixture,
  ];
  if (new Set(fixtures).size !== 1) {
    throw new Error(`Migration workbench artifact fixture mismatch: ${fixtures.join(", ")}`);
  }
  if (artifacts.migrationReport.demo.codemodTarget !== artifacts.migrationReport.target) {
    throw new Error("Migration report target does not match its CLI demo target");
  }
  const manifestPaths = new Set(artifacts.manifest.files.map((file) => file.repositoryPath));
  for (const path of [
    "examples/migration-workbench/public/artifacts/v1/migration-report.v1.json",
    "examples/migration-workbench/public/artifacts/v1/widget-readiness.v1.json",
    "examples/migration-workbench/public/artifacts/v1/maplibre-assessment.v1.json",
    "examples/migration-workbench/public/artifacts/v1/migration.v1.patch",
    "examples/migration-workbench/src/generated/migrated-main.js",
  ]) {
    if (!manifestPaths.has(path)) throw new Error(`Migration workbench manifest is missing ${path}`);
  }
}
