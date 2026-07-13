#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { parseWebMap } from "../webmap/parse.js";
import type { WebMapJson } from "../webmap/types.js";
import { type CodemodMetricsByKind, type CodemodTarget, runEsriCompatCodemod } from "./codemod.js";
import {
  type ContentImportReport,
  runContentExport,
  runContentImport,
  runContentReconcile,
  runContentScan,
} from "./content.js";
import { MIGRATION_DEMO_PRIMARY_TARGET } from "./demo-targets.js";
import { parseGeoservicesServiceUrl, runMigrationDemo } from "./demo.js";
import { evaluateMigrationGates } from "./gating.js";
import { getJsParityMatrix, summarizeJsParityMatrix } from "./parity-matrix.js";
import { runLayerReconciliation, summarizeLayerReconciliation } from "./reconcile.js";
import { buildJsMigrationReport } from "./report.js";
import { getJsRuntimeParityMatrix, summarizeJsRuntimeParity } from "./runtime-matrix.js";
import { emitEsriSampleCorpusEvidence } from "./sample-corpus-evidence.js";
import { scanArcGisUsage, summarizeArcGisScan } from "./scanner.js";
import {
  buildWidgetReadinessReport,
  evaluateWidgetGate,
  formatWidgetReadinessMarkdown,
  formatWidgetReadinessTable,
  scanWidgetUsage,
} from "./widget-scanner.js";

interface ParsedArgs {
  command:
    | "scan"
    | "widgets"
    | "codemod"
    | "reconcile"
    | "matrix"
    | "runtime-matrix"
    | "fixtures"
    | "demo"
    | "content-webmap"
    | "content"
    | "corpus-evidence";
  target: string;
  contentAction?: "scan" | "export" | "import" | "reconcile";
  codemodTarget: CodemodTarget;
  write: boolean;
  annotateTodos: boolean;
  failOnManual: boolean;
  failOnUnhandled: boolean;
  failOnBlocked: boolean;
  maxManualRatio?: number;
  maxManualInterventionRatio?: number;
  reportPath?: string;
  compatImportPath?: string;
  sourceBaseUrl?: string;
  sourceServiceId?: string;
  targetBaseUrl?: string;
  targetServiceId?: string;
  layerId?: number;
  sampleSize?: number;
  fixtureNames?: string[];
  fixtureName?: string;
  fixturesRoot?: string;
  outputDir?: string;
  adminBaseUrl?: string;
  adminApiKey?: string;
  sourceServiceUrl?: string;
  tableName?: string;
  pollIntervalMs?: number;
  timeoutSeconds?: number;
  skipImport: boolean;
  skipReconcile: boolean;
  contentInputPath?: string;
  contentOutputPath?: string;
  contentSourceUrlPrefix?: string;
  contentTargetUrlPrefix?: string;
  contentIncludeBasemap: boolean;
  contentPortalUrl?: string;
  contentToken?: string;
  contentSourceDir?: string;
  contentOutputDir?: string;
  contentImportReportPath?: string;
  contentTablePrefix?: string;
  contentIncludeFeatures: boolean;
  contentIncludeWebMaps: boolean;
  contentIncludeHostedLayers: boolean;
  corpusPath?: string;
  corpusOutputDir?: string;
  widgetOutput: "table" | "json" | "markdown";
  gatePct?: number;
}

interface FixtureMetricSnapshot {
  fixture: string;
  rootDir: string;
  readiness: "ready" | "assisted" | "blocked";
  scanSummary: string;
  flags: string[];
  totalCallSites: number;
  autoMigratedCallSites: number;
  manualCallSites: number;
  manualRewrite: {
    numerator: number;
    denominator: number;
    ratio: number;
  };
  manualIntervention: {
    numerator: number;
    denominator: number;
    ratio: number;
    unhandledUsageHits: number;
  };
  gates: string;
}

interface FixtureMetricsSummary {
  fixtureCount: number;
  ready: number;
  assisted: number;
  blocked: number;
  totalCallSites: number;
  autoMigratedCallSites: number;
  manualCallSites: number;
  unhandledUsageHits: number;
  manualRewriteNumerator: number;
  manualRewriteDenominator: number;
  manualRewriteRatio: number;
  manualInterventionNumerator: number;
  manualInterventionDenominator: number;
  manualInterventionRatio: number;
}

interface FixtureMetricsGateOptions {
  failOnManual: boolean;
  failOnUnhandled: boolean;
  failOnBlocked: boolean;
  maxManualRatio?: number;
  maxManualInterventionRatio?: number;
}

interface FixtureMetricsGateEvaluation extends FixtureMetricsGateOptions {
  passed: boolean;
  failures: string[];
}

interface FixtureMetricsReport {
  codemodTarget: CodemodTarget;
  fixturesRoot: string;
  fixtureNames: string[];
  generatedAt: string;
  summary: FixtureMetricsSummary;
  gates: FixtureMetricsGateEvaluation;
  fixtures: FixtureMetricSnapshot[];
}

const DEFAULT_REAL_SAMPLE_FIXTURE_NAMES = [
  "esri-real-sample-incident-command-app",
  "esri-real-sample-ops-center-app",
  "esri-real-sample-editing-app",
  "esri-real-sample-network-app",
] as const;
const DEFAULT_DEMO_FIXTURE_NAME = MIGRATION_DEMO_PRIMARY_TARGET.fixtureName;

const parsed = parseArgs(process.argv.slice(2));
if (!parsed) {
  printUsage();
  process.exitCode = 1;
} else {
  if (parsed.command === "scan") {
    runScan(parsed.target, parsed.reportPath);
  } else if (parsed.command === "widgets") {
    runWidgets(parsed);
  } else if (parsed.command === "content") {
    void runContent(parsed).catch((error) => {
      process.stderr.write(`contentError=${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 1;
    });
  } else if (parsed.command === "matrix") {
    runMatrix(parsed.reportPath);
  } else if (parsed.command === "runtime-matrix") {
    runRuntimeMatrix(parsed.reportPath);
  } else if (parsed.command === "content-webmap") {
    runContentWebMap(parsed);
  } else if (parsed.command === "fixtures") {
    runFixtures(parsed);
  } else if (parsed.command === "demo") {
    void runDemo(parsed).catch((error) => {
      process.stderr.write(`demoError=${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 1;
    });
  } else if (parsed.command === "reconcile") {
    void runReconcile(parsed).catch((error) => {
      process.stderr.write(`reconcileError=${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 1;
    });
  } else if (parsed.command === "corpus-evidence") {
    try {
      runCorpusEvidence(parsed);
    } catch (error) {
      process.stderr.write(`corpusEvidenceError=${error instanceof Error ? error.message : String(error)}\n`);
      process.exitCode = 1;
    }
  } else {
    runCodemod(parsed);
  }
}

function runMatrix(reportPath?: string): void {
  const matrix = getJsParityMatrix();
  const summary = summarizeJsParityMatrix(matrix);
  process.stdout.write(
    [
      `entries=${matrix.length}`,
      `honuaCompat=${summary.honuaCompat.compat}`,
      `honuaAssisted=${summary.honuaCompat.assisted}`,
      `honuaUnsupported=${summary.honuaCompat.unsupported}`,
      `honuaMapLibreNative=${summary.honuaMapLibre.native}`,
      `honuaMapLibreAssisted=${summary.honuaMapLibre.assisted}`,
      `honuaMapLibreUnsupported=${summary.honuaMapLibre.unsupported}`,
      `esriLeafletCompat=${summary.esriLeaflet.compat}`,
      `esriLeafletAssisted=${summary.esriLeaflet.assisted}`,
      `esriLeafletUnsupported=${summary.esriLeaflet.unsupported}`,
    ].join(" "),
  );
  process.stdout.write("\n");
  process.stdout.write(`${JSON.stringify({ summary, matrix }, null, 2)}\n`);

  if (reportPath) {
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify({ summary, matrix }, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${reportPath}\n`);
  }
}

function runRuntimeMatrix(reportPath?: string): void {
  const matrix = getJsRuntimeParityMatrix();
  const summary = summarizeJsRuntimeParity(matrix);
  process.stdout.write(
    [
      `entries=${matrix.length}`,
      `honuaCompat=${summary.honuaCompat.compat}`,
      `honuaAssisted=${summary.honuaCompat.assisted}`,
      `honuaUnsupported=${summary.honuaCompat.unsupported}`,
      `honuaMapLibreNative=${summary.honuaMapLibre.native}`,
      `honuaMapLibreAssisted=${summary.honuaMapLibre.assisted}`,
      `honuaMapLibreUnsupported=${summary.honuaMapLibre.unsupported}`,
      `esriLeafletCompat=${summary.esriLeaflet.compat}`,
      `esriLeafletAssisted=${summary.esriLeaflet.assisted}`,
      `esriLeafletUnsupported=${summary.esriLeaflet.unsupported}`,
    ].join(" "),
  );
  process.stdout.write("\n");
  process.stdout.write(`${JSON.stringify({ summary, matrix }, null, 2)}\n`);

  if (reportPath) {
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify({ summary, matrix }, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${reportPath}\n`);
  }
}

function runCorpusEvidence(args: ParsedArgs): void {
  const corpusRoot = path.resolve(
    args.corpusPath ?? path.join(process.cwd(), "test", "fixtures", "esri-sample-corpus"),
  );
  if (!args.corpusOutputDir) {
    throw new Error("corpus-evidence requires --out <dir>");
  }
  const outputDir = path.resolve(args.corpusOutputDir);

  const manifestPath = path.join(corpusRoot, "manifest.json");
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`corpus manifest not found at ${manifestPath}`);
  }

  const evidence = emitEsriSampleCorpusEvidence({
    manifestPath,
    codemodTarget: args.codemodTarget,
  });

  const samplesDir = path.join(outputDir, "samples");
  fs.mkdirSync(samplesDir, { recursive: true });
  for (const sample of evidence.samples) {
    const samplePath = path.join(samplesDir, `${sample.sampleId}.json`);
    fs.writeFileSync(samplePath, `${JSON.stringify(sample, null, 2)}\n`, "utf8");
  }

  const aggregatePath = path.join(outputDir, "corpus-evidence.json");
  fs.writeFileSync(aggregatePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");

  process.stdout.write(
    [
      "corpusEvidence",
      `samples=${evidence.aggregate.sampleCount}`,
      `migrated=${evidence.aggregate.statusCounts.migrated}`,
      `skipped=${evidence.aggregate.statusCounts.skipped}`,
      `error=${evidence.aggregate.statusCounts.error}`,
      `target=${evidence.codemodTarget}`,
      `out=${outputDir}`,
    ].join(" "),
  );
  process.stdout.write("\n");
  process.stdout.write(`aggregateWritten=${aggregatePath}\n`);
  process.stdout.write(`samplesDir=${samplesDir}\n`);
}

function runScan(target: string, reportPath?: string): void {
  const report = scanArcGisUsage(target);
  const summary = summarizeArcGisScan(report);

  process.stdout.write(`${summary}\n`);
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);

  if (reportPath) {
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${reportPath}\n`);
  }
}

function runWidgets(args: ParsedArgs): void {
  const scan = scanWidgetUsage(args.target);
  const report = buildWidgetReadinessReport(scan);

  if (args.widgetOutput === "json") {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } else if (args.widgetOutput === "markdown") {
    process.stdout.write(formatWidgetReadinessMarkdown(report));
  } else {
    process.stdout.write(`${formatWidgetReadinessTable(report)}\n`);
  }

  if (args.reportPath) {
    const reportPath = path.resolve(args.reportPath);
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${reportPath}\n`);
  }

  if (args.gatePct !== undefined) {
    const gate = evaluateWidgetGate(report, args.gatePct);
    process.stdout.write(`widgetGate=${gate.passed ? "pass" : "fail"} automatedPct=${gate.automatedPct.toFixed(1)}\n`);
    if (!gate.passed) {
      process.stdout.write("gatingFailures:\n");
      for (const failure of gate.failures) {
        process.stdout.write(`- ${failure}\n`);
      }
      process.exitCode = 2;
    }
  }
}

async function runContent(args: ParsedArgs): Promise<void> {
  const action = args.contentAction;
  if (!action) {
    throw new Error("content action is required (scan|export|import|reconcile)");
  }

  if (action === "scan") {
    const portalUrl = args.contentPortalUrl ?? args.target;
    const report = await runContentScan({
      portalUrl,
      token: args.contentToken,
    });
    process.stdout.write(
      [
        "contentScan",
        `portal=${report.portalUrl}`,
        `webmaps=${report.webMaps.length}`,
        `hostedFeatureServices=${report.hostedFeatureServices.length}`,
      ].join(" "),
    );
    process.stdout.write("\n");
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    if (args.reportPath) {
      const reportPath = path.resolve(args.reportPath);
      fs.mkdirSync(path.dirname(reportPath), { recursive: true });
      fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
      process.stdout.write(`reportWritten=${reportPath}\n`);
    }
    return;
  }

  if (action === "export") {
    const portalUrl = args.contentPortalUrl ?? args.target;
    const outputDir = path.resolve(args.contentOutputDir ?? path.join(process.cwd(), "content-export"));
    const report = await runContentExport({
      portalUrl,
      token: args.contentToken,
      outputDir,
      includeFeatures: args.contentIncludeFeatures,
      includeWebMaps: args.contentIncludeWebMaps,
      includeHostedLayers: args.contentIncludeHostedLayers,
    });
    process.stdout.write(
      [
        "contentExport",
        `portal=${report.portalUrl}`,
        `webmaps=${report.exportedWebMaps.length}`,
        `hostedFeatureServices=${report.exportedHostedFeatureServices.length}`,
        `manifest=${report.manifestPath}`,
      ].join(" "),
    );
    process.stdout.write("\n");
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
    if (args.reportPath) {
      const reportPath = path.resolve(args.reportPath);
      fs.mkdirSync(path.dirname(reportPath), { recursive: true });
      fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
      process.stdout.write(`reportWritten=${reportPath}\n`);
    }
    return;
  }

  if (action === "import") {
    const sourceDir = path.resolve(args.contentSourceDir ?? args.target);
    const targetBaseUrl = args.targetBaseUrl ?? args.adminBaseUrl;
    if (!targetBaseUrl) {
      throw new Error("content import requires --target <url> or --admin-base-url <url>");
    }

    const report = await runContentImport({
      sourceDir,
      outputDir: args.contentOutputDir,
      targetBaseUrl,
      adminApiKey: args.adminApiKey,
      includeWebMaps: args.contentIncludeWebMaps,
      includeHostedLayers: args.contentIncludeHostedLayers,
      sourceUrlPrefix: args.contentSourceUrlPrefix,
      targetUrlPrefix: args.contentTargetUrlPrefix,
      tablePrefix: args.contentTablePrefix,
      pollIntervalMs:
        typeof args.pollIntervalMs === "number" ? Math.max(1, Math.trunc(args.pollIntervalMs)) : undefined,
      timeoutMs:
        typeof args.timeoutSeconds === "number" ? Math.max(1, Math.trunc(args.timeoutSeconds * 1_000)) : undefined,
    });

    writeContentImportOutput(report, args.reportPath);
    return;
  }

  const sourceDir = path.resolve(args.contentSourceDir ?? args.target);
  const report = runContentReconcile({
    sourceDir,
    importReportPath: args.contentImportReportPath,
    outputPath: args.contentOutputDir,
  });
  process.stdout.write(
    [
      "contentReconcile",
      `hostedLayersPassed=${report.summary.hostedLayersPassed}`,
      `hostedLayersFailed=${report.summary.hostedLayersFailed}`,
      `webMapsPassed=${report.summary.webMapsPassed}`,
      `webMapsManual=${report.summary.webMapsManual}`,
      `webMapsFailed=${report.summary.webMapsFailed}`,
      `report=${report.reportPath}`,
    ].join(" "),
  );
  process.stdout.write("\n");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  if (args.reportPath) {
    const reportPath = path.resolve(args.reportPath);
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${reportPath}\n`);
  }
}

function writeContentImportOutput(report: ContentImportReport, reportPathOverride: string | undefined): void {
  process.stdout.write(
    [
      "contentImport",
      `hostedLayersCompleted=${report.summary.hostedLayersCompleted}`,
      `hostedLayersFailed=${report.summary.hostedLayersFailed}`,
      `webMapsConverted=${report.summary.webMapsConverted}`,
      `webMapsFailed=${report.summary.webMapsFailed}`,
      `webMapsManual=${report.summary.webMapsManualIntervention}`,
      `report=${report.reportPath}`,
    ].join(" "),
  );
  process.stdout.write("\n");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);

  if (reportPathOverride) {
    const reportPath = path.resolve(reportPathOverride);
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${reportPath}\n`);
  }
}

function runContentWebMap(args: ParsedArgs): void {
  const inputPath = path.resolve(args.contentInputPath ?? args.target);
  if (!fs.existsSync(inputPath)) {
    throw new Error(`WebMap input file does not exist: ${inputPath}`);
  }

  const raw = fs.readFileSync(inputPath, "utf8");
  const input = JSON.parse(raw) as WebMapJson;
  const { webMap, rewrittenUrlCount } = rewriteWebMapUrls(
    input,
    args.contentSourceUrlPrefix,
    args.contentTargetUrlPrefix,
  );
  const result = parseWebMap(webMap, { includeBasemap: args.contentIncludeBasemap });

  const outputPath = path.resolve(
    args.contentOutputPath ??
      path.join(path.dirname(inputPath), `${path.basename(inputPath, path.extname(inputPath))}.honua.json`),
  );
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });

  const outputDocument = {
    generatedAt: new Date().toISOString(),
    inputPath,
    rewrittenUrlCount,
    includeBasemap: args.contentIncludeBasemap,
    sourceUrlPrefix: args.contentSourceUrlPrefix,
    targetUrlPrefix: args.contentTargetUrlPrefix,
    result,
  };
  fs.writeFileSync(outputPath, `${JSON.stringify(outputDocument, null, 2)}\n`, "utf8");

  const report = buildContentWebMapReport(inputPath, outputPath, rewrittenUrlCount, result);
  process.stdout.write(
    [
      "contentWebMap",
      `sources=${report.sourceCount}`,
      `layers=${report.layerCount}`,
      `warnings=${report.warningCount}`,
      `rewrittenUrls=${report.rewrittenUrlCount}`,
      `manualIntervention=${report.manualInterventionNeeded ? "yes" : "no"}`,
    ].join(" "),
  );
  process.stdout.write("\n");
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(`outputWritten=${outputPath}\n`);

  if (args.reportPath) {
    const reportPath = path.resolve(args.reportPath);
    fs.mkdirSync(path.dirname(reportPath), { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${reportPath}\n`);
  }
}

function rewriteWebMapUrls(
  input: WebMapJson,
  sourcePrefix: string | undefined,
  targetPrefix: string | undefined,
): { webMap: WebMapJson; rewrittenUrlCount: number } {
  const webMap = structuredClone(input);
  if (!sourcePrefix || !targetPrefix) {
    return { webMap, rewrittenUrlCount: 0 };
  }

  let rewrittenUrlCount = 0;
  const rewrite = (url: unknown): string | undefined => {
    if (typeof url !== "string") return undefined;
    if (!url.startsWith(sourcePrefix)) return undefined;
    return `${targetPrefix}${url.slice(sourcePrefix.length)}`;
  };

  for (const opLayer of webMap.operationalLayers ?? []) {
    const nextUrl = rewrite(opLayer.url);
    if (nextUrl) {
      opLayer.url = nextUrl;
      rewrittenUrlCount += 1;
    }
  }

  for (const baseMapLayer of webMap.baseMap?.baseMapLayers ?? []) {
    const nextUrl = rewrite(baseMapLayer.url);
    if (nextUrl) {
      baseMapLayer.url = nextUrl;
      rewrittenUrlCount += 1;
    }
  }

  return { webMap, rewrittenUrlCount };
}

function buildContentWebMapReport(
  inputPath: string,
  outputPath: string,
  rewrittenUrlCount: number,
  result: ReturnType<typeof parseWebMap>,
): {
  inputPath: string;
  outputPath: string;
  generatedAt: string;
  sourceCount: number;
  layerCount: number;
  warningCount: number;
  rewrittenUrlCount: number;
  warningCodes: Record<string, number>;
  manualInterventionNeeded: boolean;
} {
  const warningCodes: Record<string, number> = {};
  for (const warning of result.warnings) {
    warningCodes[warning.code] = (warningCodes[warning.code] ?? 0) + 1;
  }

  const manualInterventionNeeded = result.warnings.some((warning) =>
    MANUAL_INTERVENTION_WARNING_CODES.has(warning.code),
  );

  return {
    inputPath,
    outputPath,
    generatedAt: new Date().toISOString(),
    sourceCount: Object.keys(result.style.sources).length,
    layerCount: result.style.layers.length,
    warningCount: result.warnings.length,
    rewrittenUrlCount,
    warningCodes,
    manualInterventionNeeded,
  };
}

const MANUAL_INTERVENTION_WARNING_CODES = new Set([
  "unsupported-renderer",
  "unsupported-layer-type",
  "unsupported-feature-collection",
  "unsupported-arcade-expression",
  "unsupported-3d-property",
  "complex-arcade",
  "complex-label-expression",
]);

function runFixtures(args: ParsedArgs): void {
  const fixturesRoot = args.target;
  const fixtureNames =
    args.fixtureNames && args.fixtureNames.length > 0 ? [...args.fixtureNames] : [...DEFAULT_REAL_SAMPLE_FIXTURE_NAMES];
  const report = buildFixtureMetricsReport(fixturesRoot, fixtureNames, args.codemodTarget, {
    failOnManual: args.failOnManual,
    failOnUnhandled: args.failOnUnhandled,
    failOnBlocked: args.failOnBlocked,
    maxManualRatio: args.maxManualRatio,
    maxManualInterventionRatio: args.maxManualInterventionRatio,
  });

  process.stdout.write(
    [
      `fixtures=${report.summary.fixtureCount}`,
      `ready=${report.summary.ready}`,
      `assisted=${report.summary.assisted}`,
      `blocked=${report.summary.blocked}`,
      `autoMigrated=${report.summary.autoMigratedCallSites}`,
      `manual=${report.summary.manualCallSites}`,
      `unhandled=${report.summary.unhandledUsageHits}`,
      `manualRewrite=${report.summary.manualRewriteNumerator}/${report.summary.manualRewriteDenominator}`,
      `manualIntervention=${report.summary.manualInterventionNumerator}/${report.summary.manualInterventionDenominator}`,
      `target=${report.codemodTarget}`,
    ].join(" "),
  );
  process.stdout.write("\n");
  process.stdout.write(`${formatFixtureMetricsTable(report.fixtures)}\n`);
  process.stdout.write(`fixturesGate=${report.gates.passed ? "pass" : "fail"}\n`);
  if (!report.gates.passed) {
    process.stdout.write("gatingFailures:\n");
    for (const failure of report.gates.failures) {
      process.stdout.write(`- ${failure}\n`);
    }
  }
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);

  if (args.reportPath) {
    fs.mkdirSync(path.dirname(args.reportPath), { recursive: true });
    fs.writeFileSync(args.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${args.reportPath}\n`);
  }

  if (!report.gates.passed) {
    process.exitCode = 2;
  }
}

function buildFixtureMetricsReport(
  fixturesRoot: string,
  fixtureNames: readonly string[],
  codemodTarget: CodemodTarget,
  gateOptions: FixtureMetricsGateOptions,
): FixtureMetricsReport {
  const fixtures = fixtureNames.map((fixtureName) =>
    buildFixtureMetricSnapshot(fixturesRoot, fixtureName, codemodTarget),
  );

  const summary = summarizeFixtureMetrics(fixtures);
  const gates = evaluateFixtureMetricsGates(summary, fixtures, gateOptions);
  return {
    codemodTarget,
    fixturesRoot,
    fixtureNames: [...fixtureNames],
    generatedAt: new Date().toISOString(),
    summary,
    gates,
    fixtures,
  };
}

function buildFixtureMetricSnapshot(
  fixturesRoot: string,
  fixtureName: string,
  codemodTarget: CodemodTarget,
): FixtureMetricSnapshot {
  const rootDir = path.join(fixturesRoot, fixtureName);
  if (!fs.existsSync(rootDir)) {
    throw new Error(`Fixture directory does not exist: ${rootDir}`);
  }

  const scanReport = scanArcGisUsage(rootDir);
  const codemodResult = runEsriCompatCodemod({
    rootDir,
    write: false,
    annotateTodos: false,
    target: codemodTarget,
  });
  const report = buildJsMigrationReport(rootDir, codemodResult, scanReport);

  return {
    fixture: fixtureName,
    rootDir,
    readiness: report.readiness,
    scanSummary: report.scanSummary,
    flags: [...report.scanReport.flags],
    totalCallSites: codemodResult.metrics.totalCodemodScopedCallSites,
    autoMigratedCallSites: codemodResult.metrics.autoMigratedCallSites,
    manualCallSites: codemodResult.metrics.manualCallSites,
    manualRewrite: {
      numerator: report.manualRewriteMetric.numerator,
      denominator: report.manualRewriteMetric.denominator,
      ratio: report.manualRewriteMetric.ratio,
    },
    manualIntervention: {
      numerator: report.manualInterventionMetric.numerator,
      denominator: report.manualInterventionMetric.denominator,
      ratio: report.manualInterventionMetric.ratio,
      unhandledUsageHits: report.manualInterventionMetric.unhandledUsageHits,
    },
    gates: formatGateResults(report.gates),
  };
}

function summarizeFixtureMetrics(fixtures: readonly FixtureMetricSnapshot[]): FixtureMetricsSummary {
  const ready = fixtures.filter((fixture) => fixture.readiness === "ready").length;
  const assisted = fixtures.filter((fixture) => fixture.readiness === "assisted").length;
  const blocked = fixtures.filter((fixture) => fixture.readiness === "blocked").length;
  const totalCallSites = fixtures.reduce((sum, fixture) => sum + fixture.totalCallSites, 0);
  const autoMigratedCallSites = fixtures.reduce((sum, fixture) => sum + fixture.autoMigratedCallSites, 0);
  const manualCallSites = fixtures.reduce((sum, fixture) => sum + fixture.manualCallSites, 0);
  const manualRewriteNumerator = fixtures.reduce((sum, fixture) => sum + fixture.manualRewrite.numerator, 0);
  const manualRewriteDenominator = fixtures.reduce((sum, fixture) => sum + fixture.manualRewrite.denominator, 0);
  const manualInterventionNumerator = fixtures.reduce((sum, fixture) => sum + fixture.manualIntervention.numerator, 0);
  const manualInterventionDenominator = fixtures.reduce(
    (sum, fixture) => sum + fixture.manualIntervention.denominator,
    0,
  );
  const unhandledUsageHits = fixtures.reduce((sum, fixture) => sum + fixture.manualIntervention.unhandledUsageHits, 0);

  return {
    fixtureCount: fixtures.length,
    ready,
    assisted,
    blocked,
    totalCallSites,
    autoMigratedCallSites,
    manualCallSites,
    unhandledUsageHits,
    manualRewriteNumerator,
    manualRewriteDenominator,
    manualRewriteRatio: manualRewriteDenominator === 0 ? 0 : manualRewriteNumerator / manualRewriteDenominator,
    manualInterventionNumerator,
    manualInterventionDenominator,
    manualInterventionRatio:
      manualInterventionDenominator === 0 ? 0 : manualInterventionNumerator / manualInterventionDenominator,
  };
}

function formatFixtureMetricsTable(fixtures: readonly FixtureMetricSnapshot[]): string {
  const rows = [
    "| fixture | readiness | auto/manual/total | rewrite ratio | intervention ratio | flags |",
    "| --- | --- | --- | --- | --- | --- |",
  ];
  for (const fixture of fixtures) {
    rows.push(
      `| ${fixture.fixture} | ${fixture.readiness} | ${fixture.autoMigratedCallSites}/${fixture.manualCallSites}/${fixture.totalCallSites} | ${fixture.manualRewrite.numerator}/${fixture.manualRewrite.denominator} (${fixture.manualRewrite.ratio.toFixed(3)}) | ${fixture.manualIntervention.numerator}/${fixture.manualIntervention.denominator} (${fixture.manualIntervention.ratio.toFixed(3)}) | ${fixture.flags.join(",") || "none"} |`,
    );
  }
  return rows.join("\n");
}

function evaluateFixtureMetricsGates(
  summary: FixtureMetricsSummary,
  fixtures: readonly FixtureMetricSnapshot[],
  options: FixtureMetricsGateOptions,
): FixtureMetricsGateEvaluation {
  const failures: string[] = [];
  if (options.failOnManual && summary.manualCallSites > 0) {
    failures.push(`Manual call sites detected (${summary.manualCallSites}).`);
  }
  if (options.failOnUnhandled && summary.unhandledUsageHits > 0) {
    failures.push(`Unhandled ArcGIS module usage detected (${summary.unhandledUsageHits}).`);
  }
  if (options.failOnBlocked && summary.blocked > 0) {
    const blockedFixtures = fixtures
      .filter((fixture) => fixture.readiness === "blocked")
      .map((fixture) => fixture.fixture);
    failures.push(
      `Blocked fixture readiness detected (${summary.blocked}): ${blockedFixtures.join(", ") || "unknown"}.`,
    );
  }
  if (options.maxManualRatio !== undefined && summary.manualRewriteRatio > options.maxManualRatio) {
    failures.push(
      `Manual rewrite ratio ${summary.manualRewriteRatio.toFixed(3)} exceeds max ${options.maxManualRatio.toFixed(3)}.`,
    );
  }
  if (
    options.maxManualInterventionRatio !== undefined &&
    summary.manualInterventionRatio > options.maxManualInterventionRatio
  ) {
    failures.push(
      `Manual intervention ratio ${summary.manualInterventionRatio.toFixed(3)} exceeds max ${options.maxManualInterventionRatio.toFixed(3)}.`,
    );
  }

  return {
    ...options,
    passed: failures.length === 0,
    failures,
  };
}

function runCodemod(args: ParsedArgs): void {
  const scanReport = scanArcGisUsage(args.target);
  const codemodResult = runEsriCompatCodemod({
    rootDir: args.target,
    write: args.write,
    compatImportPath: args.compatImportPath,
    annotateTodos: args.annotateTodos,
    target: args.codemodTarget,
  });
  const report = buildJsMigrationReport(args.target, codemodResult, scanReport);

  process.stdout.write(
    [
      `filesScanned=${codemodResult.filesScanned}`,
      `filesChanged=${codemodResult.filesChanged}`,
      `autoMigrated=${codemodResult.metrics.autoMigratedCallSites}`,
      `manual=${formatManualDifficultyBreakdown(report.manualTodos)}`,
      `manualRewrite=${report.manualRewriteMetric.numerator}/${report.manualRewriteMetric.denominator}`,
      `manualIntervention=${report.manualInterventionMetric.numerator}/${report.manualInterventionMetric.denominator}`,
      `writeMode=${args.write ? "enabled" : "dry-run"}`,
      `annotateTodos=${args.annotateTodos ? "enabled" : "disabled"}`,
      `target=${args.codemodTarget}`,
      `readiness=${report.readiness}`,
      `byKind=${formatByKindMetrics(codemodResult.metrics.byKind)}`,
    ].join(" "),
  );
  process.stdout.write("\n");

  process.stdout.write(`gates=${formatGateResults(report.gates)}\n`);

  if (
    (scanReport.imports.length === 0 || scanReport.filesWithArcGisImports === 0) &&
    (scanReport.esriLeafletImportCount ?? 0) > 0
  ) {
    process.stdout.write(
      "note=esri-leaflet-imports-detected-without-arcgis-js; codemod targets @arcgis/core inputs (not migrations from esri-leaflet)\n",
    );
  }

  if (report.manualTodos.length > 0) {
    process.stdout.write("manualTodos:\n");
    for (const todo of report.manualTodos) {
      process.stdout.write(`- ${todo.file}:${todo.line}:${todo.column} [${todo.kind}] ${todo.reason}\n`);
    }
  }

  if (report.manualTodoReasons.length > 0) {
    process.stdout.write("manualReasons:\n");
    for (const reason of report.manualTodoReasons.slice(0, 5)) {
      process.stdout.write(`- ${reason.count}x [${reason.kinds.join(",")}] ${reason.reason}\n`);
    }
  }

  if (report.unhandledArcGisModules.length > 0) {
    process.stdout.write("unhandledArcGisModules:\n");
    for (const moduleItem of report.unhandledArcGisModules.slice(0, 10)) {
      process.stdout.write(`- ${moduleItem.modulePath} [${moduleItem.usageStyle}] (${moduleItem.count})\n`);
    }
  }

  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);

  if (args.reportPath) {
    fs.writeFileSync(args.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${args.reportPath}\n`);
  }

  const gateEvaluation = evaluateMigrationGates(report, {
    failOnManual: args.failOnManual,
    failOnUnhandled: args.failOnUnhandled,
    failOnBlocked: args.failOnBlocked,
    maxManualRatio: args.maxManualRatio,
    maxManualInterventionRatio: args.maxManualInterventionRatio,
  });
  if (gateEvaluation.failed) {
    process.stdout.write("gatingFailures:\n");
    for (const failure of gateEvaluation.failures) {
      process.stdout.write(`- ${failure}\n`);
    }
    process.exitCode = 2;
  }
}

async function runReconcile(args: ParsedArgs): Promise<void> {
  if (
    !args.sourceBaseUrl ||
    !args.sourceServiceId ||
    !args.targetBaseUrl ||
    !args.targetServiceId ||
    args.layerId === undefined
  ) {
    printUsage();
    process.exitCode = 1;
    return;
  }

  const report = await runLayerReconciliation({
    sourceBaseUrl: args.sourceBaseUrl,
    sourceServiceId: args.sourceServiceId,
    targetBaseUrl: args.targetBaseUrl,
    targetServiceId: args.targetServiceId,
    layerId: args.layerId,
    sampleSize: args.sampleSize,
  });

  process.stdout.write(`${summarizeLayerReconciliation(report)}\n`);
  process.stdout.write(
    `checks=${report.checks.map((check) => `${check.check}:${check.passed ? "pass" : "fail"}`).join(",")}\n`,
  );
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);

  if (args.reportPath) {
    fs.writeFileSync(args.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${args.reportPath}\n`);
  }

  if (!report.passed) {
    process.exitCode = 2;
  }
}

async function runDemo(args: ParsedArgs): Promise<void> {
  const fixtureName = args.fixtureName ?? DEFAULT_DEMO_FIXTURE_NAME;
  const fixturesRoot = args.fixturesRoot ?? path.join(process.cwd(), "test", "fixtures");
  const outputDir = args.outputDir ?? path.join(process.cwd(), ".tmp", "migration-demo", fixtureName);
  const sourceUrlDetails =
    typeof args.sourceServiceUrl === "string" ? parseGeoservicesServiceUrl(args.sourceServiceUrl) : undefined;
  const resolvedLayerId = args.layerId ?? sourceUrlDetails?.layerId;
  const adminApiKey = args.adminApiKey ?? process.env.HONUA_ADMIN_API_KEY;

  if (!args.skipImport) {
    if (!args.adminBaseUrl || !args.sourceServiceUrl || resolvedLayerId === undefined || !args.tableName) {
      throw new Error(
        "demo requires --admin-base-url, --source-service-url, --layer-id (or a layer in source URL), and --table-name unless --skip-import is set.",
      );
    }
  }

  let sourceBaseUrl = args.sourceBaseUrl;
  if (!sourceBaseUrl) {
    sourceBaseUrl = sourceUrlDetails?.baseUrl;
  }

  let sourceServiceId = args.sourceServiceId;
  if (!sourceServiceId) {
    sourceServiceId = sourceUrlDetails?.serviceId;
  }

  let targetBaseUrl = args.targetBaseUrl;
  if (!targetBaseUrl) {
    targetBaseUrl = args.adminBaseUrl;
  }

  let targetServiceId = args.targetServiceId;
  if (!targetServiceId) {
    targetServiceId = args.tableName;
  }

  if (!args.skipReconcile) {
    if (!sourceBaseUrl || !sourceServiceId || !targetBaseUrl || !targetServiceId || resolvedLayerId === undefined) {
      throw new Error(
        "demo reconciliation requires source/target base URLs, service IDs, and --layer-id (or source URL with layer). Use --skip-reconcile to disable.",
      );
    }
  }

  const report = await runMigrationDemo({
    fixtureName,
    fixturesRoot,
    outputDir,
    codemodTarget: args.codemodTarget,
    compatImportPath: args.compatImportPath,
    annotateTodos: args.annotateTodos,
    skipImport: args.skipImport,
    skipReconciliation: args.skipReconcile,
    importOptions:
      args.skipImport ||
      !args.adminBaseUrl ||
      !args.sourceServiceUrl ||
      resolvedLayerId === undefined ||
      !args.tableName
        ? undefined
        : {
            adminBaseUrl: args.adminBaseUrl,
            adminApiKey,
            sourceServiceUrl: args.sourceServiceUrl,
            layerId: resolvedLayerId,
            tableName: args.tableName,
            pollIntervalMs: args.pollIntervalMs,
            timeoutMs:
              typeof args.timeoutSeconds === "number"
                ? Math.max(1, Math.trunc(args.timeoutSeconds * 1_000))
                : undefined,
            autoPublish: true,
          },
    reconciliationOptions:
      args.skipReconcile ||
      !sourceBaseUrl ||
      !sourceServiceId ||
      !targetBaseUrl ||
      !targetServiceId ||
      resolvedLayerId === undefined
        ? undefined
        : {
            sourceBaseUrl,
            sourceServiceId,
            targetBaseUrl,
            targetServiceId,
            layerId: resolvedLayerId,
            sampleSize: args.sampleSize,
          },
  });

  if (report.import) {
    process.stdout.write(
      [
        "demoStage=import",
        `jobId=${report.import.jobId}`,
        `status=${report.import.status}`,
        `polls=${report.import.pollCount}`,
      ].join(" "),
    );
    process.stdout.write("\n");
  } else {
    process.stdout.write("demoStage=import skipped=yes\n");
  }

  process.stdout.write(
    [
      "demoStage=codemod",
      `fixture=${report.fixtureName}`,
      `readiness=${report.migration.readiness}`,
      `autoMigrated=${report.migration.codemodResult.metrics.autoMigratedCallSites}`,
      `manual=${report.migration.codemodResult.metrics.manualCallSites}`,
      `manualRewrite=${report.migration.manualRewriteMetric.numerator}/${report.migration.manualRewriteMetric.denominator}`,
      `manualIntervention=${report.migration.manualInterventionMetric.numerator}/${report.migration.manualInterventionMetric.denominator}`,
    ].join(" "),
  );
  process.stdout.write("\n");

  if (report.reconciliation) {
    process.stdout.write(`demoStage=reconcile ${summarizeLayerReconciliation(report.reconciliation)}\n`);
  } else {
    process.stdout.write("demoStage=reconcile skipped=yes\n");
  }

  const stdoutSummary = {
    fixture: report.fixtureName,
    codemodTarget: report.codemodTarget,
    elapsedMs: report.elapsedMs,
    workingAppDir: report.workingAppDir,
    import: report.import
      ? {
          jobId: report.import.jobId,
          status: report.import.status,
          pollCount: report.import.pollCount,
        }
      : undefined,
    migration: {
      readiness: report.migration.readiness,
      autoMigratedCallSites: report.migration.codemodResult.metrics.autoMigratedCallSites,
      manualCallSites: report.migration.codemodResult.metrics.manualCallSites,
      manualRewrite: {
        numerator: report.migration.manualRewriteMetric.numerator,
        denominator: report.migration.manualRewriteMetric.denominator,
        ratio: report.migration.manualRewriteMetric.ratio,
      },
      manualIntervention: {
        numerator: report.migration.manualInterventionMetric.numerator,
        denominator: report.migration.manualInterventionMetric.denominator,
        ratio: report.migration.manualInterventionMetric.ratio,
      },
    },
    reconciliation: report.reconciliation
      ? {
          passed: report.reconciliation.passed,
          sourceFeatureCount: report.reconciliation.sourceFeatureCount,
          targetFeatureCount: report.reconciliation.targetFeatureCount,
          missingInTargetAttributeKeys: report.reconciliation.missingInTargetAttributeKeys.length,
          extraInTargetAttributeKeys: report.reconciliation.extraInTargetAttributeKeys.length,
        }
      : undefined,
    passed: report.passed,
  };

  process.stdout.write(
    `demoPassed=${report.passed ? "yes" : "no"} elapsedMs=${report.elapsedMs} outputDir=${report.workingAppDir}\n`,
  );
  process.stdout.write(`${JSON.stringify(stdoutSummary, null, 2)}\n`);

  if (args.reportPath) {
    fs.mkdirSync(path.dirname(args.reportPath), { recursive: true });
    fs.writeFileSync(args.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`reportWritten=${args.reportPath}\n`);
  }

  if (!report.passed) {
    process.exitCode = 2;
  }
}

function parseArgs(argv: string[]): ParsedArgs | undefined {
  if (argv.length === 0) {
    return {
      command: "scan",
      target: process.cwd(),
      write: false,
      annotateTodos: false,
      failOnManual: false,
      failOnUnhandled: false,
      failOnBlocked: false,
      codemodTarget: "honua-compat",
      skipImport: false,
      skipReconcile: false,
      contentIncludeBasemap: true,
      contentIncludeFeatures: true,
      contentIncludeWebMaps: true,
      contentIncludeHostedLayers: true,
      widgetOutput: "table",
    };
  }

  const maybeCommand = argv[0];
  const command:
    | "scan"
    | "widgets"
    | "codemod"
    | "reconcile"
    | "matrix"
    | "runtime-matrix"
    | "fixtures"
    | "demo"
    | "content-webmap"
    | "content"
    | "corpus-evidence" =
    maybeCommand === "scan" ||
    maybeCommand === "widgets" ||
    maybeCommand === "codemod" ||
    maybeCommand === "reconcile" ||
    maybeCommand === "matrix" ||
    maybeCommand === "runtime-matrix" ||
    maybeCommand === "fixtures" ||
    maybeCommand === "demo" ||
    maybeCommand === "content-webmap" ||
    maybeCommand === "content" ||
    maybeCommand === "corpus-evidence"
      ? maybeCommand
      : "scan";
  const positional = command === maybeCommand ? argv.slice(1) : argv.slice(0);

  let target: string | undefined;
  let fixtureNames: string[] | undefined;
  let reportPath: string | undefined;
  let codemodTarget: CodemodTarget = "honua-compat";
  let codemodTargetExplicit = false;
  let write = false;
  let annotateTodos = false;
  let failOnManual = false;
  let failOnUnhandled = false;
  let failOnBlocked = false;
  let maxManualRatio: number | undefined;
  let maxManualInterventionRatio: number | undefined;
  let compatImportPath: string | undefined;
  let sourceBaseUrl: string | undefined;
  let sourceServiceId: string | undefined;
  let targetBaseUrl: string | undefined;
  let targetServiceId: string | undefined;
  let layerId: number | undefined;
  let sampleSize: number | undefined;
  let fixtureName: string | undefined;
  let fixturesRoot: string | undefined;
  let outputDir: string | undefined;
  let adminBaseUrl: string | undefined;
  let adminApiKey: string | undefined;
  let sourceServiceUrl: string | undefined;
  let tableName: string | undefined;
  let pollIntervalMs: number | undefined;
  let timeoutSeconds: number | undefined;
  let skipImport = false;
  let skipReconcile = false;
  let contentInputPath: string | undefined;
  let contentOutputPath: string | undefined;
  let contentSourceUrlPrefix: string | undefined;
  let contentTargetUrlPrefix: string | undefined;
  let contentIncludeBasemap = true;
  let contentAction: "scan" | "export" | "import" | "reconcile" | undefined;
  let contentPortalUrl: string | undefined;
  let contentToken: string | undefined;
  let contentSourceDir: string | undefined;
  let contentOutputDir: string | undefined;
  let contentImportReportPath: string | undefined;
  let contentTablePrefix: string | undefined;
  let contentIncludeFeatures = true;
  let contentIncludeWebMaps = true;
  let contentIncludeHostedLayers = true;
  let corpusPath: string | undefined;
  let corpusOutputDir: string | undefined;
  let widgetOutput: "table" | "json" | "markdown" = "table";
  let gatePct: number | undefined;

  for (let i = 0; i < positional.length; i += 1) {
    const token = positional[i];
    if (token === "--help" || token === "-h") {
      return undefined;
    }
    if (token === "--write") {
      write = true;
      continue;
    }
    if (token === "--json" && command === "widgets") {
      widgetOutput = "json";
      continue;
    }
    if (token === "--markdown" && command === "widgets") {
      widgetOutput = "markdown";
      continue;
    }
    if (token === "--gate" && command === "widgets") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      const parsedGate = Number.parseFloat(next);
      if (!Number.isFinite(parsedGate) || parsedGate < 0 || parsedGate > 100) {
        return undefined;
      }
      gatePct = parsedGate;
      i += 1;
      continue;
    }
    if (token === "--annotate-todos") {
      annotateTodos = true;
      continue;
    }
    if (token === "--fail-on-manual") {
      failOnManual = true;
      continue;
    }
    if (token === "--fail-on-unhandled") {
      failOnUnhandled = true;
      continue;
    }
    if (token === "--fail-on-blocked") {
      failOnBlocked = true;
      continue;
    }
    if (token === "--max-manual-ratio") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }

      const parsedRatio = Number.parseFloat(next);
      if (!Number.isFinite(parsedRatio) || parsedRatio < 0 || parsedRatio > 1) {
        return undefined;
      }

      maxManualRatio = parsedRatio;
      i += 1;
      continue;
    }
    if (token === "--max-manual-intervention-ratio") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }

      const parsedRatio = Number.parseFloat(next);
      if (!Number.isFinite(parsedRatio) || parsedRatio < 0 || parsedRatio > 1) {
        return undefined;
      }

      maxManualInterventionRatio = parsedRatio;
      i += 1;
      continue;
    }
    if (token === "--report") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      reportPath = next;
      i += 1;
      continue;
    }
    if (token === "--compat-import-path") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      compatImportPath = next;
      i += 1;
      continue;
    }
    if (token === "--target") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      if (command === "content") {
        targetBaseUrl = next;
        i += 1;
        continue;
      }
      if (next !== "honua" && next !== "honua-compat" && next !== "esri-leaflet" && next !== "honua-maplibre") {
        return undefined;
      }
      codemodTarget = next === "honua" ? "honua-compat" : next;
      codemodTargetExplicit = true;
      i += 1;
      continue;
    }
    if (token === "--fixtures") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      const parsedFixtures = next
        .split(",")
        .map((fixture) => fixture.trim())
        .filter((fixture) => fixture.length > 0);
      if (parsedFixtures.length === 0) {
        return undefined;
      }
      fixtureNames = parsedFixtures;
      i += 1;
      continue;
    }
    if (token === "--fixture") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      fixtureName = next;
      i += 1;
      continue;
    }
    if (token === "--fixtures-root") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      fixturesRoot = next;
      i += 1;
      continue;
    }
    if (token === "--output-dir") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      if (command === "content") {
        contentOutputDir = next;
      } else {
        outputDir = next;
      }
      i += 1;
      continue;
    }
    if (token === "--admin-base-url") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      adminBaseUrl = next;
      i += 1;
      continue;
    }
    if (token === "--admin-api-key") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      adminApiKey = next;
      i += 1;
      continue;
    }
    if (token === "--source-service-url") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      sourceServiceUrl = next;
      i += 1;
      continue;
    }
    if (token === "--table-name") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      tableName = next;
      i += 1;
      continue;
    }
    if (token === "--poll-interval-ms") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      const parsedPoll = Number.parseInt(next, 10);
      if (!Number.isFinite(parsedPoll) || parsedPoll <= 0) {
        return undefined;
      }
      pollIntervalMs = parsedPoll;
      i += 1;
      continue;
    }
    if (token === "--timeout-seconds") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      const parsedTimeout = Number.parseInt(next, 10);
      if (!Number.isFinite(parsedTimeout) || parsedTimeout <= 0) {
        return undefined;
      }
      timeoutSeconds = parsedTimeout;
      i += 1;
      continue;
    }
    if (token === "--skip-import") {
      skipImport = true;
      continue;
    }
    if (token === "--skip-reconcile") {
      skipReconcile = true;
      continue;
    }
    if (token === "--input") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      contentInputPath = next;
      i += 1;
      continue;
    }
    if (token === "--corpus") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      corpusPath = next;
      i += 1;
      continue;
    }
    if (token === "--out") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      corpusOutputDir = next;
      i += 1;
      continue;
    }
    if (token === "--output") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      if (command === "content-webmap") {
        contentOutputPath = next;
      } else if (command === "content") {
        contentOutputDir = next;
      } else {
        return undefined;
      }
      i += 1;
      continue;
    }
    if (token === "--portal") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      contentPortalUrl = next;
      i += 1;
      continue;
    }
    if (token === "--token") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      contentToken = next;
      i += 1;
      continue;
    }
    if (token === "--source" || token === "--source-dir") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      contentSourceDir = next;
      i += 1;
      continue;
    }
    if (token === "--import-report") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      contentImportReportPath = next;
      i += 1;
      continue;
    }
    if (token === "--table-prefix") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      contentTablePrefix = next;
      i += 1;
      continue;
    }
    if (token === "--source-url-prefix") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      contentSourceUrlPrefix = next;
      i += 1;
      continue;
    }
    if (token === "--target-url-prefix") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      contentTargetUrlPrefix = next;
      i += 1;
      continue;
    }
    if (token === "--exclude-basemap") {
      contentIncludeBasemap = false;
      continue;
    }
    if (token === "--exclude-features") {
      contentIncludeFeatures = false;
      continue;
    }
    if (token === "--exclude-webmaps") {
      contentIncludeWebMaps = false;
      continue;
    }
    if (token === "--exclude-hosted-layers") {
      contentIncludeHostedLayers = false;
      continue;
    }
    if (token === "--source-base-url") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      sourceBaseUrl = next;
      i += 1;
      continue;
    }
    if (token === "--source-service-id") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      sourceServiceId = next;
      i += 1;
      continue;
    }
    if (token === "--target-base-url") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      targetBaseUrl = next;
      i += 1;
      continue;
    }
    if (token === "--target-service-id") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      targetServiceId = next;
      i += 1;
      continue;
    }
    if (token === "--layer-id") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      const parsedLayerId = Number.parseInt(next, 10);
      if (!Number.isFinite(parsedLayerId)) {
        return undefined;
      }
      layerId = parsedLayerId;
      i += 1;
      continue;
    }
    if (token === "--sample-size") {
      const next = positional[i + 1];
      if (!next) {
        return undefined;
      }
      const parsedSampleSize = Number.parseInt(next, 10);
      if (!Number.isFinite(parsedSampleSize) || parsedSampleSize <= 0) {
        return undefined;
      }
      sampleSize = parsedSampleSize;
      i += 1;
      continue;
    }
    if (token.startsWith("--")) {
      return undefined;
    }
    if (command === "content") {
      if (!contentAction) {
        if (token === "scan" || token === "export" || token === "import" || token === "reconcile") {
          contentAction = token;
          continue;
        }
        return undefined;
      }
      if (!target) {
        target = token;
        continue;
      }
      return undefined;
    }
    if (command === "reconcile") {
      return undefined;
    }
    if (command === "content-webmap") {
      if (!contentInputPath) {
        contentInputPath = token;
        continue;
      }
      return undefined;
    }
    if (command === "demo") {
      if (!fixtureName) {
        fixtureName = token;
        continue;
      }
      return undefined;
    }
    if (command === "corpus-evidence") {
      if (!corpusPath) {
        corpusPath = token;
        continue;
      }
      return undefined;
    }
    if (!target) {
      target = token;
      continue;
    }
    return undefined;
  }

  if (command === "content-webmap" && !contentInputPath && !target) {
    return undefined;
  }

  if (command === "content") {
    if (!contentAction) {
      return undefined;
    }

    if (contentAction === "scan" || contentAction === "export") {
      contentPortalUrl = contentPortalUrl ?? target;
      if (!contentPortalUrl) {
        return undefined;
      }
      if (contentAction === "export") {
        contentOutputDir = contentOutputDir ?? path.join(process.cwd(), "content-export");
      }
    } else {
      contentSourceDir = contentSourceDir ?? target ?? process.cwd();
      if (contentAction === "import") {
        if (!targetBaseUrl && !adminBaseUrl) {
          return undefined;
        }
      }
    }
  }

  const resolvedCodemodTarget: CodemodTarget =
    command === "corpus-evidence" && !codemodTargetExplicit ? "honua-maplibre" : codemodTarget;

  return {
    command,
    target:
      target ??
      (command === "fixtures" || command === "demo" ? path.join(process.cwd(), "test", "fixtures") : process.cwd()),
    contentAction,
    write,
    codemodTarget: resolvedCodemodTarget,
    annotateTodos,
    failOnManual,
    failOnUnhandled,
    failOnBlocked,
    maxManualRatio,
    maxManualInterventionRatio,
    reportPath,
    compatImportPath,
    sourceBaseUrl,
    sourceServiceId,
    targetBaseUrl,
    targetServiceId,
    layerId,
    sampleSize,
    fixtureNames,
    fixtureName,
    fixturesRoot,
    outputDir,
    adminBaseUrl,
    adminApiKey,
    sourceServiceUrl,
    tableName,
    pollIntervalMs,
    timeoutSeconds,
    skipImport,
    skipReconcile,
    contentInputPath,
    contentOutputPath,
    contentSourceUrlPrefix,
    contentTargetUrlPrefix,
    contentIncludeBasemap,
    contentPortalUrl,
    contentToken,
    contentSourceDir,
    contentOutputDir,
    contentImportReportPath,
    contentTablePrefix,
    contentIncludeFeatures,
    contentIncludeWebMaps,
    contentIncludeHostedLayers,
    corpusPath,
    corpusOutputDir,
    widgetOutput,
    gatePct,
  };
}

function formatByKindMetrics(byKind: CodemodMetricsByKind): string {
  return (Object.keys(byKind) as Array<keyof CodemodMetricsByKind>)
    .map((kind) => {
      const metric = byKind[kind];
      return `${kind}:${metric.autoMigrated}/${metric.manual}/${metric.total}`;
    })
    .join(",");
}

function formatManualDifficultyBreakdown(todos: readonly { difficulty?: string }[]): string {
  let trivial = 0;
  let moderate = 0;
  let complex = 0;
  for (const todo of todos) {
    if (todo.difficulty === "trivial") {
      trivial += 1;
    } else if (todo.difficulty === "complex") {
      complex += 1;
    } else {
      moderate += 1;
    }
  }
  return `[trivial:${trivial} moderate:${moderate} complex:${complex}]`;
}

function formatGateResults(gates: readonly { gate: string; passed: boolean }[]): string {
  return gates.map((gate) => `${gate.gate}:${gate.passed ? "pass" : "fail"}`).join(",");
}

function printUsage(): void {
  process.stdout.write(
    [
      "Usage:",
      "  honua-migrate [scan] <path> [--report <file>]",
      "  honua-migrate widgets <path> [--json | --markdown] [--gate <pct>] [--report <file>]",
      "  honua-migrate codemod <path> [--target <honua|honua-compat|honua-maplibre|esri-leaflet>] [--write] [--annotate-todos] [--report <file>] [--compat-import-path <pkg>] [--fail-on-manual] [--fail-on-unhandled] [--fail-on-blocked] [--max-manual-ratio <0..1>] [--max-manual-intervention-ratio <0..1>]",
      "  honua-migrate matrix [--report <file>]",
      "  honua-migrate runtime-matrix [--report <file>]",
      "  honua-migrate fixtures [<fixtures-root>] [--target <honua|honua-compat|honua-maplibre|esri-leaflet>] [--fixtures <name1,name2,...>] [--report <file>] [--fail-on-manual] [--fail-on-unhandled] [--fail-on-blocked] [--max-manual-ratio <0..1>] [--max-manual-intervention-ratio <0..1>]",
      "  honua-migrate reconcile --source-base-url <url> --source-service-id <id> --target-base-url <url> --target-service-id <id> --layer-id <n> [--sample-size <n>] [--report <file>]",
      "  honua-migrate demo [<fixture-name>] [--fixtures-root <dir>] [--output-dir <dir>] [--target <honua|honua-compat|honua-maplibre|esri-leaflet>] [--admin-base-url <url>] [--admin-api-key <key>] [--source-service-url <url>] [--layer-id <n>] [--table-name <name>] [--source-base-url <url>] [--source-service-id <id>] [--target-base-url <url>] [--target-service-id <id>] [--sample-size <n>] [--poll-interval-ms <n>] [--timeout-seconds <n>] [--skip-import] [--skip-reconcile] [--report <file>]",
      "  honua-migrate content scan --portal <url> [--token <token>] [--report <file>]",
      "  honua-migrate content export --portal <url> --output-dir <dir> [--token <token>] [--exclude-features] [--exclude-webmaps] [--exclude-hosted-layers] [--report <file>]",
      "  honua-migrate content import --source <dir> --target <url> [--admin-api-key <key>] [--output-dir <dir>] [--table-prefix <prefix>] [--source-url-prefix <url>] [--target-url-prefix <url>] [--exclude-webmaps] [--exclude-hosted-layers] [--report <file>]",
      "  honua-migrate content reconcile --source <dir> [--import-report <file>] [--output-dir <file>] [--report <file>]",
      "  honua-migrate content-webmap --input <webmap.json> [--output <file>] [--source-url-prefix <url>] [--target-url-prefix <url>] [--exclude-basemap] [--report <file>]",
      "  honua-migrate corpus-evidence [--corpus <dir>] --out <dir> [--target <honua|honua-compat|honua-maplibre|esri-leaflet>]",
      "",
      "Examples:",
      "  node dist/src/migration/cli.js scan ./src",
      "  node dist/src/migration/cli.js widgets ./src --report widget-readiness.json",
      "  node dist/src/migration/cli.js widgets ./src --markdown",
      "  node dist/src/migration/cli.js widgets ./src --gate 80",
      "  node dist/src/migration/cli.js codemod ./src --write --annotate-todos --report migration-report.json",
      "  node dist/src/migration/cli.js codemod ./src --target honua-maplibre --write --report migration-report.json",
      "  node dist/src/migration/cli.js codemod ./src --target esri-leaflet --write --report migration-report.json",
      "  node dist/src/migration/cli.js matrix --report parity-matrix.json",
      "  node dist/src/migration/cli.js runtime-matrix --report runtime-parity-matrix.json",
      "  node dist/src/migration/cli.js fixtures --report real-sample-metrics.json",
      "  node dist/src/migration/cli.js fixtures --fail-on-manual --fail-on-unhandled --fail-on-blocked --max-manual-ratio 0 --max-manual-intervention-ratio 0",
      "  node dist/src/migration/cli.js codemod ./src --fail-on-manual --fail-on-unhandled --max-manual-ratio 0.2 --max-manual-intervention-ratio 0.3",
      "  node dist/src/migration/cli.js reconcile --source-base-url https://source.example --source-service-id parcels --target-base-url https://target.example --target-service-id parcels --layer-id 0 --sample-size 200 --report reconcile-report.json",
      "  node dist/src/migration/cli.js demo --admin-base-url http://localhost:5000 --source-service-url https://arcgis.example/rest/services/incidents/FeatureServer/0 --layer-id 0 --table-name incidents --source-base-url https://arcgis.example --source-service-id incidents --target-base-url http://localhost:5000 --target-service-id incidents --report demo-report.json",
      "  node dist/src/migration/cli.js content scan --portal https://org.maps.arcgis.com --report ./content/scan.json",
      "  node dist/src/migration/cli.js content export --portal https://org.maps.arcgis.com --output-dir ./export --report ./content/export.json",
      "  node dist/src/migration/cli.js content import --source ./export --target https://honua.example.com --admin-api-key $HONUA_ADMIN_API_KEY --report ./content/import.json",
      "  node dist/src/migration/cli.js content reconcile --source ./export --report ./content/reconcile.json",
      "  node dist/src/migration/cli.js content-webmap --input ./export/map.json --output ./export/map.honua.json --source-url-prefix https://org.maps.arcgis.com --target-url-prefix https://honua.example.com --report ./export/map.report.json",
      "  node dist/src/migration/cli.js corpus-evidence --corpus test/fixtures/esri-sample-corpus --out ./corpus-evidence",
      "",
      "Target semantics:",
      "  honua: alias of honua-compat.",
      "  honua-compat: migrate ArcGIS JS (@arcgis/core) to @honua/sdk-esri-compat.",
      "  honua-maplibre: migrate supported ArcGIS JS (@arcgis/core) constructs to @honua/sdk-js/map plus maplibre-gl helpers.",
      "  esri-leaflet: migrate ArcGIS JS (@arcgis/core) to a mixed esri-leaflet + compat output.",
      "  Existing esri-leaflet apps generally do not need this codemod.",
    ].join("\n"),
  );
  process.stdout.write("\n");
}
