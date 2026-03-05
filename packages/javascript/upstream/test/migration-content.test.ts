import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { runContentExport, runContentImport, runContentReconcile, runContentScan } from "../src/migration/content.js";

const tempDirs: string[] = [];

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-migration-content-"));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("migration content workflow", () => {
  it("scans and exports portal content", async () => {
    const root = makeTempDir();
    const outputDir = path.join(root, "export");
    const portalUrl = "https://org.maps.arcgis.com";

    const scanFetch = createPortalFetch(portalUrl);

    const scan = await runContentScan({
      portalUrl,
      fetchFn: scanFetch,
    });

    expect(scan.webMaps).toHaveLength(1);
    expect(scan.hostedFeatureServices).toHaveLength(1);

    const report = await runContentExport({
      portalUrl,
      outputDir,
      fetchFn: scanFetch,
      includeFeatures: true,
    });

    expect(report.exportedWebMaps).toHaveLength(1);
    expect(report.exportedHostedFeatureServices).toHaveLength(1);
    expect(fs.existsSync(report.manifestPath)).toBe(true);

    const manifest = JSON.parse(fs.readFileSync(report.manifestPath, "utf8")) as {
      webMaps: Array<{ webMapPath: string }>;
      hostedFeatureServices: Array<{
        layers: Array<{ featureCount?: number; featureSetPath?: string; geoJsonPath?: string }>;
      }>;
    };

    expect(manifest.webMaps).toHaveLength(1);
    expect(manifest.hostedFeatureServices).toHaveLength(1);
    expect(manifest.hostedFeatureServices[0].layers).toHaveLength(1);

    const layer = manifest.hostedFeatureServices[0].layers[0];
    expect(layer.featureCount).toBe(2);
    expect(layer.featureSetPath).toBeDefined();
    expect(layer.geoJsonPath).toBeDefined();

    if (layer.featureSetPath) {
      expect(fs.existsSync(path.join(outputDir, layer.featureSetPath))).toBe(true);
    }
    if (layer.geoJsonPath) {
      expect(fs.existsSync(path.join(outputDir, layer.geoJsonPath))).toBe(true);
    }
  });

  it("imports exported content and reconciles reports", async () => {
    const root = makeTempDir();
    const sourceDir = path.join(root, "export");
    const portalUrl = "https://org.maps.arcgis.com";

    await runContentExport({
      portalUrl,
      outputDir: sourceDir,
      fetchFn: createPortalFetch(portalUrl),
      includeFeatures: true,
    });

    const importReport = await runContentImport({
      sourceDir,
      targetBaseUrl: "http://127.0.0.1:5050",
      adminApiKey: "demo-key",
      sourceUrlPrefix: "https://org.maps.arcgis.com",
      targetUrlPrefix: "https://honua.example.com",
      fetchFn: createImportFetch(),
      pollIntervalMs: 1,
      timeoutMs: 10_000,
    });

    expect(importReport.summary.hostedLayersCompleted).toBe(1);
    expect(importReport.summary.hostedLayersFailed).toBe(0);
    expect(importReport.summary.webMapsConverted).toBe(1);
    expect(importReport.summary.webMapsFailed).toBe(0);

    const reconcile = runContentReconcile({ sourceDir });
    expect(reconcile.summary.hostedLayersPassed).toBe(1);
    expect(reconcile.summary.hostedLayersFailed).toBe(0);
    expect(reconcile.summary.webMapsPassed).toBe(1);
    expect(reconcile.summary.webMapsManual).toBe(0);
    expect(reconcile.summary.webMapsFailed).toBe(0);
  });
});

function createPortalFetch(portalUrl: string): typeof fetch {
  const normalizedPortal = portalUrl.replace(/\/+$/, "");

  return (async (input: RequestInfo | URL) => {
    const urlString = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const url = new URL(urlString);

    if (url.pathname.endsWith("/sharing/rest/search")) {
      const query = url.searchParams.get("q") ?? "";
      if (query.includes("Web Map")) {
        return jsonResponse({
          total: 1,
          start: 1,
          nextStart: -1,
          results: [
            {
              id: "wm-1",
              title: "City Map",
              type: "Web Map",
              owner: "owner-1",
            },
          ],
        });
      }
      if (query.includes("Hosted Service")) {
        return jsonResponse({
          total: 1,
          start: 1,
          nextStart: -1,
          results: [
            {
              id: "svc-1",
              title: "Parcels Service",
              type: "Feature Service",
              owner: "owner-1",
              url: `${normalizedPortal}/arcgis/rest/services/Parcels/FeatureServer`,
            },
          ],
        });
      }
    }

    if (url.pathname.endsWith("/sharing/rest/content/items/wm-1/data")) {
      return jsonResponse({
        version: "2.28",
        operationalLayers: [
          {
            id: "parcels",
            title: "Parcels",
            layerType: "ArcGISFeatureLayer",
            url: `${normalizedPortal}/arcgis/rest/services/Parcels/FeatureServer/0`,
            layerDefinition: {
              drawingInfo: {
                renderer: {
                  type: "simple",
                  symbol: {
                    type: "esriSFS",
                    color: [120, 160, 210, 255],
                  },
                },
              },
            },
          },
        ],
      });
    }

    if (url.pathname.endsWith("/arcgis/rest/services/Parcels/FeatureServer")) {
      return jsonResponse({
        layers: [{ id: 0, name: "Parcels" }],
      });
    }

    if (url.pathname.endsWith("/arcgis/rest/services/Parcels/FeatureServer/0")) {
      return jsonResponse({
        id: 0,
        name: "Parcels",
        geometryType: "esriGeometryPoint",
      });
    }

    if (url.pathname.endsWith("/arcgis/rest/services/Parcels/FeatureServer/0/query")) {
      return jsonResponse({
        geometryType: "esriGeometryPoint",
        features: [
          {
            attributes: { OBJECTID: 1, NAME: "A" },
            geometry: { x: -122.4, y: 37.78 },
          },
          {
            attributes: { OBJECTID: 2, NAME: "B" },
            geometry: { x: -122.41, y: 37.79 },
          },
        ],
      });
    }

    return new Response(JSON.stringify({ error: { code: 404, message: `Unhandled URL: ${urlString}` } }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
}

function createImportFetch(): typeof fetch {
  let pollCount = 0;

  return (async (input: RequestInfo | URL, init?: RequestInit) => {
    const urlString = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;

    if (urlString.endsWith("/api/v1/admin/import/geoservices/start")) {
      return jsonResponse(
        {
          jobId: "job-1",
          statusUrl: "jobs/job-1",
        },
        202,
      );
    }

    if (urlString.endsWith("/api/v1/admin/import/geoservices/jobs/job-1")) {
      pollCount += 1;
      if (pollCount === 1) {
        return jsonResponse({
          jobId: "job-1",
          status: 0,
          currentPhase: "Queued",
          featuresProcessed: 0,
        });
      }

      return jsonResponse({
        jobId: "job-1",
        status: "Completed",
        currentPhase: "Done",
        featuresProcessed: 2,
        estimatedTotalFeatures: 2,
      });
    }

    return new Response(JSON.stringify({ error: `Unhandled URL: ${urlString}`, method: init?.method }), {
      status: 404,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
