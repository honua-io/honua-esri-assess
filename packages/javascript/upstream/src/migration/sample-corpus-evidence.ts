import path from "node:path";

import {
  type CodemodConstructorKind,
  type CodemodTarget,
  type EsriCompatCodemodResult,
  type MigrationTodo,
  runEsriCompatCodemod,
} from "./codemod.js";
import {
  type ArcGisServiceReference,
  type EsriSampleCorpusManifest,
  type EsriSampleCorpusSample,
  type EsriSampleFixtureAnalysis,
  type EsriSampleGuardrailFlag,
  type EsriSampleLicenseMetadata,
  type EsriSampleSkipReason,
  type EsriSampleSourceReference,
  type EsriSampleTermsMetadata,
  type PortalItemReference,
  analyzeEsriSampleFixture,
  loadEsriSampleCorpusManifest,
} from "./sample-corpus.js";

const DEFAULT_CODEMOD_TARGET: CodemodTarget = "honua-maplibre";

// Skip reasons that prevent the codemod from running against a sample. These
// correspond to samples that would require Esri credentials, premium service
// access, or private Portal content to even render ? the codemod has nothing
// useful to say about them in a fixture-only lane, so we record them as
// `status: "skipped"` evidence and surface the manifest skip reasons.
const RUN_BLOCKING_SKIP_REASONS: ReadonlySet<EsriSampleSkipReason> = new Set([
  "requires-api-key",
  "requires-oauth",
  "premium-service",
  "private-content",
  "unclear-content-terms",
  "unsupported-sample-family",
]);

export type EsriSampleEvidenceStatus = "migrated" | "skipped" | "error";

export interface EsriSampleEvidenceClassification {
  auto: number;
  manual: number;
  unsupported: number;
}

export interface EsriSampleEvidenceManualTodoReason {
  reason: string;
  count: number;
  kinds: CodemodConstructorKind[];
}

export interface EsriSampleEvidenceManualTodos {
  total: number;
  reasons: EsriSampleEvidenceManualTodoReason[];
}

export interface EsriSampleEvidenceUrlRewriteSummary {
  total: number;
  byKind: Record<string, number>;
}

export interface EsriSampleEvidenceRecord {
  sampleId: string;
  status: EsriSampleEvidenceStatus;
  reason?: string;
  codemodTarget: CodemodTarget;
  sourceRef: EsriSampleSourceReference;
  license: EsriSampleLicenseMetadata;
  terms: EsriSampleTermsMetadata;
  skipReasons: EsriSampleSkipReason[];
  classification: EsriSampleEvidenceClassification;
  manualTodos: EsriSampleEvidenceManualTodos;
  referencedServices: ArcGisServiceReference[];
  portalItems: PortalItemReference[];
  guardrailFlags: EsriSampleGuardrailFlag[];
  urlRewriteSummary: EsriSampleEvidenceUrlRewriteSummary;
  unsupportedApis: string[];
  filesScanned: number;
  filesChanged: number;
}

export interface EsriSampleEvidenceStatusCounts {
  migrated: number;
  skipped: number;
  error: number;
}

export interface EsriSampleEvidenceAggregate {
  sampleCount: number;
  codemodTarget: CodemodTarget;
  statusCounts: EsriSampleEvidenceStatusCounts;
  totals: EsriSampleEvidenceClassification;
  manualTodoTotal: number;
  uniqueUnsupportedApis: string[];
}

export interface EsriSampleCorpusEvidence {
  manifestPath?: string;
  codemodTarget: CodemodTarget;
  samples: EsriSampleEvidenceRecord[];
  aggregate: EsriSampleEvidenceAggregate;
}

export interface EmitEsriSampleCorpusEvidenceOptions {
  manifestPath: string;
  codemodTarget?: CodemodTarget;
}

export interface BuildEsriSampleCorpusEvidenceOptions {
  manifest: EsriSampleCorpusManifest;
  manifestDir: string;
  codemodTarget?: CodemodTarget;
}

/**
 * Loads the curated manifest from `manifestPath`, runs the migration codemod
 * (default target: `honua-maplibre`) against each runnable fixture, and emits
 * a structured per-sample + aggregate evidence record. Skipped samples are
 * surfaced as `status: "skipped"` with the manifest skip reason; no live Esri
 * services are contacted.
 */
export function emitEsriSampleCorpusEvidence(options: EmitEsriSampleCorpusEvidenceOptions): EsriSampleCorpusEvidence {
  const manifest = loadEsriSampleCorpusManifest(options.manifestPath);
  const manifestDir = path.dirname(path.resolve(options.manifestPath));
  const evidence = buildEsriSampleCorpusEvidence({
    manifest,
    manifestDir,
    codemodTarget: options.codemodTarget,
  });
  return {
    ...evidence,
    manifestPath: path.resolve(options.manifestPath),
  };
}

/**
 * Build evidence directly from an already-loaded manifest. Useful when the
 * caller has already parsed the manifest and wants to avoid re-reading from
 * disk. Behaves identically to `emitEsriSampleCorpusEvidence` otherwise.
 */
export function buildEsriSampleCorpusEvidence(options: BuildEsriSampleCorpusEvidenceOptions): EsriSampleCorpusEvidence {
  const codemodTarget = options.codemodTarget ?? DEFAULT_CODEMOD_TARGET;
  const samples = options.manifest.samples.map((sample) =>
    buildSampleEvidence(sample, options.manifestDir, codemodTarget),
  );
  const aggregate = summarizeEvidence(samples, codemodTarget);
  return {
    codemodTarget,
    samples,
    aggregate,
  };
}

function buildSampleEvidence(
  sample: EsriSampleCorpusSample,
  manifestDir: string,
  codemodTarget: CodemodTarget,
): EsriSampleEvidenceRecord {
  const analysis = analyzeEsriSampleFixture(sample, { manifestDir });
  const skipReason = resolveSkipReason(sample);

  if (skipReason) {
    return buildSkippedEvidence(sample, analysis, codemodTarget, skipReason);
  }

  let codemodResult: EsriCompatCodemodResult;
  try {
    codemodResult = runEsriCompatCodemod({
      rootDir: path.resolve(manifestDir, sample.fixture.root),
      target: codemodTarget,
      write: false,
      annotateTodos: false,
    });
  } catch (error) {
    return buildErrorEvidence(sample, analysis, codemodTarget, error);
  }

  return buildMigratedEvidence(sample, analysis, codemodTarget, codemodResult);
}

function buildMigratedEvidence(
  sample: EsriSampleCorpusSample,
  analysis: EsriSampleFixtureAnalysis,
  codemodTarget: CodemodTarget,
  codemodResult: EsriCompatCodemodResult,
): EsriSampleEvidenceRecord {
  const metrics = codemodResult.metrics;
  const classification: EsriSampleEvidenceClassification = {
    auto: metrics.autoMigratedCallSites,
    manual: metrics.manualCallSites,
    unsupported: countUnsupportedCallSites(codemodResult.manualTodos),
  };
  const manualTodos = summarizeManualTodos(codemodResult.manualTodos);
  const unsupportedApis = collectUnsupportedApis(codemodResult.manualTodos);
  const urlRewriteSummary = buildUrlRewriteSummary(analysis.serviceUrls);

  return {
    sampleId: sample.id,
    status: "migrated",
    codemodTarget,
    sourceRef: sample.source,
    license: sample.license,
    terms: sample.terms,
    skipReasons: analysis.skipReasons,
    classification,
    manualTodos,
    referencedServices: analysis.serviceUrls,
    portalItems: analysis.portalItems,
    guardrailFlags: analysis.guardrailFlags,
    urlRewriteSummary,
    unsupportedApis,
    filesScanned: codemodResult.filesScanned,
    filesChanged: codemodResult.filesChanged,
  };
}

function buildSkippedEvidence(
  sample: EsriSampleCorpusSample,
  analysis: EsriSampleFixtureAnalysis,
  codemodTarget: CodemodTarget,
  reason: string,
): EsriSampleEvidenceRecord {
  return {
    sampleId: sample.id,
    status: "skipped",
    reason,
    codemodTarget,
    sourceRef: sample.source,
    license: sample.license,
    terms: sample.terms,
    skipReasons: analysis.skipReasons,
    classification: { auto: 0, manual: 0, unsupported: 0 },
    manualTodos: { total: 0, reasons: [] },
    referencedServices: analysis.serviceUrls,
    portalItems: analysis.portalItems,
    guardrailFlags: analysis.guardrailFlags,
    urlRewriteSummary: buildUrlRewriteSummary(analysis.serviceUrls),
    unsupportedApis: [],
    filesScanned: analysis.filesScanned,
    filesChanged: 0,
  };
}

function buildErrorEvidence(
  sample: EsriSampleCorpusSample,
  analysis: EsriSampleFixtureAnalysis,
  codemodTarget: CodemodTarget,
  error: unknown,
): EsriSampleEvidenceRecord {
  const message = error instanceof Error ? error.message : String(error);
  return {
    sampleId: sample.id,
    status: "error",
    reason: `codemod failed: ${message}`,
    codemodTarget,
    sourceRef: sample.source,
    license: sample.license,
    terms: sample.terms,
    skipReasons: analysis.skipReasons,
    classification: { auto: 0, manual: 0, unsupported: 0 },
    manualTodos: { total: 0, reasons: [] },
    referencedServices: analysis.serviceUrls,
    portalItems: analysis.portalItems,
    guardrailFlags: analysis.guardrailFlags,
    urlRewriteSummary: buildUrlRewriteSummary(analysis.serviceUrls),
    unsupportedApis: [],
    filesScanned: analysis.filesScanned,
    filesChanged: 0,
  };
}

function resolveSkipReason(sample: EsriSampleCorpusSample): string | undefined {
  if (sample.status !== "skipped") {
    return undefined;
  }
  const reasons = sample.skipReasons ?? [];
  const blocking = reasons.filter((reason) => RUN_BLOCKING_SKIP_REASONS.has(reason));
  if (blocking.length === 0) {
    // Sample is marked skipped but doesn't list a run-blocking reason ? record
    // the raw manifest reasons (or a generic fallback) so callers can still
    // see why CI elected to skip it.
    return reasons.length > 0 ? reasons.join(", ") : "manifest marks sample as skipped";
  }
  return blocking.join(", ");
}

function countUnsupportedCallSites(todos: readonly MigrationTodo[]): number {
  return todos.filter((todo) => todo.difficulty === "complex").length;
}

function summarizeManualTodos(todos: readonly MigrationTodo[]): EsriSampleEvidenceManualTodos {
  const grouped = new Map<string, { count: number; kinds: Set<CodemodConstructorKind> }>();
  for (const todo of todos) {
    let bucket = grouped.get(todo.reason);
    if (!bucket) {
      bucket = { count: 0, kinds: new Set<CodemodConstructorKind>() };
      grouped.set(todo.reason, bucket);
    }
    bucket.count += 1;
    bucket.kinds.add(todo.kind);
  }

  const reasons = Array.from(grouped.entries())
    .map(([reason, bucket]) => ({
      reason,
      count: bucket.count,
      kinds: Array.from(bucket.kinds).sort(),
    }))
    .sort((a, b) => (a.count === b.count ? a.reason.localeCompare(b.reason) : b.count - a.count));

  return { total: todos.length, reasons };
}

function collectUnsupportedApis(todos: readonly MigrationTodo[]): string[] {
  const kinds = new Set<CodemodConstructorKind>();
  for (const todo of todos) {
    kinds.add(todo.kind);
  }
  return Array.from(kinds).sort();
}

function buildUrlRewriteSummary(services: readonly ArcGisServiceReference[]): EsriSampleEvidenceUrlRewriteSummary {
  const byKind: Record<string, number> = {};
  for (const service of services) {
    byKind[service.kind] = (byKind[service.kind] ?? 0) + 1;
  }
  return { total: services.length, byKind };
}

function summarizeEvidence(
  samples: readonly EsriSampleEvidenceRecord[],
  codemodTarget: CodemodTarget,
): EsriSampleEvidenceAggregate {
  const statusCounts: EsriSampleEvidenceStatusCounts = { migrated: 0, skipped: 0, error: 0 };
  const totals: EsriSampleEvidenceClassification = { auto: 0, manual: 0, unsupported: 0 };
  let manualTodoTotal = 0;
  const uniqueUnsupportedApis = new Set<string>();

  for (const sample of samples) {
    statusCounts[sample.status] += 1;
    totals.auto += sample.classification.auto;
    totals.manual += sample.classification.manual;
    totals.unsupported += sample.classification.unsupported;
    manualTodoTotal += sample.manualTodos.total;
    for (const api of sample.unsupportedApis) {
      uniqueUnsupportedApis.add(api);
    }
  }

  return {
    sampleCount: samples.length,
    codemodTarget,
    statusCounts,
    totals,
    manualTodoTotal,
    uniqueUnsupportedApis: Array.from(uniqueUnsupportedApis).sort(),
  };
}
