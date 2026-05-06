import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  applyLiveImportProgress,
  createFixtureMigrationWorkbenchWorkflow,
  createMigrationWorkbenchWorkflowFromArtifacts,
  createWorkbenchReport,
  runHonuaCloudImportJob,
  serializeWorkbenchReport,
} from "../examples/migration-workbench/src/model.js";
import type { MigrationWorkbenchArtifacts, WorkbenchSourceSummary } from "../examples/migration-workbench/src/types.js";
import { runEsriCompatCodemod } from "../src/migration/codemod.js";
import type { ContentImportReport, ContentReconcileReport } from "../src/migration/content.js";
import type { GeoservicesImportJobReport } from "../src/migration/demo.js";
import type { LayerReconciliationReport } from "../src/migration/reconcile.js";
import { buildJsMigrationReport } from "../src/migration/report.js";
import { scanArcGisUsage } from "../src/migration/scanner.js";

describe("migration workbench model", () => {
  it("builds a deterministic fixture workflow with all required stages visible", () => {
    const workflow = createFixtureMigrationWorkbenchWorkflow();
    const report = createWorkbenchReport(workflow);
    const json = serializeWorkbenchReport(report);

    expect(workflow.mode).toBe("demo");
    expect(workflow.stages.map((stage) => stage.id)).toEqual([
      "scan",
      "readiness",
      "codemod",
      "content",
      "import",
      "reconciliation",
      "report",
    ]);
    expect(workflow.stages.find((stage) => stage.id === "import")?.title).toBe("Demo Import Replay");
    expect(workflow.importItems.some((item) => item.userMessage.includes("no cloud write was attempted"))).toBe(true);
    expect(workflow.contentItems.some((item) => item.artifactPath.includes("features.geojson"))).toBe(true);
    expect(report.summary.manualActionCount).toBeGreaterThan(0);
    expect(report.summary.blockedActionCount).toBeGreaterThan(0);
    expect(report.notes).toContain(
      "Feature data imports are tracked as materialized artifacts, not transparent feature-query caches.",
    );
    expect(json).toBe(serializeWorkbenchReport(createWorkbenchReport(createFixtureMigrationWorkbenchWorkflow())));
  });

  it("keeps live Honua Cloud import opt-in and blocked until required config is complete", () => {
    const missingConfig = createFixtureMigrationWorkbenchWorkflow({
      mode: "live",
      cloudImport: { enabled: true },
    });

    expect(missingConfig.stages.find((stage) => stage.id === "import")?.title).toBe("Live Honua Cloud Import");
    expect(missingConfig.importItems.some((item) => item.status === "blocked")).toBe(true);
    expect(missingConfig.actionItems.some((item) => item.id === "blocked-live-import-config")).toBe(true);

    const configured = createFixtureMigrationWorkbenchWorkflow({
      mode: "live",
      cloudImport: {
        enabled: true,
        adminBaseUrl: "https://honua.example",
        sourceServiceUrl: "https://org.maps.arcgis.com/arcgis/rest/services/Hydrants/FeatureServer",
        layerId: 0,
        tableName: "hydrants_live",
      },
    });

    expect(configured.importItems.some((item) => item.status === "configured")).toBe(true);
    expect(configured.actionItems.some((item) => item.id === "blocked-live-import-config")).toBe(false);
  });

  it("maps existing migration and content artifact shapes into the workbench report", () => {
    const artifacts = createExistingMigrationArtifacts();
    const workflow = createMigrationWorkbenchWorkflowFromArtifacts(artifacts, {
      generatedAt: "2026-05-05T18:30:00.000Z",
    });
    const report = createWorkbenchReport(workflow);

    expect(workflow.stages.find((stage) => stage.id === "scan")?.metrics[0]?.value).toBe(
      String(artifacts.scan.filesScanned),
    );
    expect(workflow.stages.find((stage) => stage.id === "codemod")?.metrics[0]?.value).toBe(
      String(artifacts.migration.codemodResult.metrics.autoMigratedCallSites),
    );
    expect(workflow.contentItems.map((item) => item.status)).toContain("manual");
    expect(workflow.contentItems.map((item) => item.status)).toContain("materialized");
    expect(workflow.importItems[0]?.status).toBe("simulated");
    expect(report.summary.reconciliationStatus).toBe("manual");
    expect(serializeWorkbenchReport(report)).toContain("hydrants_honua");
  });

  it("polls a live Honua Cloud import job and updates the workflow import stage", async () => {
    const requests: Array<{ url: string; method: string; apiKey?: string; body?: string }> = [];
    const fetchFn: typeof fetch = (async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const headers = normalizeHeaders(init?.headers);
      requests.push({
        url,
        method: init?.method ?? "GET",
        apiKey: headers["x-api-key"],
        body: typeof init?.body === "string" ? init.body : undefined,
      });

      if (url.endsWith("/api/v1/admin/import/geoservices/start")) {
        return jsonResponse({ jobId: "job-workbench-1", statusUrl: "jobs/job-workbench-1" }, 202);
      }

      if (url.endsWith("/api/v1/admin/import/geoservices/jobs/job-workbench-1")) {
        return jsonResponse({
          status: "Completed",
          currentPhase: "Done",
          featuresProcessed: 128,
          estimatedTotalFeatures: 128,
        });
      }

      return jsonResponse({ error: "unexpected" }, 404);
    }) as typeof fetch;

    const progress = await runHonuaCloudImportJob(
      {
        enabled: true,
        adminBaseUrl: "https://honua.example",
        adminApiKey: "test-key",
        sourceServiceUrl: "https://org.maps.arcgis.com/arcgis/rest/services/Hydrants/FeatureServer",
        layerId: 0,
        tableName: "hydrants_live",
      },
      { fetchFn },
    );

    expect(progress.job?.status).toBe("Completed");
    expect(progress.item.status).toBe("completed");
    expect(progress.item.processedFeatures).toBe(128);
    expect(requests[0]).toMatchObject({
      method: "POST",
      apiKey: "test-key",
    });

    const workflow = createFixtureMigrationWorkbenchWorkflow({
      mode: "live",
      cloudImport: {
        enabled: true,
        adminBaseUrl: "https://honua.example",
        sourceServiceUrl: "https://org.maps.arcgis.com/arcgis/rest/services/Hydrants/FeatureServer",
        layerId: 0,
        tableName: "hydrants_live",
      },
    });
    const updated = applyLiveImportProgress(workflow, {
      ...progress,
      item: { ...progress.item, id: "import-hydrants-0" },
    });

    expect(updated.importItems.find((item) => item.id === "import-hydrants-0")?.status).toBe("completed");
    expect(updated.stages.find((stage) => stage.id === "import")?.metrics[1]?.value).toBe("1");
  });
});

function createExistingMigrationArtifacts(): MigrationWorkbenchArtifacts {
  const fixtureDir = fileURLToPath(new URL("./fixtures/esri-demo-feature-table-relates-app", import.meta.url));
  const scan = scanArcGisUsage(fixtureDir);
  const codemod = runEsriCompatCodemod({
    rootDir: fixtureDir,
    target: "honua-compat",
    annotateTodos: true,
  });
  const migration = buildJsMigrationReport(fixtureDir, codemod, scan);
  const source: WorkbenchSourceSummary = {
    title: "Hydrant migration artifact bridge",
    fixtureName: "esri-demo-feature-table-relates-app",
    owner: "City Utilities",
    sourcePortal: "https://org.maps.arcgis.com",
    sourceServiceUrl: "https://org.maps.arcgis.com/arcgis/rest/services/Hydrants/FeatureServer",
    sourceServiceId: "Hydrants",
    targetServiceId: "hydrants_honua",
    layerId: 0,
    appRoot: "test/fixtures/esri-demo-feature-table-relates-app",
    compatibilityProfile: "Honua JS compat + content import MVP",
  };
  const job: GeoservicesImportJobReport = {
    jobId: "job-artifact-1",
    status: "Completed",
    statusUrl: "https://honua.example/api/v1/admin/import/geoservices/jobs/job-artifact-1",
    pollCount: 1,
    featuresProcessed: 128,
    estimatedTotalFeatures: 128,
  };
  const contentImport: ContentImportReport = {
    generatedAt: "2026-05-05T18:20:00.000Z",
    sourceDir: "/tmp/workbench-export",
    outputDir: "/tmp/workbench-import",
    targetBaseUrl: "https://honua.example",
    manifestPath: "/tmp/workbench-export/content-export-manifest.json",
    importedHostedLayers: [
      {
        itemId: "svc-hydrants",
        layerId: 0,
        tableName: "hydrants_honua",
        status: "completed",
        job,
        sourceFeatureCount: 128,
      },
    ],
    importedWebMaps: [
      {
        itemId: "wm-hydrants",
        title: "Hydrant operations",
        status: "converted",
        outputPath: "webmaps/hydrant-operations.honua.json",
        warningCount: 2,
        manualInterventionNeeded: true,
        rewrittenUrlCount: 1,
      },
    ],
    summary: {
      hostedLayersCompleted: 1,
      hostedLayersFailed: 0,
      webMapsConverted: 1,
      webMapsFailed: 0,
      webMapsManualIntervention: 1,
    },
    reportPath: "/tmp/workbench-import/content-import-report.json",
  };
  const contentReconcile: ContentReconcileReport = {
    generatedAt: "2026-05-05T18:21:00.000Z",
    sourceDir: "/tmp/workbench-export",
    manifestPath: "/tmp/workbench-export/content-export-manifest.json",
    importReportPath: "/tmp/workbench-import/content-import-report.json",
    hostedLayers: [
      {
        itemId: "svc-hydrants",
        layerId: 0,
        tableName: "hydrants_honua",
        status: "pass",
        sourceFeatureCount: 128,
        targetProcessedCount: 128,
      },
    ],
    webMaps: [
      {
        itemId: "wm-hydrants",
        title: "Hydrant operations",
        status: "manual",
        warningCount: 2,
        reason: "manual intervention required due to unsupported properties",
      },
    ],
    summary: {
      hostedLayersPassed: 1,
      hostedLayersFailed: 0,
      webMapsPassed: 0,
      webMapsManual: 1,
      webMapsFailed: 0,
    },
    reportPath: "/tmp/workbench-export/content-reconcile-report.json",
  };
  const layerReconciliation: LayerReconciliationReport = {
    sourceBaseUrl: "https://org.maps.arcgis.com",
    sourceServiceId: "Hydrants",
    targetBaseUrl: "https://honua.example",
    targetServiceId: "hydrants_honua",
    layerId: 0,
    sampleSize: 25,
    sourceFeatureCount: 128,
    targetFeatureCount: 128,
    countDelta: 0,
    sourceGeometryValidityRatio: 1,
    targetGeometryValidityRatio: 1,
    sourceAttributeKeys: ["FACILITYID", "OBJECTID", "status"],
    targetAttributeKeys: ["FACILITYID", "OBJECTID", "honua_import_job_id", "status"],
    missingInTargetAttributeKeys: [],
    extraInTargetAttributeKeys: ["honua_import_job_id"],
    checks: [
      { check: "feature-count", passed: true, detail: "counts match (128)" },
      { check: "geometry-validity", passed: true, detail: "target valid geometry ratio=1.000" },
      { check: "attribute-keys", passed: true, detail: "target covers source attribute keys" },
    ],
    passed: true,
  };

  return {
    source,
    scan,
    migration,
    contentImport,
    contentReconcile,
    layerReconciliation,
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function normalizeHeaders(headers: HeadersInit | undefined): Record<string, string> {
  const normalized: Record<string, string> = {};
  if (!headers) return normalized;
  if (headers instanceof Headers) {
    headers.forEach((value, key) => {
      normalized[key.toLowerCase()] = value;
    });
    return normalized;
  }
  if (Array.isArray(headers)) {
    for (const [key, value] of headers) normalized[key.toLowerCase()] = value;
    return normalized;
  }
  for (const [key, value] of Object.entries(headers)) normalized[key.toLowerCase()] = value;
  return normalized;
}
