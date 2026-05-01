import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";
import { getProjectRoot, withCliLock } from "./migration-cli-lock.js";

const tempDirs: string[] = [];
let builtOnce = false;

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-cli-demo-"));
  tempDirs.push(dir);
  return dir;
}

function ensureBuiltCliArtifacts(): void {
  withCliLock(() => {
    const cliPath = path.join(getProjectRoot(), "dist", "src", "migration", "cli.js");
    if (builtOnce && fs.existsSync(cliPath)) {
      return;
    }

    const buildResult = spawnSync("npm", ["run", "build", "--silent"], {
      cwd: getProjectRoot(),
      encoding: "utf8",
    });
    if (buildResult.status !== 0) {
      throw new Error(buildResult.stderr || buildResult.stdout || "failed to build migration CLI");
    }
    builtOnce = true;
  });
}

function runCli(args: readonly string[], cwd: string): { status: number | null; stdout: string; stderr: string } {
  return withCliLock(() => {
    const cliPath = path.join(getProjectRoot(), "dist", "src", "migration", "cli.js");
    const result = spawnSync("node", [cliPath, ...args], {
      cwd,
      encoding: "utf8",
    });

    return {
      status: result.status,
      stdout: result.stdout,
      stderr: result.stderr,
    };
  });
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("migration cli demo", () => {
  it("runs codemod-only demo mode and writes report", { timeout: 60_000 }, () => {
    ensureBuiltCliArtifacts();
    const root = makeTempDir();
    const outputDir = path.join(root, "output");
    const reportPath = path.join(root, "demo-report.json");

    const result = runCli(
      [
        "demo",
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
});
