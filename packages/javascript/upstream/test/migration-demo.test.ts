import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

import { parseGeoservicesServiceUrl, runGeoservicesImportJob, runMigrationDemo } from "../src/migration/demo.js";

const tempDirs: string[] = [];

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-migration-demo-"));
  tempDirs.push(dir);
  return dir;
}

function fixtureRoot(): string {
  return fileURLToPath(new URL("./fixtures", import.meta.url));
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("migration demo helpers", () => {
  it("parses geoservices service URL details", () => {
    const parsed = parseGeoservicesServiceUrl("https://example.test/gis/rest/services/incidents/FeatureServer/3");

    expect(parsed).toEqual({
      baseUrl: "https://example.test/gis",
      serviceId: "incidents",
      serviceType: "FeatureServer",
      layerId: 3,
    });
  });

  it("runs geoservices import polling until completion", async () => {
    const requests: Array<{
      url: string;
      method: string;
      headers: Record<string, string>;
      body: string;
    }> = [];
    let pollCount = 0;

    const fetchFn: typeof fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const method = init?.method ?? "GET";
      const headers = normalizeHeaders(init?.headers);
      const body =
        typeof init?.body === "string"
          ? init.body
          : init?.body instanceof Uint8Array
            ? Buffer.from(init.body).toString("utf8")
            : "";

      requests.push({ url, method, headers, body });

      if (url.endsWith("/api/v1/admin/import/geoservices/start")) {
        return new Response(JSON.stringify({ jobId: "job-123", statusUrl: "jobs/job-123" }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        });
      }

      if (url.endsWith("/api/v1/admin/import/geoservices/jobs/job-123")) {
        pollCount += 1;
        if (pollCount === 1) {
          return new Response(
            JSON.stringify({
              jobId: "job-123",
              status: 0,
              currentPhase: "Queued",
              featuresProcessed: 0,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }

        return new Response(
          JSON.stringify({
            jobId: "job-123",
            status: "Completed",
            currentPhase: "Done",
            featuresProcessed: 42,
            estimatedTotalFeatures: 42,
            errorMessage: "password=completed-job-secret",
            startedAt: "password=completed-start-secret",
            completedAt: "2026-07-22T00:00:00Z\ntoken=completed-end-secret",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      return new Response(JSON.stringify({ error: "not found" }), { status: 404 });
    }) as typeof fetch;

    const result = await runGeoservicesImportJob({
      adminBaseUrl: "http://127.0.0.1:5050",
      adminApiKey: "demo-key",
      sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
      layerId: 0,
      tableName: "incidents",
      pollIntervalMs: 1,
      timeoutMs: 5_000,
      fetchFn,
    });

    expect(result.jobId).toBe("job-123");
    expect(result.status).toBe("Completed");
    expect(result.pollCount).toBe(2);
    expect(result.featuresProcessed).toBe(42);
    expect(result).not.toHaveProperty("errorMessage");
    expect(result.startedAt).toBeUndefined();
    expect(result.completedAt).toBeUndefined();
    expect(JSON.stringify(result)).not.toContain("completed-start-secret");
    expect(JSON.stringify(result)).not.toContain("completed-end-secret");

    const startRequest = requests.find((request) => request.url.endsWith("/start"));
    expect(startRequest?.method).toBe("POST");
    expect(startRequest?.headers["x-api-key"]).toBe("demo-key");
    expect(startRequest?.body).toContain('"tableName":"incidents"');
  });

  it("rejects cross-origin geoservices import status URLs before polling with the admin key", async () => {
    const requests: Array<{ url: string; headers: Record<string, string> }> = [];

    const fetchFn: typeof fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const headers = normalizeHeaders(init?.headers);
      requests.push({ url, headers });

      if (url.endsWith("/api/v1/admin/import/geoservices/start")) {
        return new Response(
          JSON.stringify({
            jobId: "job-123",
            statusUrl: "https://attacker.example/jobs/job-123",
          }),
          {
            status: 202,
            headers: { "Content-Type": "application/json" },
          },
        );
      }

      return new Response(JSON.stringify({ error: "unexpected poll" }), { status: 500 });
    }) as typeof fetch;

    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        adminApiKey: "demo-key",
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        pollIntervalMs: 1,
        timeoutMs: 5_000,
        fetchFn,
      }),
    ).rejects.toThrow("Import job status URL must stay on the configured admin origin.");

    expect(requests).toHaveLength(1);
    expect(requests[0]?.headers["x-api-key"]).toBe("demo-key");
    expect(requests.some((request) => hasOrigin(request.url, "https://attacker.example"))).toBe(false);
  });

  it("rejects same-origin geoservices import status URLs outside the import API path", async () => {
    const requests: Array<{ url: string; headers: Record<string, string> }> = [];

    const fetchFn: typeof fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const headers = normalizeHeaders(init?.headers);
      requests.push({ url, headers });

      if (url.endsWith("/api/v1/admin/import/geoservices/start")) {
        return new Response(
          JSON.stringify({
            jobId: "job-123",
            statusUrl: "/api/v1/admin/import/geoservices-other/jobs/job-123",
          }),
          {
            status: 202,
            headers: { "Content-Type": "application/json" },
          },
        );
      }

      return new Response(JSON.stringify({ error: "unexpected poll" }), { status: 500 });
    }) as typeof fetch;

    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        adminApiKey: "demo-key",
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        pollIntervalMs: 1,
        timeoutMs: 5_000,
        fetchFn,
      }),
    ).rejects.toThrow("Import job status URL must stay under the geoservices import API path.");

    expect(requests).toHaveLength(1);
    expect(requests[0]?.headers["x-api-key"]).toBe("demo-key");
  });

  it("rejects geoservices import status URLs with encoded path separators", async () => {
    const requests: Array<{ url: string; headers: Record<string, string> }> = [];

    const fetchFn: typeof fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const headers = normalizeHeaders(init?.headers);
      requests.push({ url, headers });

      if (url.endsWith("/api/v1/admin/import/geoservices/start")) {
        return new Response(
          JSON.stringify({
            jobId: "job-123",
            statusUrl: "/api/v1/admin/import/geoservices/%2F..%2Fgeoservices-other/jobs/job-123",
          }),
          {
            status: 202,
            headers: { "Content-Type": "application/json" },
          },
        );
      }

      return new Response(JSON.stringify({ error: "unexpected poll" }), { status: 500 });
    }) as typeof fetch;

    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        adminApiKey: "demo-key",
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        pollIntervalMs: 1,
        timeoutMs: 5_000,
        fetchFn,
      }),
    ).rejects.toThrow("Import job status URL must stay under the geoservices import API path.");

    expect(requests).toHaveLength(1);
    expect(requests[0]?.headers["x-api-key"]).toBe("demo-key");
  });

  it("does not expose remote error bodies in migration demo errors", async () => {
    const apiKey = "demo-key-secret";
    const password = "remote-password-value";
    const bearer = "remote-bearer-value";
    const fetchFn: typeof fetch = (async () =>
      new Response(
        JSON.stringify({
          password,
          authorization: `Bearer ${bearer}`,
        }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        },
      )) as typeof fetch;

    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        adminApiKey: apiKey,
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        fetchFn,
      }),
    ).rejects.toThrow("Import request failed with HTTP status 500.");

    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        adminApiKey: apiKey,
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        fetchFn,
      }),
    ).rejects.not.toThrow(apiKey);
    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        adminApiKey: apiKey,
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        fetchFn,
      }),
    ).rejects.not.toThrow(password);
    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        adminApiKey: apiKey,
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        fetchFn,
      }),
    ).rejects.not.toThrow(bearer);
  });

  it("rejects unsafe remote job identifiers before constructing a status URL", async () => {
    const maliciousJobId = "job?token=job-secret\nterminal-injection";
    const requests: string[] = [];
    const fetchFn: typeof fetch = (async (input) => {
      requests.push(String(input));
      return new Response(JSON.stringify({ jobId: maliciousJobId }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        fetchFn,
      }),
    ).rejects.toThrow("Import start response contained an invalid job identifier.");

    await expect(
      runGeoservicesImportJob({
        adminBaseUrl: "http://127.0.0.1:5050",
        sourceServiceUrl: "https://arcgis.example/rest/services/incidents/FeatureServer",
        layerId: 0,
        tableName: "incidents",
        fetchFn,
      }),
    ).rejects.not.toThrow("job-secret");
    expect(requests).toHaveLength(2);
  });

  it("runs migration demo codemod stage and writes fixture output", async () => {
    const outputDir = makeTempDir();
    const report = await runMigrationDemo({
      fixtureName: "esri-ready-app",
      fixturesRoot: fixtureRoot(),
      outputDir,
      skipImport: true,
      skipReconciliation: true,
    });

    expect(report.passed).toBe(true);
    expect(report.elapsedMs).toBeGreaterThanOrEqual(0);
    expect(report.migration.readiness).toBe("ready");
    expect(report.migration.codemodResult.metrics.manualCallSites).toBe(0);
    expect(fs.existsSync(path.join(report.workingAppDir, "src", "main.ts"))).toBe(true);
  });
});

/**
 * Exact origin comparison via `URL` parsing, not substring/`startsWith`
 * matching (which can be spoofed by a host such as
 * `https://attacker.example.evil.test`).
 */
function hasOrigin(url: string, origin: string): boolean {
  try {
    return new URL(url).origin === new URL(origin).origin;
  } catch {
    return false;
  }
}

function normalizeHeaders(headers: HeadersInit | undefined): Record<string, string> {
  if (!headers) {
    return {};
  }

  const normalized: Record<string, string> = {};
  const entries = new Headers(headers).entries();
  for (const [key, value] of entries) {
    normalized[key] = value;
  }
  return normalized;
}
