import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  commitStagedOutputDirectory,
  createStagedOutputDirectory,
  discardStagedOutputDirectory,
  writeOutputFilesAtomically,
} from "../src/migration/output-writer.js";

const tempDirs: string[] = [];

function makeTempDir(): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "honua-output-writer-"));
  tempDirs.push(directory);
  return directory;
}

afterEach(() => {
  vi.restoreAllMocks();
  for (const directory of tempDirs.splice(0)) {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

describe("atomic migration output writer", () => {
  it("refuses ordinary collisions before writing any member of an output set", () => {
    const root = makeTempDir();
    const firstPath = path.join(root, "first.json");
    const secondPath = path.join(root, "second.json");
    fs.writeFileSync(secondPath, "original-second\n", "utf8");

    expect(() =>
      writeOutputFilesAtomically([
        { path: firstPath, contents: "new-first\n" },
        { path: secondPath, contents: "new-second\n" },
      ]),
    ).toThrow("--force");

    expect(fs.existsSync(firstPath)).toBe(false);
    expect(fs.readFileSync(secondPath, "utf8")).toBe("original-second\n");
  });

  it("replaces an existing output only when force is explicit", () => {
    const root = makeTempDir();
    const outputPath = path.join(root, "report.json");
    fs.writeFileSync(outputPath, "original\n", "utf8");

    writeOutputFilesAtomically([{ path: outputPath, contents: "replacement\n" }], true);

    expect(fs.readFileSync(outputPath, "utf8")).toBe("replacement\n");
  });

  it("restores every prior output when a multi-file commit fails", () => {
    const root = makeTempDir();
    const firstPath = path.join(root, "first.json");
    const secondPath = path.join(root, "second.json");
    fs.writeFileSync(firstPath, "original-first\n", "utf8");
    fs.writeFileSync(secondPath, "original-second\n", "utf8");

    const linkSync = fs.linkSync.bind(fs);
    let linkCount = 0;
    vi.spyOn(fs, "linkSync").mockImplementation((existingPath, newPath) => {
      linkCount += 1;
      if (linkCount === 2) {
        throw new Error("injected link failure");
      }
      linkSync(existingPath, newPath);
    });

    expect(() =>
      writeOutputFilesAtomically(
        [
          { path: firstPath, contents: "new-first\n" },
          { path: secondPath, contents: "new-second\n" },
        ],
        true,
      ),
    ).toThrow("existing outputs were preserved");

    expect(fs.readFileSync(firstPath, "utf8")).toBe("original-first\n");
    expect(fs.readFileSync(secondPath, "utf8")).toBe("original-second\n");
    expect(fs.readdirSync(root).filter((entry) => entry.includes(".honua-"))).toEqual([]);
  });

  it("preserves a directory that appears between preflight and commit", () => {
    const root = makeTempDir();
    const targetPath = path.join(root, "export");
    const stagedPath = createStagedOutputDirectory(targetPath);
    fs.writeFileSync(path.join(stagedPath, "new.json"), "new\n", "utf8");

    const existsSync = fs.existsSync.bind(fs);
    let targetChecks = 0;
    vi.spyOn(fs, "existsSync").mockImplementation((candidate) => {
      if (path.resolve(String(candidate)) === path.resolve(targetPath)) {
        targetChecks += 1;
        if (targetChecks === 2) {
          fs.mkdirSync(targetPath);
          fs.writeFileSync(path.join(targetPath, "competitor.json"), "competitor\n", "utf8");
        }
      }
      return existsSync(candidate);
    });

    expect(() => commitStagedOutputDirectory(stagedPath, targetPath)).toThrow("--force");

    expect(fs.readFileSync(path.join(targetPath, "competitor.json"), "utf8")).toBe("competitor\n");
    expect(fs.readFileSync(path.join(stagedPath, "new.json"), "utf8")).toBe("new\n");
    discardStagedOutputDirectory(stagedPath);
  });
});
