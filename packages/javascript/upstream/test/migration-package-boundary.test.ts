import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const packageRoot = path.resolve(import.meta.dirname, "../..");

describe("standalone package boundary", () => {
  it("does not claim the canonical Python executable name", () => {
    const packageJson = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8")) as {
      version: string;
      repository: { type: string; url: string; directory: string };
      homepage: string;
      bugs: { url: string };
      engines: { node: string };
      bin: Record<string, string>;
      dependencies: Record<string, string>;
    };

    expect(packageJson.version).toBe("0.1.3-beta.0");
    expect(packageJson.repository).toEqual({
      type: "git",
      url: "git+https://github.com/honua-io/honua-migrate.git",
      directory: "packages/javascript",
    });
    expect(packageJson.homepage).toBe("https://github.com/honua-io/honua-migrate#readme");
    expect(packageJson.bugs).toEqual({ url: "https://github.com/honua-io/honua-migrate/issues" });
    expect(packageJson.engines).toEqual({ node: ">=20.19.0" });
    expect(packageJson.bin).toEqual({ "honua-js-migrate": "./dist/migration/cli.js" });
    expect(packageJson.bin).not.toHaveProperty("honua-migrate");
    expect(packageJson.dependencies).toHaveProperty("@honua/sdk");
    expect(packageJson.dependencies).not.toHaveProperty("@honua/sdk-js");
  });

  it("records the historical source separately from the current release owner", () => {
    const provenance = JSON.parse(fs.readFileSync(path.join(packageRoot, "DEPENDENCY_PROVENANCE.json"), "utf8")) as {
      source: { repository: string };
      currentOwner: {
        repository: string;
        packagePath: string;
        npmPackage: string;
        version: string;
        releaseTag: string;
        nodeEngine: string;
      };
    };

    expect(provenance.source.repository).toBe("https://github.com/honua-io/honua-sdk-js");
    expect(provenance.currentOwner).toEqual({
      repository: "https://github.com/honua-io/honua-migrate",
      packagePath: "packages/javascript",
      npmPackage: "@honua/honua-migrate",
      version: "0.1.3-beta.0",
      releaseTag: "javascript-v0.1.3-beta.0",
      nodeEngine: ">=20.19.0",
    });
  });

  it("owns its artifact contract instead of importing the legacy SDK migration subpath", () => {
    const entrySource = fs.readFileSync(path.join(packageRoot, "upstream", "src", "migration-entry.ts"), "utf8");
    const sourceFiles = fs
      .readdirSync(path.join(packageRoot, "upstream", "src", "migration"))
      .filter((name) => name.endsWith(".ts"))
      .map((name) => fs.readFileSync(path.join(packageRoot, "upstream", "src", "migration", name), "utf8"));

    expect(entrySource).toContain('from "./migration/contracts.js"');
    expect([entrySource, ...sourceFiles].join("\n")).not.toContain('from "@honua/sdk-js/migration"');
  });

  it("builds the real AST codemod and complete migration module set", () => {
    for (const moduleName of ["codemod", "content", "demo", "reconcile", "report", "sample-corpus"]) {
      expect(fs.existsSync(path.join(packageRoot, "dist", "migration", `${moduleName}.js`))).toBe(true);
    }
  });
});
