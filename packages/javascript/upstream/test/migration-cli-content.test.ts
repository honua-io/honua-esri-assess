import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";

import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { getProjectRoot, withCliLockAsync } from "./migration-cli-lock.js";
import { getPreparedMigrationCliPath } from "./prepared-sdk-artifacts.js";

let server: http.Server | undefined;
let portalUrl = "";
let failWebMapData = false;
const requestMethods: string[] = [];
const remoteErrorSecrets = [
  "remote-password-value",
  "remote-passwd-value",
  "remote-secret-value",
  "remote-authorization-value",
  "remote-credential-value",
  "remote-bearer-value",
];

const tempDirs: string[] = [];

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-cli-content-"));
  tempDirs.push(dir);
  return dir;
}

function ensureBuiltCliArtifacts(): void {
  getPreparedMigrationCliPath();
}

beforeAll(async () => {
  server = http.createServer((req, res) => {
    if (!req.url) {
      res.statusCode = 404;
      res.end();
      return;
    }
    requestMethods.push(req.method ?? "UNKNOWN");

    const url = new URL(req.url, "http://localhost");

    if (url.pathname.endsWith("/sharing/rest/search")) {
      const query = url.searchParams.get("q") ?? "";
      if (query.includes("Web Map")) {
        json(res, {
          total: 1,
          start: 1,
          nextStart: -1,
          results: [
            {
              id: "wm-1",
              title: "Test WebMap",
              type: "Web Map",
              owner: "owner-1",
            },
          ],
        });
        return;
      }
      if (query.includes("Hosted Service")) {
        json(res, {
          total: 1,
          start: 1,
          nextStart: -1,
          results: [
            {
              id: "svc-1",
              title: "Parcels",
              type: "Feature Service",
              owner: "owner-1",
              url: `${portalUrl}/arcgis/rest/services/Parcels/FeatureServer`,
            },
          ],
        });
        return;
      }
    }

    if (url.pathname.endsWith("/sharing/rest/content/items/wm-1/data")) {
      if (failWebMapData) {
        json(
          res,
          {
            password: remoteErrorSecrets[0],
            passwd: remoteErrorSecrets[1],
            secret: remoteErrorSecrets[2],
            authorization: remoteErrorSecrets[3],
            credential: remoteErrorSecrets[4],
            header: `Bearer ${remoteErrorSecrets[5]}`,
          },
          500,
        );
        return;
      }
      json(res, {
        operationalLayers: [
          {
            id: "parcels",
            layerType: "ArcGISFeatureLayer",
            url: `${portalUrl}/arcgis/rest/services/Parcels/FeatureServer/0`,
            layerDefinition: {
              drawingInfo: {
                renderer: {
                  type: "simple",
                  symbol: {
                    type: "esriSFS",
                    color: [120, 140, 180, 255],
                  },
                },
              },
            },
          },
        ],
      });
      return;
    }

    if (url.pathname.endsWith("/arcgis/rest/services/Parcels/FeatureServer")) {
      json(res, {
        layers: [{ id: 0, name: "Parcels" }],
      });
      return;
    }

    if (url.pathname.endsWith("/arcgis/rest/services/Parcels/FeatureServer/0")) {
      json(res, {
        id: 0,
        name: "Parcels",
        geometryType: "esriGeometryPoint",
      });
      return;
    }

    if (url.pathname.endsWith("/arcgis/rest/services/Parcels/FeatureServer/0/query")) {
      json(res, {
        geometryType: "esriGeometryPoint",
        features: [
          { attributes: { OBJECTID: 1 }, geometry: { x: 1, y: 2 } },
          { attributes: { OBJECTID: 2 }, geometry: { x: 2, y: 3 } },
        ],
      });
      return;
    }

    json(res, { error: `Unhandled URL ${url.pathname}` }, 404);
  });

  await new Promise<void>((resolve) => {
    server!.listen(0, "127.0.0.1", () => resolve());
  });

  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Failed to start migration content mock server");
  }
  portalUrl = `http://127.0.0.1:${address.port}`;
});

beforeEach(() => {
  failWebMapData = false;
  requestMethods.length = 0;
});

afterAll(async () => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }

  if (!server) {
    return;
  }
  await new Promise<void>((resolve) => server!.close(() => resolve()));
});

describe("migration cli content", () => {
  it("runs content scan", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();

    const result = await runCli(["content", "scan", "--portal", portalUrl]);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("contentScan");
    expect(result.stdout).toContain("webmaps=1");
    expect(result.stdout).toContain("hostedFeatureServices=1");
  });

  it("runs content export and writes manifest", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();
    const outputDir = path.join(makeTempDir(), "export");

    const result = await runCli([
      "content",
      "export",
      "--portal",
      portalUrl,
      "--output-dir",
      outputDir,
      "--acknowledge-mutations",
    ]);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("contentExport");

    const manifestPath = path.join(outputDir, "content-export-manifest.json");
    expect(fs.existsSync(manifestPath)).toBe(true);

    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as {
      webMaps: unknown[];
      hostedFeatureServices: Array<{ layers: unknown[] }>;
    };

    expect(manifest.webMaps).toHaveLength(1);
    expect(manifest.hostedFeatureServices).toHaveLength(1);
    expect(manifest.hostedFeatureServices[0].layers).toHaveLength(1);
  });

  it("refuses mutation without acknowledgement before writing files", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();
    const outputDir = path.join(makeTempDir(), "unacknowledged-export");

    const result = await runCli(["content", "export", "--portal", portalUrl, "--output-dir", outputDir]);

    expect(result.status).toBe(1);
    expect(result.stderr).toContain("--acknowledge-mutations");
    expect(fs.existsSync(outputDir)).toBe(false);
  });

  it("does not disclose credentials when refusing content import", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();
    const sourceDir = makeTempDir();
    const secret = "never-print-this-admin-key";

    const result = await runCli([
      "content",
      "import",
      "--source",
      sourceDir,
      "--target",
      "https://target.invalid",
      "--admin-api-key",
      secret,
    ]);

    expect(result.status).toBe(1);
    expect(result.stderr).toContain("--acknowledge-mutations");
    expect(`${result.stdout}\n${result.stderr}`).not.toContain(secret);
  });

  it("detects an export collision before network access", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();
    const outputDir = path.join(makeTempDir(), "existing-export");
    fs.mkdirSync(outputDir, { recursive: true });
    const sentinelPath = path.join(outputDir, "sentinel.txt");
    fs.writeFileSync(sentinelPath, "preserve-me\n", "utf8");

    const result = await runCli([
      "content",
      "export",
      "--portal",
      portalUrl,
      "--output-dir",
      outputDir,
      "--acknowledge-mutations",
    ]);

    expect(result.status).toBe(1);
    expect(result.stderr).toContain("--force");
    expect(requestMethods).toEqual([]);
    expect(fs.readFileSync(sentinelPath, "utf8")).toBe("preserve-me\n");
  });

  it("replaces an export tree only with force", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();
    const outputDir = path.join(makeTempDir(), "forced-export");
    fs.mkdirSync(outputDir, { recursive: true });
    fs.writeFileSync(path.join(outputDir, "sentinel.txt"), "old\n", "utf8");

    const result = await runCli([
      "content",
      "export",
      "--portal",
      portalUrl,
      "--output-dir",
      outputDir,
      "--acknowledge-mutations",
      "--force",
    ]);

    expect(result.status).toBe(0);
    expect(fs.existsSync(path.join(outputDir, "sentinel.txt"))).toBe(false);
    expect(fs.existsSync(path.join(outputDir, "content-export-manifest.json"))).toBe(true);
  });

  it("preserves an existing export tree when a forced export fails", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();
    const root = makeTempDir();
    const outputDir = path.join(root, "failed-export");
    fs.mkdirSync(outputDir, { recursive: true });
    const sentinelPath = path.join(outputDir, "sentinel.txt");
    const manifestPath = path.join(outputDir, "content-export-manifest.json");
    fs.writeFileSync(sentinelPath, "preserve-me\n", "utf8");
    fs.writeFileSync(manifestPath, "old-manifest\n", "utf8");
    failWebMapData = true;

    const result = await runCli([
      "content",
      "export",
      "--portal",
      portalUrl,
      "--output-dir",
      outputDir,
      "--acknowledge-mutations",
      "--force",
    ]);

    expect(result.status).toBe(1);
    expect(fs.readFileSync(sentinelPath, "utf8")).toBe("preserve-me\n");
    expect(fs.readFileSync(manifestPath, "utf8")).toBe("old-manifest\n");
    expect(fs.readdirSync(root).filter((entry) => entry.includes(".honua-"))).toEqual([]);
    for (const secret of remoteErrorSecrets) {
      expect(`${result.stdout}\n${result.stderr}`).not.toContain(secret);
    }
  });

  it("runs local content reconciliation without acknowledgement or network access", async () => {
    await ensureBuiltCliArtifacts();
    const sourceDir = makeTempDir();
    fs.writeFileSync(
      path.join(sourceDir, "content-export-manifest.json"),
      `${JSON.stringify({ webMaps: [], hostedFeatureServices: [] })}\n`,
      "utf8",
    );
    const importDir = path.join(sourceDir, "content-import");
    fs.mkdirSync(importDir, { recursive: true });
    fs.writeFileSync(
      path.join(importDir, "content-import-report.json"),
      `${JSON.stringify({ importedHostedLayers: [], importedWebMaps: [] })}\n`,
      "utf8",
    );

    const result = await runCli(["content", "reconcile", "--source", sourceDir]);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("contentReconcile");
    expect(requestMethods).toEqual([]);
    expect(fs.existsSync(path.join(sourceDir, "content-reconcile-report.json"))).toBe(true);
  });

  it("rejects URL queries and fragments without echoing their values", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();
    const querySecret = "innocent-key-secret-value";
    const fragmentSecret = "fragment-secret-value";

    const queryResult = await runCli(["content", "scan", "--portal", `${portalUrl}?context=${querySecret}`]);
    const fragmentResult = await runCli(["content", "scan", "--portal", `${portalUrl}#${fragmentSecret}`]);

    expect(queryResult.status).toBe(1);
    expect(fragmentResult.status).toBe(1);
    expect(`${queryResult.stdout}\n${queryResult.stderr}`).not.toContain(querySecret);
    expect(`${fragmentResult.stdout}\n${fragmentResult.stderr}`).not.toContain(fragmentSecret);
    expect(requestMethods).toEqual([]);
  });
});

async function runCli(args: readonly string[]): Promise<{ status: number | null; stdout: string; stderr: string }> {
  return withCliLockAsync(async () => {
    const child = spawn(process.execPath, [getPreparedMigrationCliPath(), ...args], {
      cwd: getProjectRoot(),
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout?.on("data", (chunk: Buffer | string) => {
      stdout += chunk.toString();
    });
    child.stderr?.on("data", (chunk: Buffer | string) => {
      stderr += chunk.toString();
    });

    const status = await new Promise<number | null>((resolve, reject) => {
      child.once("error", reject);
      child.once("close", (code) => resolve(code));
    });

    return {
      status,
      stdout,
      stderr,
    };
  });
}

function json(res: http.ServerResponse, body: unknown, status = 200): void {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(body));
}
