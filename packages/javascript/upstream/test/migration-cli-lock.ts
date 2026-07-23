import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const LOCK_RETRY_MS = 25;
const LOCK_WAIT_TIMEOUT_MS = 15 * 60_000;
const LOCK_OWNER_STALE_MS = 30 * 60_000;
const UNKNOWN_OWNER_STALE_MS = 5 * 60_000;

interface LockOwner {
  pid: number;
  acquiredAt: number;
}

export function getProjectRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
}

export function withCliLock<T>(work: () => T): T {
  const release = acquireCliLockSync();
  try {
    return work();
  } finally {
    release();
  }
}

export async function withCliLockAsync<T>(work: () => Promise<T> | T): Promise<T> {
  const release = await acquireCliLockAsync();
  try {
    return await work();
  } finally {
    release();
  }
}

function acquireCliLockSync(): () => void {
  const lockDir = cliLockDir();
  fs.mkdirSync(path.dirname(lockDir), { recursive: true });
  const startedAt = Date.now();

  for (;;) {
    try {
      fs.mkdirSync(lockDir);
      writeOwner(lockDir);
      return () => fs.rmSync(lockDir, { recursive: true, force: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
        throw error;
      }
      maybeRemoveStaleLock(lockDir);
      if (Date.now() - startedAt > LOCK_WAIT_TIMEOUT_MS) {
        throw new Error(`Timed out waiting for migration CLI lock: ${lockDir}`);
      }
      sleepSync(LOCK_RETRY_MS);
    }
  }
}

async function acquireCliLockAsync(): Promise<() => void> {
  const lockDir = cliLockDir();
  fs.mkdirSync(path.dirname(lockDir), { recursive: true });
  const startedAt = Date.now();

  for (;;) {
    try {
      fs.mkdirSync(lockDir);
      writeOwner(lockDir);
      return () => fs.rmSync(lockDir, { recursive: true, force: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
        throw error;
      }
      maybeRemoveStaleLock(lockDir);
      if (Date.now() - startedAt > LOCK_WAIT_TIMEOUT_MS) {
        throw new Error(`Timed out waiting for migration CLI lock: ${lockDir}`);
      }
      await sleepAsync(LOCK_RETRY_MS);
    }
  }
}

function cliLockDir(): string {
  return path.join(getProjectRoot(), ".tmp", "vitest-cli-lock");
}

function writeOwner(lockDir: string): void {
  const owner: LockOwner = { pid: process.pid, acquiredAt: Date.now() };
  fs.writeFileSync(path.join(lockDir, "owner.json"), `${JSON.stringify(owner)}\n`, "utf8");
}

function maybeRemoveStaleLock(lockDir: string): void {
  if (!isStaleLock(lockDir)) {
    return;
  }
  fs.rmSync(lockDir, { recursive: true, force: true });
}

function isStaleLock(lockDir: string): boolean {
  let stat: fs.Stats;
  try {
    stat = fs.statSync(lockDir);
  } catch {
    return false;
  }

  const owner = readOwner(lockDir);
  const ageMs = Date.now() - (owner?.acquiredAt ?? stat.mtimeMs);
  if (!owner) {
    return ageMs > UNKNOWN_OWNER_STALE_MS;
  }
  if (ageMs > LOCK_OWNER_STALE_MS) {
    return true;
  }
  return !isProcessAlive(owner.pid);
}

function readOwner(lockDir: string): LockOwner | undefined {
  try {
    const parsed = JSON.parse(fs.readFileSync(path.join(lockDir, "owner.json"), "utf8")) as Partial<LockOwner>;
    if (
      typeof parsed.pid === "number" &&
      Number.isInteger(parsed.pid) &&
      parsed.pid > 0 &&
      typeof parsed.acquiredAt === "number" &&
      Number.isFinite(parsed.acquiredAt)
    ) {
      return { pid: parsed.pid, acquiredAt: parsed.acquiredAt };
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}

function sleepSync(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

async function sleepAsync(ms: number): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
}
