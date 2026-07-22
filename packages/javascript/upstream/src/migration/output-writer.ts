import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

export interface OutputPlan {
  files?: readonly string[];
  directories?: readonly string[];
  force?: boolean;
}

export interface PreparedOutputPlan {
  files: string[];
  directories: string[];
  force: boolean;
}

export interface OutputFile {
  path: string;
  contents: string | Buffer;
}

interface StagedOutput {
  targetPath: string;
  temporaryPath: string;
  backupPath?: string;
  committed: boolean;
}

export function preflightOutputPlan(plan: OutputPlan): PreparedOutputPlan {
  const force = plan.force === true;
  const files = (plan.files ?? []).map(resolveSafeOutputPath);
  const directories = (plan.directories ?? []).map(resolveSafeOutputPath);
  assertUniqueOutputs([...files, ...directories]);

  for (const filePath of files) {
    assertUsableParent(filePath);
    if (!fs.existsSync(filePath)) {
      continue;
    }
    if (fs.lstatSync(filePath).isDirectory()) {
      throw new Error("An output file path refers to an existing directory.");
    }
    if (!force) {
      throw new Error("An output already exists; rerun with --force to replace it.");
    }
  }

  for (const directoryPath of directories) {
    assertUsableParent(directoryPath);
    if (!fs.existsSync(directoryPath)) {
      continue;
    }
    if (!fs.lstatSync(directoryPath).isDirectory()) {
      throw new Error("An output directory path refers to an existing file.");
    }
    if (!force) {
      throw new Error("An output directory already exists; rerun with --force to reuse it.");
    }
  }

  return { files, directories, force };
}

export function writeOutputFilesAtomically(outputs: readonly OutputFile[], force = false): string[] {
  const prepared = preflightOutputPlan({ files: outputs.map((output) => output.path), force });
  const staged: StagedOutput[] = [];

  try {
    for (const [index, output] of outputs.entries()) {
      const targetPath = prepared.files[index];
      fs.mkdirSync(path.dirname(targetPath), { recursive: true });
      const temporaryPath = siblingTemporaryPath(targetPath, "tmp");
      try {
        const descriptor = fs.openSync(temporaryPath, "wx", 0o666);
        try {
          fs.writeFileSync(descriptor, output.contents);
          fs.fsyncSync(descriptor);
        } finally {
          fs.closeSync(descriptor);
        }
      } catch (error) {
        removeIfPresent(temporaryPath);
        throw error;
      }
      staged.push({ targetPath, temporaryPath, committed: false });
    }

    if (prepared.force) {
      for (const output of staged) {
        if (!fs.existsSync(output.targetPath)) {
          continue;
        }
        output.backupPath = siblingTemporaryPath(output.targetPath, "bak");
        fs.renameSync(output.targetPath, output.backupPath);
      }
    }

    for (const output of staged) {
      fs.linkSync(output.temporaryPath, output.targetPath);
      output.committed = true;
      fs.unlinkSync(output.temporaryPath);
    }

    for (const output of staged) {
      removeIfPresent(output.backupPath);
    }
    return prepared.files;
  } catch (error) {
    rollbackOutputs(staged);
    throw new Error("Output write failed; existing outputs were preserved.", { cause: error });
  } finally {
    for (const output of staged) {
      removeIfPresent(output.temporaryPath);
    }
  }
}

export function createStagedOutputDirectory(targetPath: string, force = false): string {
  const resolvedTarget = preflightOutputPlan({ directories: [targetPath], force }).directories[0];
  fs.mkdirSync(path.dirname(resolvedTarget), { recursive: true });
  return fs.mkdtempSync(path.join(path.dirname(resolvedTarget), `.${path.basename(resolvedTarget)}.honua-stage-`));
}

export function commitStagedOutputDirectory(stagedPath: string, targetPath: string, force = false): string {
  const resolvedTarget = preflightOutputPlan({ directories: [targetPath], force }).directories[0];
  const resolvedStage = path.resolve(stagedPath);
  if (path.dirname(resolvedStage) !== path.dirname(resolvedTarget) || !fs.lstatSync(resolvedStage).isDirectory()) {
    throw new Error("Staged output directories must be valid siblings of their destination.");
  }

  let backupPath: string | undefined;
  if (!force && fs.existsSync(resolvedTarget)) {
    throw new Error("An output directory appeared during commit; rerun with --force to replace it.");
  }
  try {
    if (force && fs.existsSync(resolvedTarget)) {
      backupPath = siblingTemporaryPath(resolvedTarget, "bak");
      fs.renameSync(resolvedTarget, backupPath);
    }
    fs.renameSync(resolvedStage, resolvedTarget);
    removeDirectoryIfPresent(backupPath);
    return resolvedTarget;
  } catch (error) {
    if (!fs.existsSync(resolvedTarget) && backupPath && fs.existsSync(backupPath)) {
      try {
        fs.renameSync(backupPath, resolvedTarget);
      } catch {
        // Preserve the backup when restoration is not possible.
      }
    }
    throw new Error("Output directory commit failed; the previous output was preserved.", { cause: error });
  }
}

export function discardStagedOutputDirectory(stagedPath: string | undefined): void {
  removeDirectoryIfPresent(stagedPath);
}

function resolveSafeOutputPath(value: string): string {
  if (value.includes("\0") || /^[a-z][a-z0-9+.-]*:\/\//i.test(value)) {
    throw new Error("Output destinations must be local filesystem paths, not URLs.");
  }
  return path.resolve(value);
}

function assertUniqueOutputs(outputs: readonly string[]): void {
  const keys = new Set<string>();
  for (const output of outputs) {
    const key = process.platform === "win32" ? output.toLowerCase() : output;
    if (keys.has(key)) {
      throw new Error("The same output destination was requested more than once.");
    }
    keys.add(key);
  }
}

function assertUsableParent(outputPath: string): void {
  let candidate = path.dirname(outputPath);
  for (;;) {
    if (fs.existsSync(candidate)) {
      if (!fs.lstatSync(candidate).isDirectory()) {
        throw new Error("An output parent path refers to an existing file.");
      }
      return;
    }
    const parent = path.dirname(candidate);
    if (parent === candidate) {
      return;
    }
    candidate = parent;
  }
}

function siblingTemporaryPath(targetPath: string, kind: "tmp" | "bak"): string {
  return path.join(path.dirname(targetPath), `.${path.basename(targetPath)}.honua-${randomUUID()}.${kind}`);
}

function rollbackOutputs(outputs: readonly StagedOutput[]): void {
  for (const output of [...outputs].reverse()) {
    if (output.committed) {
      removeIfPresent(output.targetPath);
    }
    if (output.backupPath && fs.existsSync(output.backupPath)) {
      try {
        fs.renameSync(output.backupPath, output.targetPath);
      } catch {
        // Preserve the backup when restoration is not possible; never delete the prior content.
      }
    }
  }
}

function removeIfPresent(filePath: string | undefined): void {
  if (!filePath || !fs.existsSync(filePath)) {
    return;
  }
  try {
    fs.unlinkSync(filePath);
  } catch {
    // Best-effort cleanup must not hide the primary write result.
  }
}

function removeDirectoryIfPresent(directoryPath: string | undefined): void {
  if (!directoryPath || !fs.existsSync(directoryPath)) {
    return;
  }
  try {
    fs.rmSync(directoryPath, { recursive: true, force: true });
  } catch {
    // Best-effort cleanup must not hide the primary write result.
  }
}
