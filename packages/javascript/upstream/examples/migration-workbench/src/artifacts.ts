import type {
  MapLibreAssessmentArtifact,
  MigrationWorkbenchArtifactSet,
  MigrationWorkbenchManifest,
  MigrationWorkbenchReportArtifact,
  WidgetReadinessArtifact,
} from "./types.js";

const ARTIFACT_FILENAMES = {
  manifest: "manifest.v1.json",
  migrationReport: "migration-report.v1.json",
  widgetReadiness: "widget-readiness.v1.json",
  maplibreAssessment: "maplibre-assessment.v1.json",
  diff: "migration.v1.patch",
} as const;

export interface LoadMigrationWorkbenchArtifactsOptions {
  readonly fetchFn?: typeof fetch;
  readonly artifactBaseUrl?: string;
}

export async function loadMigrationWorkbenchArtifacts(
  options: LoadMigrationWorkbenchArtifactsOptions = {},
): Promise<MigrationWorkbenchArtifactSet> {
  const fetchFn = options.fetchFn ?? globalThis.fetch.bind(globalThis);
  const artifactBaseUrl = (options.artifactBaseUrl ?? "/artifacts/v1").replace(/\/$/u, "");
  const [manifest, migrationReport, widgetReadiness, maplibreAssessment, diff] = await Promise.all([
    fetchJson(fetchFn, `${artifactBaseUrl}/${ARTIFACT_FILENAMES.manifest}`),
    fetchJson(fetchFn, `${artifactBaseUrl}/${ARTIFACT_FILENAMES.migrationReport}`),
    fetchJson(fetchFn, `${artifactBaseUrl}/${ARTIFACT_FILENAMES.widgetReadiness}`),
    fetchJson(fetchFn, `${artifactBaseUrl}/${ARTIFACT_FILENAMES.maplibreAssessment}`),
    fetchText(fetchFn, `${artifactBaseUrl}/${ARTIFACT_FILENAMES.diff}`),
  ]);

  return {
    manifest: parseManifest(manifest),
    migrationReport: parseMigrationReport(migrationReport),
    widgetReadiness: parseWidgetReadiness(widgetReadiness),
    maplibreAssessment: parseMapLibreAssessment(maplibreAssessment),
    diff,
  };
}

export function parseManifest(value: unknown): MigrationWorkbenchManifest {
  const record = requireRecord(value, "manifest");
  requireSchema(record, "honua.migration-workbench.manifest.v1", "manifest");
  requireString(record.artifactSet, "manifest.artifactSet");
  requireString(record.fixture, "manifest.fixture");
  requireArray(record.commands, "manifest.commands");
  requireArray(record.files, "manifest.files");
  requireRecord(record.provenance, "manifest.provenance");
  return record as unknown as MigrationWorkbenchManifest;
}

export function parseMigrationReport(value: unknown): MigrationWorkbenchReportArtifact {
  const record = requireRecord(value, "migration report");
  requireSchema(record, "honua.migration-workbench.report.v1", "migration report");
  const demo = requireRecord(record.demo, "migration report.demo");
  const migration = requireRecord(demo.migration, "migration report.demo.migration");
  requireRecord(migration.scanReport, "migration report.demo.migration.scanReport");
  requireRecord(migration.codemodResult, "migration report.demo.migration.codemodResult");
  requireArray(migration.gates, "migration report.demo.migration.gates");
  const behaviorProof = requireRecord(record.behaviorProof, "migration report.behaviorProof");
  requireArray(behaviorProof.assertions, "migration report.behaviorProof.assertions");
  requireRecord(record.patchProof, "migration report.patchProof");
  return record as unknown as MigrationWorkbenchReportArtifact;
}

export function parseWidgetReadiness(value: unknown): WidgetReadinessArtifact {
  const record = requireRecord(value, "widget readiness");
  requireSchema(record, "honua.migration-workbench.widget-readiness.v1", "widget readiness");
  const report = requireRecord(record.report, "widget readiness.report");
  requireArray(report.widgets, "widget readiness.report.widgets");
  requireRecord(report.summary, "widget readiness.report.summary");
  return record as unknown as WidgetReadinessArtifact;
}

export function parseMapLibreAssessment(value: unknown): MapLibreAssessmentArtifact {
  const record = requireRecord(value, "MapLibre assessment");
  requireSchema(record, "honua.migration-workbench.maplibre-assessment.v1", "MapLibre assessment");
  const report = requireRecord(record.report, "MapLibre assessment.report");
  requireRecord(report.codemodResult, "MapLibre assessment.report.codemodResult");
  requireArray(report.gates, "MapLibre assessment.report.gates");
  const residuals = requireRecord(record.residuals, "MapLibre assessment.residuals");
  requireArray(residuals.manualTodos, "MapLibre assessment.residuals.manualTodos");
  requireArray(residuals.unsupportedModules, "MapLibre assessment.residuals.unsupportedModules");
  return record as unknown as MapLibreAssessmentArtifact;
}

async function fetchJson(fetchFn: typeof fetch, url: string): Promise<unknown> {
  const response = await fetchFn(url, { method: "GET", credentials: "omit" });
  if (!response.ok) throw new Error(`Unable to load ${url}: HTTP ${response.status}`);
  return response.json();
}

async function fetchText(fetchFn: typeof fetch, url: string): Promise<string> {
  const response = await fetchFn(url, { method: "GET", credentials: "omit" });
  if (!response.ok) throw new Error(`Unable to load ${url}: HTTP ${response.status}`);
  return response.text();
}

function requireSchema(record: Record<string, unknown>, expected: string, label: string): void {
  if (record.schemaVersion !== expected) {
    throw new Error(`${label} has unsupported schemaVersion ${String(record.schemaVersion)}`);
  }
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function requireArray(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${label} must be a non-empty string`);
  return value;
}
