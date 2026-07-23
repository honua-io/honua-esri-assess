import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const packageRoot = path.resolve(import.meta.dirname, "../..");

describe("standalone package boundary", () => {
  it("does not claim the canonical Python executable name", () => {
    const packageJson = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8")) as {
      bin: Record<string, string>;
    };

    expect(packageJson.bin).toEqual({ "honua-js-migrate": "./dist/migration/cli.js" });
    expect(packageJson.bin).not.toHaveProperty("honua-migrate");
  });

  it("builds the real AST codemod and complete migration module set", () => {
    for (const moduleName of ["codemod", "content", "demo", "reconcile", "report", "sample-corpus"]) {
      expect(fs.existsSync(path.join(packageRoot, "dist", "migration", `${moduleName}.js`))).toBe(true);
    }
  });
});
