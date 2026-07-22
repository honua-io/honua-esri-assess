import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const packageRoot = path.resolve(import.meta.dirname, "../..");

describe("standalone package boundary", () => {
  it("does not claim the canonical Python executable name", () => {
    const packageJson = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8")) as {
      bin: Record<string, string>;
      dependencies: Record<string, string>;
    };

    expect(packageJson.bin).toEqual({ "honua-js-migrate": "./dist/migration/cli.js" });
    expect(packageJson.bin).not.toHaveProperty("honua-migrate");
    expect(packageJson.dependencies).toHaveProperty("@honua/sdk");
    expect(packageJson.dependencies).not.toHaveProperty("@honua/sdk-js");
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
