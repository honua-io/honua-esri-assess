import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";
import { getProjectRoot, withCliLock } from "./migration-cli-lock.js";

const tempDirs: string[] = [];
let builtOnce = false;

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-cli-corpus-evidence-"));
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

const fixtureCorpusRoot = path.join(getProjectRoot(), "test", "fixtures", "esri-sample-corpus");
const fixtureManifestPath = path.join(fixtureCorpusRoot, "manifest.json");

interface AggregateEvidence {
  codemodTarget: string;
  manifestPath?: string;
  samples: Array<{
    sampleId: string;
    status: "migrated" | "skipped" | "error";
    codemodTarget: string;
  }>;
  aggregate: {
    sampleCount: number;
    codemodTarget: string;
    statusCounts: { migrated: number; skipped: number; error: number };
    totals: { auto: number; manual: number; unsupported: number };
    manualTodoTotal: number;
    uniqueUnsupportedApis: string[];
  };
}

describe("migration cli corpus-evidence", () => {
  it("writes per-sample and aggregate evidence artifacts for the fixture corpus", () => {
    ensureBuiltCliArtifacts();
    const outRoot = makeTempDir();
    const outDir = path.join(outRoot, "evidence");

    const result = runCli(["corpus-evidence", "--corpus", fixtureCorpusRoot, "--out", outDir], getProjectRoot());

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("corpusEvidence");
    expect(result.stdout).toContain("target=honua-maplibre");
    expect(result.stdout).toContain(`out=${outDir}`);

    const aggregatePath = path.join(outDir, "corpus-evidence.json");
    const samplesDir = path.join(outDir, "samples");
    expect(fs.existsSync(aggregatePath)).toBe(true);
    expect(fs.existsSync(samplesDir)).toBe(true);

    const aggregate = JSON.parse(fs.readFileSync(aggregatePath, "utf8")) as AggregateEvidence;
    expect(aggregate.codemodTarget).toBe("honua-maplibre");
    expect(aggregate.aggregate.codemodTarget).toBe("honua-maplibre");

    const manifest = JSON.parse(fs.readFileSync(fixtureManifestPath, "utf8")) as {
      samples: Array<{ id: string }>;
    };
    expect(aggregate.aggregate.sampleCount).toBe(manifest.samples.length);
    expect(aggregate.samples).toHaveLength(manifest.samples.length);

    const summed =
      aggregate.aggregate.statusCounts.migrated +
      aggregate.aggregate.statusCounts.skipped +
      aggregate.aggregate.statusCounts.error;
    expect(summed).toBe(manifest.samples.length);
    expect(aggregate.aggregate.statusCounts.migrated).toBeGreaterThanOrEqual(1);
    expect(aggregate.aggregate.statusCounts.skipped).toBeGreaterThanOrEqual(2);
    expect(aggregate.aggregate.statusCounts.error).toBe(0);

    for (const sample of manifest.samples) {
      const samplePath = path.join(samplesDir, `${sample.id}.json`);
      expect(fs.existsSync(samplePath)).toBe(true);
      const written = JSON.parse(fs.readFileSync(samplePath, "utf8")) as {
        sampleId: string;
        codemodTarget: string;
      };
      expect(written.sampleId).toBe(sample.id);
      expect(written.codemodTarget).toBe("honua-maplibre");
    }
  }, 240_000);

  it("respects an explicit --target flag in the aggregate output", () => {
    ensureBuiltCliArtifacts();
    const outRoot = makeTempDir();
    const outDir = path.join(outRoot, "evidence");

    const result = runCli(
      ["corpus-evidence", "--corpus", fixtureCorpusRoot, "--out", outDir, "--target", "honua-compat"],
      getProjectRoot(),
    );

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("target=honua-compat");

    const aggregate = JSON.parse(
      fs.readFileSync(path.join(outDir, "corpus-evidence.json"), "utf8"),
    ) as AggregateEvidence;
    expect(aggregate.codemodTarget).toBe("honua-compat");
    expect(aggregate.aggregate.codemodTarget).toBe("honua-compat");
    for (const sample of aggregate.samples) {
      expect(sample.codemodTarget).toBe("honua-compat");
    }
  }, 240_000);

  it("exits non-zero with a clear stderr message when the corpus manifest is missing", () => {
    ensureBuiltCliArtifacts();
    const outRoot = makeTempDir();
    const missingCorpus = path.join(outRoot, "does-not-exist");
    const outDir = path.join(outRoot, "evidence");

    const result = runCli(["corpus-evidence", "--corpus", missingCorpus, "--out", outDir], getProjectRoot());

    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("corpusEvidenceError=");
    expect(result.stderr).toContain("manifest.json");
    expect(fs.existsSync(path.join(outDir, "corpus-evidence.json"))).toBe(false);
  }, 60_000);
});
