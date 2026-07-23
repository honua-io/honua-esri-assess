import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";
import { getProjectRoot, withCliLock } from "./migration-cli-lock.js";
import { getPreparedMigrationCliPath } from "./prepared-sdk-artifacts.js";

const tempDirs: string[] = [];

function makeTempDir(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-cli-content-"));
  tempDirs.push(dir);
  return dir;
}

function ensureBuiltCliArtifacts(): void {
  getPreparedMigrationCliPath();
}

function runCli(args: readonly string[], cwd: string): { status: number | null; stdout: string; stderr: string } {
  return withCliLock(() => {
    const cliPath = getPreparedMigrationCliPath();
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

describe("migration cli content-webmap", () => {
  it("converts webmap json and rewrites source urls", () => {
    ensureBuiltCliArtifacts();
    const root = makeTempDir();

    const inputPath = path.join(root, "input-webmap.json");
    const outputPath = path.join(root, "output-webmap.honua.json");
    const reportPath = path.join(root, "output-webmap.report.json");

    fs.writeFileSync(
      inputPath,
      `${JSON.stringify(
        {
          operationalLayers: [
            {
              id: "parcels",
              title: "Parcels",
              layerType: "ArcGISFeatureLayer",
              url: "https://org.maps.arcgis.com/arcgis/rest/services/Parcels/FeatureServer/0",
              layerDefinition: {
                drawingInfo: {
                  renderer: {
                    type: "simple",
                    symbol: {
                      type: "esriSFS",
                      color: [150, 180, 210, 255],
                    },
                  },
                },
              },
            },
          ],
        },
        null,
        2,
      )}\n`,
      "utf8",
    );

    const result = runCli(
      [
        "content-webmap",
        "--input",
        inputPath,
        "--output",
        outputPath,
        "--source-url-prefix",
        "https://org.maps.arcgis.com",
        "--target-url-prefix",
        "https://honua.example.com",
        "--report",
        reportPath,
      ],
      getProjectRoot(),
    );

    expect(result.status).toBe(0);
    expect(result.stdout).toContain("contentWebMap");
    expect(result.stdout).toContain(`outputWritten=${outputPath}`);
    expect(result.stdout).toContain(`reportWritten=${reportPath}`);

    const output = JSON.parse(fs.readFileSync(outputPath, "utf8")) as {
      rewrittenUrlCount: number;
      result: {
        style: {
          sources: Record<string, { url?: string }>;
        };
      };
    };

    expect(output.rewrittenUrlCount).toBe(1);
    expect(output.result.style.sources.parcels?.url).toBe(
      "https://honua.example.com/arcgis/rest/services/Parcels/FeatureServer/0",
    );

    const report = JSON.parse(fs.readFileSync(reportPath, "utf8")) as {
      warningCount: number;
      rewrittenUrlCount: number;
      manualInterventionNeeded: boolean;
      warningCodes: Record<string, number>;
    };

    expect(report.warningCount).toBe(0);
    expect(report.rewrittenUrlCount).toBe(1);
    expect(report.manualInterventionNeeded).toBe(false);
    expect(report.warningCodes).toEqual({});
  }, 30_000);
});
