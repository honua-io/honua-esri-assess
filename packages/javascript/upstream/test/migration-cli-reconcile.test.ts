import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";

import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { getProjectRoot, withCliLockAsync } from "./migration-cli-lock.js";
import { getPreparedMigrationCliPath } from "./prepared-sdk-artifacts.js";

let server: http.Server | undefined;
let baseUrl = "";
const requestMethods: string[] = [];
const tempDirs: string[] = [];

function makeTempDir(): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "honua-cli-reconcile-"));
  tempDirs.push(directory);
  return directory;
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
    const isSource = url.pathname.startsWith("/source/");
    const isCount = url.searchParams.get("returnCountOnly") === "true";
    const isFailureTarget = url.searchParams.get("where") === "status = 'mismatch'";

    const payload = isCount
      ? { count: isSource ? 3 : isFailureTarget ? 2 : 3 }
      : {
          features: isSource
            ? [
                { attributes: { OBJECTID: 1, NAME: "A" }, geometry: { x: 1, y: 2 } },
                { attributes: { OBJECTID: 2, NAME: "B" }, geometry: { x: 2, y: 3 } },
              ]
            : isFailureTarget
              ? [
                  { attributes: { OBJECTID: 1 }, geometry: {} },
                  { attributes: { OBJECTID: 2 }, geometry: { x: 2, y: 3 } },
                ]
              : [
                  { attributes: { OBJECTID: 1, NAME: "A" }, geometry: { x: 1, y: 2 } },
                  { attributes: { OBJECTID: 2, NAME: "B" }, geometry: { x: 2, y: 3 } },
                ],
        };

    res.setHeader("Content-Type", "application/json");
    res.statusCode = 200;
    res.end(JSON.stringify(payload));
  });

  await new Promise<void>((resolve) => {
    server!.listen(0, "127.0.0.1", () => resolve());
  });

  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Failed to start CLI reconcile mock server");
  }
  baseUrl = `http://127.0.0.1:${address.port}`;
});

beforeEach(() => {
  requestMethods.length = 0;
});

afterAll(async () => {
  for (const directory of tempDirs.splice(0)) {
    fs.rmSync(directory, { recursive: true, force: true });
  }
  if (!server) {
    return;
  }
  await new Promise<void>((resolve) => server!.close(() => resolve()));
});

describe("migration cli reconcile", () => {
  it("returns exit code 0 when reconciliation checks pass", { timeout: 60_000 }, async () => {
    ensureBuiltCliArtifacts();
    const result = await runCli([
      "reconcile",
      "--source-base-url",
      `${baseUrl}/source`,
      "--source-service-id",
      "parcels",
      "--target-base-url",
      `${baseUrl}/target`,
      "--target-service-id",
      "parcels",
      "--layer-id",
      "0",
      "--sample-size",
      "25",
    ]);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("passed=yes");
    expect(result.stdout).toContain("checks=feature-count:pass,geometry-validity:pass,attribute-keys:pass");
    expect(requestMethods).toEqual(["GET", "GET", "GET", "GET"]);
  });

  it("writes a read-only reconciliation report without acknowledgement", { timeout: 60_000 }, async () => {
    ensureBuiltCliArtifacts();
    const reportPath = path.join(makeTempDir(), "reconcile-report.json");
    const result = await runCli([
      "reconcile",
      "--source-base-url",
      `${baseUrl}/source`,
      "--source-service-id",
      "parcels",
      "--target-base-url",
      `${baseUrl}/target`,
      "--target-service-id",
      "parcels",
      "--layer-id",
      "0",
      "--sample-size",
      "25",
      "--report",
      reportPath,
    ]);

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("passed=yes");
    expect(fs.existsSync(reportPath)).toBe(true);
    expect(requestMethods).toEqual(["GET", "GET", "GET", "GET"]);
  });

  it("detects report collisions before reconciliation network access", { timeout: 60_000 }, async () => {
    ensureBuiltCliArtifacts();
    const reportPath = path.join(makeTempDir(), "reconcile-report.json");
    fs.writeFileSync(reportPath, "preserve-me\n", "utf8");
    const result = await runCli([
      "reconcile",
      "--source-base-url",
      `${baseUrl}/source`,
      "--source-service-id",
      "parcels",
      "--target-base-url",
      `${baseUrl}/target`,
      "--target-service-id",
      "parcels",
      "--layer-id",
      "0",
      "--report",
      reportPath,
    ]);

    expect(result.status).toBe(1);
    expect(result.stderr).toContain("--force");
    expect(result.stdout).toBe("");
    expect(requestMethods).toEqual([]);
    expect(fs.readFileSync(reportPath, "utf8")).toBe("preserve-me\n");
  });
});

function runCli(
  args: readonly string[],
  envOverrides: Record<string, string> = {},
): Promise<{ status: number | null; stdout: string; stderr: string }> {
  return withCliLockAsync(
    () =>
      new Promise((resolve, reject) => {
        const child = spawn(process.execPath, [getPreparedMigrationCliPath(), ...args], {
          cwd: getProjectRoot(),
          env: {
            ...process.env,
            ...envOverrides,
          },
          stdio: ["ignore", "pipe", "pipe"],
        });

        let stdout = "";
        let stderr = "";
        child.stdout.on("data", (chunk: Buffer | string) => {
          stdout += chunk.toString();
        });
        child.stderr.on("data", (chunk: Buffer | string) => {
          stderr += chunk.toString();
        });

        child.on("error", (error) => reject(error));
        child.on("close", (status) => {
          resolve({
            status,
            stdout,
            stderr,
          });
        });
      }),
  );
}
