import { spawn } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";

import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { getProjectRoot, withCliLockAsync } from "./migration-cli-lock.js";
import { getPreparedMigrationCliPath } from "./prepared-sdk-artifacts.js";

const tempDirs: string[] = [];
let server: http.Server | undefined;
let adminBaseUrl = "";
const remoteSecrets = ["demo-password-value", "demo-credential-value", "demo-bearer-value"];

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-cli-demo-"));
  tempDirs.push(dir);
  return dir;
}

function ensureBuiltCliArtifacts(): void {
  getPreparedMigrationCliPath();
}

async function runCli(
  args: readonly string[],
  cwd: string,
): Promise<{ status: number | null; stdout: string; stderr: string }> {
  return withCliLockAsync(async () => {
    const cliPath = getPreparedMigrationCliPath();
    const child = spawn("node", [cliPath, ...args], {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    const status = await new Promise<number | null>((resolve, reject) => {
      child.once("error", reject);
      child.once("close", resolve);
    });
    return {
      status,
      stdout,
      stderr,
    };
  });
}

beforeAll(async () => {
  server = http.createServer((_req, res) => {
    res.statusCode = 500;
    res.setHeader("Content-Type", "application/json");
    res.end(
      JSON.stringify({
        password: remoteSecrets[0],
        credential: remoteSecrets[1],
        authorization: `Bearer ${remoteSecrets[2]}`,
      }),
    );
  });
  await new Promise<void>((resolve) => server!.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Failed to start demo error server");
  }
  adminBaseUrl = `http://127.0.0.1:${address.port}`;
});

afterAll(async () => {
  if (server) {
    await new Promise<void>((resolve) => server!.close(() => resolve()));
  }
});

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("migration cli demo", () => {
  it("runs codemod-only demo mode and writes report", { timeout: 60_000 }, async () => {
    ensureBuiltCliArtifacts();
    const root = makeTempDir();
    const outputDir = path.join(root, "output");
    const reportPath = path.join(root, "demo-report.json");

    const result = await runCli(
      [
        "demo",
        "--acknowledge-mutations",
        "--fixtures-root",
        path.join(getProjectRoot(), "test", "fixtures"),
        "--fixture",
        "esri-demo-feature-table-relates-app",
        "--output-dir",
        outputDir,
        "--skip-import",
        "--skip-reconcile",
        "--report",
        reportPath,
      ],
      getProjectRoot(),
    );

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("demoStage=import skipped=yes");
    expect(result.stdout).toContain("demoStage=codemod");
    expect(result.stdout).toContain("demoStage=reconcile skipped=yes");
    expect(result.stdout).toContain("demoPassed=yes");
    expect(result.stdout).toContain(`reportWritten=${reportPath}`);

    const report = JSON.parse(fs.readFileSync(reportPath, "utf8")) as {
      passed: boolean;
      import?: unknown;
      reconciliation?: unknown;
      migration: {
        readiness: string;
      };
      workingAppDir: string;
    };

    expect(report.passed).toBe(true);
    expect(report.import).toBeUndefined();
    expect(report.reconciliation).toBeUndefined();
    expect(report.migration.readiness).toBe("ready");
    expect(fs.existsSync(path.join(report.workingAppDir, "src", "main.js"))).toBe(true);
  });

  it(
    "refuses demo mutation without acknowledgement and does not disclose credentials",
    { timeout: 60_000 },
    async () => {
      ensureBuiltCliArtifacts();
      const root = makeTempDir();
      const outputDir = path.join(root, "unacknowledged-output");
      const secret = "never-print-this-demo-key";

      const result = await runCli(
        [
          "demo",
          "--fixtures-root",
          path.join(getProjectRoot(), "test", "fixtures"),
          "--fixture",
          "esri-demo-feature-table-relates-app",
          "--output-dir",
          outputDir,
          "--admin-api-key",
          secret,
          "--skip-import",
          "--skip-reconcile",
        ],
        getProjectRoot(),
      );

      expect(result.status).toBe(1);
      expect(result.stderr).toContain("--acknowledge-mutations");
      expect(`${result.stdout}\n${result.stderr}`).not.toContain(secret);
      expect(fs.existsSync(outputDir)).toBe(false);
    },
  );

  it("does not expose remote import error bodies in CLI stderr", { timeout: 60_000 }, async () => {
    ensureBuiltCliArtifacts();
    const root = makeTempDir();
    const result = await runCli(
      [
        "demo",
        "--acknowledge-mutations",
        "--fixtures-root",
        path.join(getProjectRoot(), "test", "fixtures"),
        "--fixture",
        "esri-demo-feature-table-relates-app",
        "--output-dir",
        path.join(root, "output"),
        "--admin-base-url",
        adminBaseUrl,
        "--source-service-url",
        "https://arcgis.example/rest/services/incidents/FeatureServer/0",
        "--layer-id",
        "0",
        "--table-name",
        "incidents",
        "--skip-reconcile",
      ],
      getProjectRoot(),
    );

    expect(result.status).toBe(1);
    expect(result.stderr).toContain("Import request failed with HTTP status 500.");
    for (const secret of remoteSecrets) {
      expect(`${result.stdout}\n${result.stderr}`).not.toContain(secret);
    }
  });
});
