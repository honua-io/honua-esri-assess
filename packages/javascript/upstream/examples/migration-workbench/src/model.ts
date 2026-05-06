import {
  WORKBENCH_BASE_ARTIFACTS,
  WORKBENCH_CODEMOD_METRICS,
  WORKBENCH_CONTENT_ITEMS,
  WORKBENCH_FIXED_GENERATED_AT,
  WORKBENCH_FIXTURE_ACTIONS,
  WORKBENCH_FIXTURE_NAME,
  WORKBENCH_IMPORT_ITEMS,
  WORKBENCH_RECONCILIATION,
  WORKBENCH_SCAN_METRICS,
  WORKBENCH_SOURCE,
} from "./fixtures.js";
import type {
  HonuaCloudImportConfig,
  LiveImportProgress,
  MigrationWorkbenchArtifacts,
  MigrationWorkbenchConfig,
  MigrationWorkbenchReport,
  MigrationWorkbenchWorkflow,
  WorkbenchActionItem,
  WorkbenchArtifact,
  WorkbenchContentItem,
  WorkbenchImportItem,
  WorkbenchMetric,
  WorkbenchMode,
  WorkbenchReconciliationSummary,
  WorkbenchSourceSummary,
  WorkbenchStage,
  WorkbenchStageId,
  WorkbenchStageStatus,
} from "./types.js";

const REPORT_SCHEMA_VERSION = "honua-migration-workbench-report.v1";
const TERMINAL_IMPORT_STATUSES = new Set(["Completed", "Failed", "Cancelled"]);
const IMPORT_STATUS_BY_ENUM_VALUE = new Map<number, string>([
  [0, "Queued"],
  [1, "Discovering"],
  [2, "RetrievingFeatures"],
  [3, "CreatingTable"],
  [4, "InsertingFeatures"],
  [5, "Publishing"],
  [6, "Completed"],
  [7, "Failed"],
  [8, "Cancelled"],
]);

export function createFixtureMigrationWorkbenchWorkflow(
  config: Partial<MigrationWorkbenchConfig> = {},
): MigrationWorkbenchWorkflow {
  const generatedAt = config.generatedAt ?? WORKBENCH_FIXED_GENERATED_AT;
  const mode = config.mode ?? "demo";
  const fixtureName = config.fixtureName ?? WORKBENCH_FIXTURE_NAME;
  const cloudImport = config.cloudImport ?? { enabled: mode === "live" };
  const source = { ...WORKBENCH_SOURCE, fixtureName };
  const importItems = createFixtureImportItems(mode, cloudImport);
  const actionItems = withLiveConfigActions(mode, cloudImport, [...WORKBENCH_FIXTURE_ACTIONS]);
  const artifacts = buildReportArtifacts(WORKBENCH_BASE_ARTIFACTS);
  const readiness = actionItems.some((item) => item.severity === "blocked") ? "assisted" : "ready";
  const stages = buildStages({
    mode,
    readiness,
    source,
    scanMetrics: WORKBENCH_SCAN_METRICS,
    codemodMetrics: WORKBENCH_CODEMOD_METRICS,
    contentItems: WORKBENCH_CONTENT_ITEMS,
    importItems,
    reconciliation: WORKBENCH_RECONCILIATION,
    actionItems,
    artifacts,
  });

  return {
    generatedAt,
    reportId: buildReportId(fixtureName, mode, generatedAt),
    mode,
    fixtureName,
    source,
    cloudImport,
    readiness,
    stages,
    actionItems,
    contentItems: WORKBENCH_CONTENT_ITEMS,
    importItems,
    reconciliation: WORKBENCH_RECONCILIATION,
    artifacts,
  };
}

export function createMigrationWorkbenchWorkflowFromArtifacts(
  artifacts: MigrationWorkbenchArtifacts,
  config: Partial<MigrationWorkbenchConfig> = {},
): MigrationWorkbenchWorkflow {
  const generatedAt = config.generatedAt ?? WORKBENCH_FIXED_GENERATED_AT;
  const mode = config.mode ?? "demo";
  const cloudImport = config.cloudImport ?? { enabled: mode === "live" };
  const fixtureName = config.fixtureName ?? artifacts.source.fixtureName;
  const source = { ...artifacts.source, fixtureName };
  const contentItems = contentItemsFromReports(artifacts);
  const importItems = importItemsFromReport(artifacts, mode, cloudImport);
  const reconciliation = reconciliationFromReports(artifacts);
  const actionItems = withLiveConfigActions(mode, cloudImport, actionItemsFromReports(artifacts));
  const reportArtifacts = buildReportArtifacts(buildArtifactListFromReports(artifacts));
  const scanMetrics = [
    { label: "Files scanned", value: String(artifacts.scan.filesScanned) },
    { label: "ArcGIS imports", value: String(artifacts.scan.imports.length) },
    { label: "Risk flags", value: String(artifacts.scan.flags.length), tone: metricTone(artifacts.scan.flags.length) },
  ] satisfies readonly WorkbenchMetric[];
  const codemodMetrics = [
    {
      label: "Auto migrated",
      value: String(artifacts.migration.codemodResult.metrics.autoMigratedCallSites),
      tone: "good",
    },
    {
      label: "Manual call sites",
      value: String(artifacts.migration.codemodResult.metrics.manualCallSites),
      tone: metricTone(artifacts.migration.codemodResult.metrics.manualCallSites),
    },
    {
      label: "Unhandled modules",
      value: String(artifacts.migration.manualInterventionMetric.unhandledUsageHits),
      tone: metricTone(artifacts.migration.manualInterventionMetric.unhandledUsageHits),
    },
  ] satisfies readonly WorkbenchMetric[];
  const stages = buildStages({
    mode,
    readiness: artifacts.migration.readiness,
    source,
    scanMetrics,
    codemodMetrics,
    contentItems,
    importItems,
    reconciliation,
    actionItems,
    artifacts: reportArtifacts,
  });

  return {
    generatedAt,
    reportId: buildReportId(fixtureName, mode, generatedAt),
    mode,
    fixtureName,
    source,
    cloudImport,
    readiness: artifacts.migration.readiness,
    stages,
    actionItems,
    contentItems,
    importItems,
    reconciliation,
    artifacts: reportArtifacts,
  };
}

export function createWorkbenchReport(workflow: MigrationWorkbenchWorkflow): MigrationWorkbenchReport {
  const actionItems = [...workflow.actionItems].sort(compareActionItems);
  const stages = workflow.stages.map((stage) => ({
    ...stage,
    artifacts: [...stage.artifacts].sort(compareArtifacts),
  }));
  const contentItems = [...workflow.contentItems].sort((a, b) => a.id.localeCompare(b.id));
  const importItems = [...workflow.importItems].sort((a, b) => a.id.localeCompare(b.id));
  const artifacts = [...workflow.artifacts].sort(compareArtifacts);

  return {
    schemaVersion: REPORT_SCHEMA_VERSION,
    reportId: workflow.reportId,
    generatedAt: workflow.generatedAt,
    mode: workflow.mode,
    fixtureName: workflow.fixtureName,
    source: workflow.source,
    summary: {
      readiness: workflow.readiness,
      stageCount: stages.length,
      manualActionCount: actionItems.filter((item) => item.severity === "manual").length,
      blockedActionCount: actionItems.filter((item) => item.severity === "blocked").length,
      contentItems: contentItems.length,
      importItems: importItems.length,
      reconciliationStatus: workflow.reconciliation.status,
    },
    stages,
    actionItems,
    contentItems,
    importItems,
    reconciliation: workflow.reconciliation,
    artifacts,
    notes: [
      "Demo mode is deterministic and does not write to Honua Cloud.",
      "Live mode starts Honua Cloud import jobs only when the opt-in import config is complete.",
      "Feature data imports are tracked as materialized artifacts, not transparent feature-query caches.",
      "Scan metadata and compatibility profile results may be cached between migration runs.",
    ],
  };
}

export function serializeWorkbenchReport(report: MigrationWorkbenchReport): string {
  return `${JSON.stringify(report, null, 2)}\n`;
}

export function serializeWorkbenchMarkdownReport(report: MigrationWorkbenchReport): string {
  const lines = [
    `# ${report.source.title}`,
    "",
    `Report ID: ${report.reportId}`,
    `Generated: ${report.generatedAt}`,
    `Mode: ${report.mode}`,
    `Readiness: ${report.summary.readiness}`,
    "",
    "## Stages",
    "",
    ...report.stages.map((stage) => `- ${stage.title}: ${stage.status} - ${stage.summary}`),
    "",
    "## Action Items",
    "",
    ...report.actionItems.map((item) => `- ${item.severity.toUpperCase()}: ${item.title} - ${item.nextStep}`),
    "",
    "## Materialized Content",
    "",
    ...report.contentItems.map((item) => `- ${item.title}: ${item.status} (${item.artifactPath})`),
    "",
    "## Reconciliation",
    "",
    `Status: ${report.reconciliation.status}`,
    `Feature count delta: ${report.reconciliation.countDelta}`,
    `Missing target keys: ${report.reconciliation.missingTargetKeys.join(", ") || "none"}`,
    `Extra target keys: ${report.reconciliation.extraTargetKeys.join(", ") || "none"}`,
    "",
  ];
  return `${lines.join("\n")}\n`;
}

export function applyLiveImportProgress(
  workflow: MigrationWorkbenchWorkflow,
  progress: LiveImportProgress,
): MigrationWorkbenchWorkflow {
  let matched = false;
  const importItems = workflow.importItems.map((item) => {
    if (item.id !== progress.item.id) return item;
    matched = true;
    return progress.item;
  });
  const nextImportItems =
    matched || importItems.length === 0
      ? importItems
      : importItems.map((item, index) => (index === 0 && item.status !== "blocked" ? progress.item : item));
  const stages = buildStages({
    mode: workflow.mode,
    readiness: workflow.readiness,
    source: workflow.source,
    scanMetrics: stageMetrics(workflow, "scan"),
    codemodMetrics: stageMetrics(workflow, "codemod"),
    contentItems: workflow.contentItems,
    importItems: nextImportItems,
    reconciliation: workflow.reconciliation,
    actionItems: workflow.actionItems,
    artifacts: workflow.artifacts,
  });
  return { ...workflow, importItems: nextImportItems, stages };
}

export async function runHonuaCloudImportJob(
  config: HonuaCloudImportConfig,
  options: { readonly fetchFn?: typeof fetch } = {},
): Promise<LiveImportProgress> {
  const missing = missingCloudImportConfig(config);
  if (missing.length > 0) {
    throw new Error(`Live Honua Cloud import is missing required config: ${missing.join(", ")}`);
  }

  const fetchFn = options.fetchFn ?? globalThis.fetch.bind(globalThis);
  const adminBaseUrl = trimTrailingSlash(config.adminBaseUrl ?? "");
  const importBase = `${adminBaseUrl}/api/v1/admin/import/geoservices`;
  const startRecord = asRecord(
    await fetchJson(fetchFn, `${importBase}/start`, {
      method: "POST",
      headers: buildJsonHeaders(config.adminApiKey),
      body: JSON.stringify({
        serviceUrl: config.sourceServiceUrl,
        layerId: config.layerId,
        tableName: config.tableName,
        autoPublish: true,
      }),
    }),
    "Import start response",
  );
  const jobId = readRequiredString(startRecord, "jobId");
  const statusUrl = resolveStatusUrl(importBase, readOptionalString(startRecord, "statusUrl"), jobId);
  const pollIntervalMs = Math.max(100, config.pollIntervalMs ?? 2_000);
  const timeoutMs = Math.max(1_000, config.timeoutMs ?? 600_000);
  const deadline = Date.now() + timeoutMs;
  let pollCount = 0;
  let latest: Record<string, unknown> | undefined;

  for (;;) {
    pollCount += 1;
    latest = asRecord(
      await fetchJson(fetchFn, statusUrl, {
        method: "GET",
        headers: buildJsonHeaders(config.adminApiKey),
      }),
      "Import progress response",
    );

    const status = normalizeImportStatus(latest.status);
    if (TERMINAL_IMPORT_STATUSES.has(status)) break;
    if (Date.now() >= deadline) {
      throw new Error(`Timed out waiting for import job ${jobId} after ${timeoutMs}ms.`);
    }
    await delay(pollIntervalMs);
  }

  if (!latest) {
    throw new Error(`Import job ${jobId} completed without a status payload.`);
  }

  const job = {
    jobId,
    status: normalizeImportStatus(latest.status),
    statusUrl,
    pollCount,
    currentPhase: readOptionalString(latest, "currentPhase"),
    featuresProcessed: readOptionalNumber(latest, "featuresProcessed"),
    estimatedTotalFeatures: readOptionalNumber(latest, "estimatedTotalFeatures"),
    startedAt: readOptionalString(latest, "startedAt"),
    completedAt: readOptionalString(latest, "completedAt"),
    durationMs: readOptionalNumber(latest, "durationMs"),
    errorMessage: readOptionalString(latest, "errorMessage"),
  };

  return {
    item: liveImportItemFromJob(config, job),
    job,
  };
}

export function missingCloudImportConfig(config: HonuaCloudImportConfig): string[] {
  const missing: string[] = [];
  if (!config.enabled) missing.push("enabled");
  if (!config.adminBaseUrl) missing.push("adminBaseUrl");
  if (!config.sourceServiceUrl) missing.push("sourceServiceUrl");
  if (typeof config.layerId !== "number") missing.push("layerId");
  if (!config.tableName) missing.push("tableName");
  return missing;
}

function buildStages(args: {
  readonly mode: WorkbenchMode;
  readonly readiness: MigrationWorkbenchWorkflow["readiness"];
  readonly source: WorkbenchSourceSummary;
  readonly scanMetrics: readonly WorkbenchMetric[];
  readonly codemodMetrics: readonly WorkbenchMetric[];
  readonly contentItems: readonly WorkbenchContentItem[];
  readonly importItems: readonly WorkbenchImportItem[];
  readonly reconciliation: WorkbenchReconciliationSummary;
  readonly actionItems: readonly WorkbenchActionItem[];
  readonly artifacts: readonly WorkbenchArtifact[];
}): WorkbenchStage[] {
  const contentBlocked = args.contentItems.some((item) => item.status === "blocked");
  const contentManual = args.contentItems.some((item) => item.status === "manual");
  const importBlocked = args.importItems.some((item) => item.status === "blocked");
  const importRunning = args.importItems.some((item) => item.status === "running");
  const importFailed = args.importItems.some((item) => item.status === "failed");
  const importConfigured = args.importItems.some((item) => item.status === "configured");

  return [
    {
      id: "scan",
      title: "Scan",
      status: "complete",
      summary: `Scanned ${args.source.appRoot} for ArcGIS SDK usage and migration risk flags.`,
      metrics: args.scanMetrics,
      artifacts: artifactsFor(args.artifacts, "scan"),
      userMessages: [
        "Scan metadata and compatibility profile results can be cached because they describe source inventory, not live feature data.",
      ],
    },
    {
      id: "readiness",
      title: "Readiness",
      status: readinessStatus(args.readiness),
      summary: readinessSummary(args.readiness),
      metrics: [
        { label: "Readiness", value: args.readiness, tone: args.readiness === "ready" ? "good" : "warning" },
        {
          label: "Manual actions",
          value: String(args.actionItems.filter((item) => item.severity === "manual").length),
          tone: "warning",
        },
        {
          label: "Blocked items",
          value: String(args.actionItems.filter((item) => item.severity === "blocked").length),
          tone: args.actionItems.some((item) => item.severity === "blocked") ? "danger" : "good",
        },
      ],
      artifacts: artifactsFor(args.artifacts, "codemod"),
      userMessages: [
        "Readiness is based on codemod TODOs, unhandled ArcGIS modules, content conversion warnings, and blocked import items.",
      ],
    },
    {
      id: "codemod",
      title: "Migration Preview",
      status: args.actionItems.some((item) => item.sourceStage === "codemod") ? "manual" : "complete",
      summary: "Previewed ArcGIS JavaScript SDK rewrites and captured developer TODOs before applying live changes.",
      metrics: args.codemodMetrics,
      artifacts: artifactsFor(args.artifacts, "codemod"),
      userMessages: [
        "Automatic rewrites stay separate from manual TODOs so developers can review exactly what will change.",
      ],
    },
    {
      id: "content",
      title: "Content Conversion",
      status: contentBlocked ? "blocked" : contentManual ? "manual" : "complete",
      summary: "Converted web map JSON and materialized hosted feature data as regression artifacts.",
      metrics: [
        { label: "Web maps", value: String(args.contentItems.filter((item) => item.type === "web-map").length) },
        {
          label: "Materialized layers",
          value: String(args.contentItems.filter((item) => item.status === "materialized").length),
          tone: "good",
        },
        {
          label: "Blocked",
          value: String(args.contentItems.filter((item) => item.status === "blocked").length),
          tone: contentBlocked ? "danger" : "good",
        },
      ],
      artifacts: artifactsFor(args.artifacts, "content"),
      userMessages: [
        "Hosted feature data imports are represented as materialized artifacts such as GeoJSON or Esri feature-set files.",
      ],
    },
    {
      id: "import",
      title: args.mode === "live" ? "Live Honua Cloud Import" : "Demo Import Replay",
      status: importFailed
        ? "failed"
        : importRunning
          ? "running"
          : importBlocked
            ? "blocked"
            : importConfigured
              ? "waiting"
              : "complete",
      summary:
        args.mode === "live"
          ? "Live mode is opt-in and starts Honua Cloud import jobs only after cloud config is present."
          : "Demo mode replays deterministic import job results and never writes to Honua Cloud.",
      metrics: [
        { label: "Mode", value: args.mode },
        {
          label: "Completed",
          value: String(
            args.importItems.filter((item) => item.status === "completed" || item.status === "simulated").length,
          ),
          tone: "good",
        },
        {
          label: "Blocked",
          value: String(args.importItems.filter((item) => item.status === "blocked").length),
          tone: importBlocked ? "danger" : "good",
        },
      ],
      artifacts: artifactsFor(args.artifacts, "import"),
      userMessages: [
        args.mode === "live"
          ? "Live import polls Honua Cloud job status; fixture/demo import remains visually and structurally separate."
          : "Set the live import environment variables to switch this stage from replay to Honua Cloud orchestration.",
      ],
    },
    {
      id: "reconciliation",
      title: "Parity & Reconciliation",
      status:
        args.reconciliation.status === "pass"
          ? "complete"
          : args.reconciliation.status === "manual"
            ? "manual"
            : "failed",
      summary: args.reconciliation.userMessage,
      metrics: [
        { label: "Source count", value: String(args.reconciliation.sourceFeatureCount) },
        { label: "Target count", value: String(args.reconciliation.targetFeatureCount) },
        {
          label: "Delta",
          value: String(args.reconciliation.countDelta),
          tone: metricTone(Math.abs(args.reconciliation.countDelta)),
        },
      ],
      artifacts: artifactsFor(args.artifacts, "reconciliation"),
      userMessages: [
        "Reconciliation compares materialized source artifacts with imported Honua outputs and records manual web map parity decisions.",
      ],
    },
    {
      id: "report",
      title: "Exportable Report",
      status: "complete",
      summary: "Produces deterministic JSON and Markdown report artifacts for regression review.",
      metrics: [
        { label: "Artifacts", value: String(args.artifacts.length) },
        { label: "Report formats", value: "2", tone: "good" },
      ],
      artifacts: artifactsFor(args.artifacts, "report"),
      userMessages: ["The report can be exported or linked from CI and demo reviews."],
    },
  ];
}

function createFixtureImportItems(
  mode: WorkbenchMode,
  cloudImport: HonuaCloudImportConfig,
): readonly WorkbenchImportItem[] {
  if (mode === "demo") return WORKBENCH_IMPORT_ITEMS;

  const missing = missingCloudImportConfig(cloudImport);
  const configured = missing.length === 0;
  return WORKBENCH_IMPORT_ITEMS.map((item) => {
    if (item.status === "blocked") {
      return { ...item, mode, statusLabel: "Blocked before live import" };
    }
    return {
      ...item,
      mode,
      sourceServiceUrl: cloudImport.sourceServiceUrl ?? item.sourceServiceUrl,
      layerId: cloudImport.layerId ?? item.layerId,
      tableName: cloudImport.tableName ?? item.tableName,
      status: configured ? "configured" : "blocked",
      statusLabel: configured ? "Ready for Honua Cloud import" : `Missing live config: ${missing.join(", ")}`,
      jobId: undefined,
      processedFeatures: undefined,
      userMessage: configured
        ? "Live import is configured and will use Honua Cloud import/job orchestration when started."
        : "Live import was requested, but the app will not call Honua Cloud until required config is present.",
    };
  });
}

function withLiveConfigActions(
  mode: WorkbenchMode,
  cloudImport: HonuaCloudImportConfig,
  actions: WorkbenchActionItem[],
): WorkbenchActionItem[] {
  if (mode !== "live") return actions;
  const missing = missingCloudImportConfig(cloudImport);
  if (missing.length === 0) return actions;
  return [
    ...actions,
    {
      id: "blocked-live-import-config",
      severity: "blocked",
      sourceStage: "import",
      title: "Complete Honua Cloud import config",
      userMessage: `Live import is opt-in and is blocked until ${missing.join(", ")} is configured.`,
      nextStep:
        "Set the VITE_HONUA_CLOUD_ADMIN_BASE_URL, source service, layer, and table environment variables before starting a live import.",
    },
  ];
}

function contentItemsFromReports(artifacts: MigrationWorkbenchArtifacts): WorkbenchContentItem[] {
  const webMaps: WorkbenchContentItem[] = artifacts.contentImport.importedWebMaps.map((webMap) => {
    const status: WorkbenchContentItem["status"] =
      webMap.status === "failed" ? "blocked" : webMap.manualInterventionNeeded ? "manual" : "converted";
    return {
      id: webMap.itemId,
      title: webMap.title,
      type: "web-map",
      status,
      artifactPath: webMap.outputPath ?? artifacts.contentImport.reportPath,
      warningCount: webMap.warningCount,
      userMessage:
        webMap.status === "failed"
          ? `The web map failed conversion: ${webMap.errorMessage ?? "unknown conversion error"}`
          : webMap.manualInterventionNeeded
            ? "The web map converted, but unsupported properties require analyst review before publish."
            : "The web map converted without manual intervention warnings.",
    };
  });
  const hostedLayers: WorkbenchContentItem[] = artifacts.contentImport.importedHostedLayers.map((layer) => {
    const status: WorkbenchContentItem["status"] = layer.status === "completed" ? "materialized" : "blocked";
    return {
      id: `${layer.itemId}-${layer.layerId}`,
      title: `${layer.itemId} layer ${layer.layerId}`,
      type: "hosted-feature-layer",
      status,
      artifactPath: artifacts.contentImport.reportPath,
      featureCount: layer.sourceFeatureCount,
      userMessage:
        layer.status === "completed"
          ? "The hosted layer import is tied to a materialized source artifact and import job report."
          : `The hosted layer import failed: ${layer.errorMessage ?? "unknown import error"}`,
    };
  });
  return [...webMaps, ...hostedLayers].sort((a, b) => a.id.localeCompare(b.id));
}

function importItemsFromReport(
  artifacts: MigrationWorkbenchArtifacts,
  mode: WorkbenchMode,
  cloudImport: HonuaCloudImportConfig,
): WorkbenchImportItem[] {
  const missing = missingCloudImportConfig(cloudImport);
  const liveConfigured = mode === "live" && missing.length === 0;
  return artifacts.contentImport.importedHostedLayers.map((layer) => {
    if (mode === "live" && !liveConfigured) {
      return {
        id: `${layer.itemId}-${layer.layerId}`,
        title: `${layer.itemId} layer ${layer.layerId}`,
        mode,
        sourceServiceUrl: cloudImport.sourceServiceUrl ?? artifacts.source.sourceServiceUrl,
        layerId: cloudImport.layerId ?? layer.layerId,
        tableName: cloudImport.tableName ?? layer.tableName,
        status: "blocked",
        statusLabel: `Missing live config: ${missing.join(", ")}`,
        artifactPath: artifacts.contentImport.reportPath,
        totalFeatures: layer.sourceFeatureCount,
        userMessage: "Live import will not start until the required Honua Cloud config is present.",
      };
    }

    return {
      id: `${layer.itemId}-${layer.layerId}`,
      title: `${layer.itemId} layer ${layer.layerId}`,
      mode,
      sourceServiceUrl: cloudImport.sourceServiceUrl ?? artifacts.source.sourceServiceUrl,
      layerId: cloudImport.layerId ?? layer.layerId,
      tableName: cloudImport.tableName ?? layer.tableName,
      status: mode === "live" ? "configured" : layer.status === "completed" ? "simulated" : "failed",
      statusLabel:
        mode === "live"
          ? "Ready for Honua Cloud import"
          : layer.status === "completed"
            ? "Demo import completed"
            : "Demo import failed",
      artifactPath: artifacts.contentImport.reportPath,
      jobId: layer.job?.jobId,
      processedFeatures: layer.job?.featuresProcessed,
      totalFeatures: layer.sourceFeatureCount,
      userMessage:
        mode === "live"
          ? "Live import is configured and waiting for the user to start the Honua Cloud job."
          : "Demo mode replays the import report and does not write to Honua Cloud.",
    };
  });
}

function reconciliationFromReports(artifacts: MigrationWorkbenchArtifacts): WorkbenchReconciliationSummary {
  const manualWebMaps = artifacts.contentReconcile.summary.webMapsManual;
  const failedWebMaps = artifacts.contentReconcile.summary.webMapsFailed;
  const failedLayers = artifacts.contentReconcile.summary.hostedLayersFailed;
  const status = failedWebMaps > 0 || failedLayers > 0 ? "fail" : manualWebMaps > 0 ? "manual" : "pass";

  return {
    status,
    countDelta: artifacts.layerReconciliation.countDelta,
    sourceFeatureCount: artifacts.layerReconciliation.sourceFeatureCount,
    targetFeatureCount: artifacts.layerReconciliation.targetFeatureCount,
    missingTargetKeys: artifacts.layerReconciliation.missingInTargetAttributeKeys,
    extraTargetKeys: artifacts.layerReconciliation.extraInTargetAttributeKeys,
    userMessage:
      status === "pass"
        ? "Feature counts, geometry, attributes, and converted content reconcile."
        : status === "manual"
          ? "Feature parity passes, but one or more converted web maps require manual review."
          : "Reconciliation failed; review feature counts, schema deltas, or failed content conversions.",
  };
}

function actionItemsFromReports(artifacts: MigrationWorkbenchArtifacts): WorkbenchActionItem[] {
  const fromTodos = artifacts.migration.manualTodos.map((todo, index) => ({
    id: `manual-codemod-${index + 1}`,
    severity: "manual" as const,
    sourceStage: "codemod" as const,
    title: `Review ${humanizeKind(todo.kind)} in ${basename(todo.file)}`,
    userMessage: `The codemod left this call site for a developer because ${lowercaseFirst(todo.reason)}`,
    nextStep: "Open the codemod report, update the call site, and rerun the workbench report.",
    relatedArtifact: "reports/codemod-report.json",
  }));
  const fromUnhandled = artifacts.migration.unhandledArcGisModules.map((item, index) => ({
    id: `blocked-unhandled-module-${index + 1}`,
    severity: "blocked" as const,
    sourceStage: "readiness" as const,
    title: `Unsupported ArcGIS module: ${item.modulePath}`,
    userMessage: `The scanner found ${item.count} ${item.usageStyle} use of ${item.modulePath}, which is outside codemod scope.`,
    nextStep: "Replace the module or add a supported migration mapping before live import is approved.",
    relatedArtifact: "reports/arcgis-scan.json",
  }));
  const fromWebMaps = artifacts.contentReconcile.webMaps
    .filter((webMap) => webMap.status === "manual" || webMap.status === "fail")
    .map((webMap, index) => ({
      id: `${webMap.status}-webmap-${index + 1}`,
      severity: webMap.status === "manual" ? ("manual" as const) : ("blocked" as const),
      sourceStage: "content" as const,
      title: `${webMap.status === "manual" ? "Review" : "Fix"} ${webMap.title}`,
      userMessage: webMap.reason ?? "The web map did not fully reconcile.",
      nextStep:
        webMap.status === "manual"
          ? "Review the converted web map warnings and approve or edit the unsupported behavior."
          : "Fix the conversion error and rerun content import.",
      relatedArtifact: artifacts.contentReconcile.reportPath,
    }));
  const fromLayers = artifacts.contentReconcile.hostedLayers
    .filter((layer) => layer.status === "fail")
    .map((layer, index) => ({
      id: `blocked-layer-${index + 1}`,
      severity: "blocked" as const,
      sourceStage: "reconciliation" as const,
      title: `Reconcile layer ${layer.layerId}`,
      userMessage: layer.reason ?? "The hosted layer did not reconcile.",
      nextStep: "Compare the materialized source artifact with the Honua import job output and rerun reconciliation.",
      relatedArtifact: artifacts.contentReconcile.reportPath,
    }));
  return [...fromTodos, ...fromUnhandled, ...fromWebMaps, ...fromLayers].sort(compareActionItems);
}

function buildArtifactListFromReports(artifacts: MigrationWorkbenchArtifacts): WorkbenchArtifact[] {
  return [
    {
      id: "scan-json",
      kind: "scan",
      label: "Scan JSON",
      href: "reports/arcgis-scan.json",
      description: "ArcGIS import inventory and risk flags.",
    },
    {
      id: "codemod-report",
      kind: "codemod",
      label: "Codemod report",
      href: "reports/codemod-report.json",
      description: "Readiness, rewrite metrics, and manual migration TODOs.",
    },
    {
      id: "content-import-report",
      kind: "import",
      label: "Content import report",
      href: artifacts.contentImport.reportPath,
      description: "Content import results and Honua import job status.",
    },
    {
      id: "content-reconcile-report",
      kind: "reconciliation",
      label: "Content reconciliation report",
      href: artifacts.contentReconcile.reportPath,
      description: "Content parity checks for web maps and hosted layers.",
    },
  ];
}

function buildReportArtifacts(baseArtifacts: readonly WorkbenchArtifact[]): WorkbenchArtifact[] {
  const reportArtifacts: WorkbenchArtifact[] = [
    ...baseArtifacts,
    {
      id: "workbench-json-report",
      kind: "report",
      label: "Workbench JSON",
      href: "#workbench-report-json",
      description: "Deterministic report artifact for regression checks.",
    },
    {
      id: "workbench-markdown-report",
      kind: "report",
      label: "Workbench Markdown",
      href: "#workbench-report-markdown",
      description: "Human-readable report summary for reviewers.",
    },
  ];
  return reportArtifacts.sort(compareArtifacts);
}

function liveImportItemFromJob(
  config: HonuaCloudImportConfig,
  job: NonNullable<LiveImportProgress["job"]>,
): WorkbenchImportItem {
  const status = job.status === "Completed" ? "completed" : "failed";
  return {
    id: `live-${config.tableName ?? "import"}`,
    title: `${config.tableName ?? "Honua Cloud"} import`,
    mode: "live",
    sourceServiceUrl: config.sourceServiceUrl ?? "",
    layerId: config.layerId ?? 0,
    tableName: config.tableName ?? "unknown_table",
    status,
    statusLabel: status === "completed" ? "Honua Cloud import completed" : `Honua Cloud import ${job.status}`,
    jobId: job.jobId,
    processedFeatures: job.featuresProcessed,
    totalFeatures: job.estimatedTotalFeatures,
    userMessage:
      status === "completed"
        ? "Live import completed through Honua Cloud import/job orchestration."
        : (job.errorMessage ?? "Live import did not complete successfully."),
  };
}

function artifactsFor(artifacts: readonly WorkbenchArtifact[], kind: WorkbenchArtifact["kind"]): WorkbenchArtifact[] {
  return artifacts.filter((artifact) => artifact.kind === kind);
}

function readinessStatus(readiness: MigrationWorkbenchWorkflow["readiness"]): WorkbenchStageStatus {
  if (readiness === "ready") return "complete";
  if (readiness === "blocked") return "blocked";
  return "manual";
}

function readinessSummary(readiness: MigrationWorkbenchWorkflow["readiness"]): string {
  if (readiness === "ready") return "The source app is ready for automatic migration and import rehearsal.";
  if (readiness === "blocked") return "The source app has blocking migration issues that must be resolved first.";
  return "The source app can proceed with assisted migration after the listed manual items are reviewed.";
}

function stageMetrics(workflow: MigrationWorkbenchWorkflow, stageId: WorkbenchStageId): readonly WorkbenchMetric[] {
  return workflow.stages.find((stage) => stage.id === stageId)?.metrics ?? [];
}

function metricTone(count: number): WorkbenchMetric["tone"] {
  return count === 0 ? "good" : "warning";
}

function buildReportId(fixtureName: string, mode: WorkbenchMode, generatedAt: string): string {
  const stamp = generatedAt.replace(/\D/g, "").slice(0, 14) || "fixture";
  return `${fixtureName}-${mode}-${stamp}`.replace(/[^a-z0-9-]+/gi, "-").toLowerCase();
}

function compareArtifacts(a: WorkbenchArtifact, b: WorkbenchArtifact): number {
  return a.kind === b.kind ? a.id.localeCompare(b.id) : a.kind.localeCompare(b.kind);
}

function compareActionItems(a: WorkbenchActionItem, b: WorkbenchActionItem): number {
  const severityOrder = { blocked: 0, manual: 1, warning: 2 };
  return severityOrder[a.severity] === severityOrder[b.severity]
    ? a.id.localeCompare(b.id)
    : severityOrder[a.severity] - severityOrder[b.severity];
}

function humanizeKind(kind: string): string {
  return kind
    .split("-")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function basename(file: string): string {
  const parts = file.split(/[\\/]/);
  return parts[parts.length - 1] ?? file;
}

function lowercaseFirst(value: string): string {
  return value.length > 0 ? `${value.slice(0, 1).toLowerCase()}${value.slice(1)}` : value;
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

async function fetchJson(fetchFn: typeof fetch, url: string, init: RequestInit): Promise<unknown> {
  const response = await fetchFn(url, init);
  const text = await response.text();
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} from Honua Cloud import endpoint: ${text.slice(0, 200)}`);
  }
  return text.length > 0 ? JSON.parse(text) : {};
}

function buildJsonHeaders(adminApiKey?: string): Record<string, string> {
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
    ...(adminApiKey ? { "X-API-Key": adminApiKey } : {}),
  };
}

function asRecord(value: unknown, context: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${context} was not a JSON object.`);
  }
  return value as Record<string, unknown>;
}

function readRequiredString(source: Record<string, unknown>, key: string): string {
  const value = source[key];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`Expected ${key} to be a non-empty string.`);
  }
  return value;
}

function readOptionalString(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

function readOptionalNumber(source: Record<string, unknown>, key: string): number | undefined {
  const value = source[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function normalizeImportStatus(status: unknown): string {
  if (typeof status === "string" && status.length > 0) return status;
  if (typeof status === "number" && Number.isFinite(status)) {
    return IMPORT_STATUS_BY_ENUM_VALUE.get(Math.trunc(status)) ?? "Unknown";
  }
  return "Unknown";
}

function resolveStatusUrl(importBase: string, providedStatusUrl: string | undefined, jobId: string): string {
  const base = new URL(`${trimTrailingSlash(importBase)}/`);
  const resolved = new URL(providedStatusUrl ?? `jobs/${jobId}`, base);
  if (resolved.origin !== base.origin || !resolved.pathname.startsWith(base.pathname)) {
    throw new Error("Import job status URL must stay under the Honua Cloud import API.");
  }
  return resolved.toString();
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
