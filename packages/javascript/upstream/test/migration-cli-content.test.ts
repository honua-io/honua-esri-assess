import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { execSync, spawn } from "node:child_process";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

let server: http.Server | undefined;
let portalUrl = "";
let builtOnce = false;

const tempDirs: string[] = [];

function projectRoot(): string {
  return path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
}

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-cli-content-"));
  tempDirs.push(dir);
  return dir;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function withCliLock<T>(work: () => Promise<T> | T): Promise<T> {
  const lockDir = path.join(projectRoot(), ".tmp", "vitest-cli-lock");
  fs.mkdirSync(path.dirname(lockDir), { recursive: true });
  for (;;) {
    try {
      await fs.promises.mkdir(lockDir);
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
        throw error;
      }
      await sleep(25);
    }
  }

  try {
    return await work();
  } finally {
    await fs.promises.rm(lockDir, { recursive: true, force: true });
  }
}

async function ensureBuiltCliArtifacts(): Promise<void> {
  await withCliLock(() => {
    if (builtOnce) {
      return;
    }

    execSync("npm run build --silent", {
      cwd: projectRoot(),
      stdio: "pipe",
    });
    builtOnce = true;
  });
}

beforeAll(async () => {
  server = http.createServer((req, res) => {
    if (!req.url) {
      res.statusCode = 404;
      res.end();
      return;
    }

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

    const result = await runCli(["dist/src/migration/cli.js", "content", "scan", "--portal", portalUrl]);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("contentScan");
    expect(result.stdout).toContain("webmaps=1");
    expect(result.stdout).toContain("hostedFeatureServices=1");
  });

  it("runs content export and writes manifest", { timeout: 180_000 }, async () => {
    await ensureBuiltCliArtifacts();
    const outputDir = path.join(makeTempDir(), "export");

    const result = await runCli([
      "dist/src/migration/cli.js",
      "content",
      "export",
      "--portal",
      portalUrl,
      "--output-dir",
      outputDir,
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
});

async function runCli(args: readonly string[]): Promise<{ status: number | null; stdout: string; stderr: string }> {
  return withCliLock(async () => {
    const child = spawn("node", args, {
      cwd: projectRoot(),
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
