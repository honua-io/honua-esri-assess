import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import dgram from "node:dgram";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { afterAll, describe, expect, it } from "vitest";

import {
  buildMigrationWorkbenchArtifacts,
  captureRegularTree,
  compareUtf8,
  defaultRepositoryRoot,
  digestTreeSnapshot,
  executeIsolatedGeneratedModule,
  materializeArtifactSet,
  materializeMigrationWorkbenchArtifacts,
  regularTreeSnapshotsEqual,
  runBoundedCommand,
} from "../scripts/lib/migration-workbench-artifacts.mjs";
import { prepareSdkArtifact } from "../scripts/lib/prepared-sdk-artifact.mjs";

const repositoryRoot = defaultRepositoryRoot();
const tempDirs: string[] = [];
const artifactPaths = [
  "examples/migration-workbench/public/artifacts/v1/manifest.v1.json",
  "examples/migration-workbench/public/artifacts/v1/migration-report.v1.json",
  "examples/migration-workbench/public/artifacts/v1/widget-readiness.v1.json",
  "examples/migration-workbench/public/artifacts/v1/maplibre-assessment.v1.json",
  "examples/migration-workbench/public/artifacts/v1/migration.v1.patch",
  "examples/migration-workbench/src/generated/migrated-main.js",
].sort(compareUtf8);

function makeTempDir(label: string, parent = os.tmpdir()): string {
  fs.mkdirSync(parent, { recursive: true });
  const temporaryRoot = fs.mkdtempSync(path.join(parent, `${label}-`));
  tempDirs.push(temporaryRoot);
  return temporaryRoot;
}

function copyIntoFakeRepository(fakeRoot: string, repositoryPath: string): void {
  const sourcePath = path.join(repositoryRoot, repositoryPath);
  const destinationPath = path.join(fakeRoot, repositoryPath);
  fs.mkdirSync(path.dirname(destinationPath), { recursive: true });
  const sourceStat = fs.lstatSync(sourcePath);
  fs.cpSync(sourcePath, destinationPath, {
    recursive: sourceStat.isDirectory(),
    dereference: false,
    verbatimSymlinks: true,
  });
}

function makeFakeRepository(): string {
  const parent = path.join(repositoryRoot, ".tmp");
  const fakeRoot = makeTempDir("migration-workbench-security-repo", parent);
  for (const repositoryPath of [
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "vitest.config.ts",
    ".nvmrc",
    "LICENSE",
    "dist",
    "examples/arcgis-source-app",
    "examples/migration-workbench/fixtures/expected-behavior.v1.json",
    "scripts/generate-migration-workbench-artifacts.mjs",
    "scripts/lib/migration-workbench-artifacts.mjs",
    "scripts/lib/migration-workbench-execution-runner.mjs",
    "scripts/lib/migration-workbench-network-guard.mjs",
    "scripts/lib/prepared-sdk-artifact.mjs",
  ]) {
    copyIntoFakeRepository(fakeRoot, repositoryPath);
  }
  for (const repositoryPath of ["src", "test", "bench", "config"]) {
    fs.mkdirSync(path.join(fakeRoot, repositoryPath));
  }
  prepareSdkArtifact({ projectRoot: fakeRoot, mode: "capture" });
  const sourceNodeModules = path.join(repositoryRoot, "node_modules");
  const fakeNodeModules = path.join(fakeRoot, "node_modules");
  fs.mkdirSync(fakeNodeModules);
  for (const name of fs.readdirSync(sourceNodeModules).sort(compareUtf8)) {
    const sourcePath = path.join(sourceNodeModules, name);
    const stat = fs.lstatSync(sourcePath);
    fs.symlinkSync(sourcePath, path.join(fakeNodeModules, name), stat.isDirectory() ? "dir" : "file");
  }
  return fakeRoot;
}

function readCommittedArtifactSet(): Map<string, Buffer> {
  return new Map(
    artifactPaths.map((repositoryPath) => [repositoryPath, fs.readFileSync(path.join(repositoryRoot, repositoryPath))]),
  );
}

function runGenerator(fakeRoot: string, mode: "--write" | "--check", environment = process.env) {
  const result = spawnSync(process.execPath, ["scripts/generate-migration-workbench-artifacts.mjs", mode], {
    cwd: fakeRoot,
    encoding: "utf8",
    env: environment,
    shell: false,
    timeout: 60_000,
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.error) {
    throw result.error;
  }
  return result;
}

function legacyAmbiguousTreeHash(rootPath: string): string {
  const digest = createHash("sha256");
  const names = fs.readdirSync(rootPath).sort(compareUtf8);
  for (const name of names) {
    const filePath = path.join(rootPath, name);
    const stat = fs.lstatSync(filePath);
    digest.update(name);
    digest.update("\0");
    digest.update("file");
    digest.update("\0");
    digest.update(String((stat.mode & 0o111) !== 0));
    digest.update("\0");
    digest.update(fs.readFileSync(filePath));
    digest.update("\0");
  }
  return digest.digest("hex");
}

function expectGeneratorFailure(result: ReturnType<typeof runGenerator>, pattern: RegExp): void {
  expect(result.status).not.toBe(0);
  expect(`${result.stdout}\n${result.stderr}`).toMatch(pattern);
}

function expectGeneratorSuccess(result: ReturnType<typeof runGenerator>): void {
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

async function startUdpCounter(counterPath: string): Promise<{ child: ReturnType<typeof spawn>; port: number }> {
  const listenerSource = `
    import dgram from "node:dgram";
    import fs from "node:fs";
    const counterPath = process.argv[1];
    let count = 0;
    const server = dgram.createSocket("udp4");
    server.on("message", () => fs.writeFileSync(counterPath, String(++count)));
    server.bind(0, "127.0.0.1", () => process.stdout.write(String(server.address().port) + "\\n"));
  `;
  const child = spawn(process.execPath, ["--input-type=module", "-e", listenerSource, counterPath], {
    stdio: ["ignore", "pipe", "pipe"],
  });
  const port = await new Promise<number>((resolve, reject) => {
    let stdout = "";
    let stderr = "";
    const timeout = setTimeout(() => reject(new Error(`UDP listener did not become ready: ${stderr}`)), 5_000);
    child.stderr?.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.stdout?.on("data", (chunk) => {
      stdout += String(chunk);
      const newline = stdout.indexOf("\n");
      if (newline >= 0) {
        clearTimeout(timeout);
        resolve(Number.parseInt(stdout.slice(0, newline), 10));
      }
    });
    child.once("error", (error) => {
      clearTimeout(timeout);
      reject(error);
    });
    child.once("exit", (code) => {
      if (!stdout.includes("\n")) {
        clearTimeout(timeout);
        reject(new Error(`UDP listener exited early with code ${code}: ${stderr}`));
      }
    });
  });
  return { child, port };
}

async function sendUdpControl(port: number): Promise<void> {
  const socket = dgram.createSocket("udp4");
  try {
    await new Promise<void>((resolve, reject) => {
      socket.send(Buffer.from("control"), port, "127.0.0.1", (error) => (error ? reject(error) : resolve()));
    });
  } finally {
    socket.close();
  }
}

async function waitForCounter(counterPath: string, expected: number): Promise<void> {
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    const count = fs.existsSync(counterPath) ? Number.parseInt(fs.readFileSync(counterPath, "utf8"), 10) : 0;
    if (count === expected) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`UDP counter did not reach ${expected}.`);
}

afterAll(() => {
  for (const temporaryRoot of [...tempDirs].reverse()) {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

describe("migration workbench artifact hardening", () => {
  it("uses unambiguous length-framed tree records plus direct byte equality", () => {
    const firstTree = makeTempDir("migration-tree-collision-a");
    const secondTree = makeTempDir("migration-tree-collision-b");
    fs.writeFileSync(path.join(firstTree, "a"), Buffer.from("X\0b\0file\0false\0Y", "utf8"));
    fs.writeFileSync(path.join(secondTree, "a"), Buffer.from("X", "utf8"));
    fs.writeFileSync(path.join(secondTree, "b"), Buffer.from("Y", "utf8"));

    expect(legacyAmbiguousTreeHash(firstTree)).toBe(legacyAmbiguousTreeHash(secondTree));
    const firstSnapshot = captureRegularTree(firstTree);
    const secondSnapshot = captureRegularTree(secondTree);
    expect(digestTreeSnapshot(firstSnapshot)).not.toBe(digestTreeSnapshot(secondSnapshot));
    expect(regularTreeSnapshotsEqual(firstSnapshot, secondSnapshot)).toBe(false);
  });

  it("orders tree and artifact paths by UTF-8 bytes without locale state", () => {
    const tree = makeTempDir("migration-tree-ordering");
    const names = ["z", "?", "a", "Z", "?", "e?"];
    for (const name of names) {
      fs.writeFileSync(path.join(tree, name), name);
    }
    const expected = [...names].sort((left, right) => Buffer.compare(Buffer.from(left), Buffer.from(right)));
    expect(captureRegularTree(tree).map((entry) => entry.relativePath)).toEqual(expected);
    expect([...artifactPaths].sort(compareUtf8)).toEqual(artifactPaths);
  });

  it("is byte-identical under hostile Git environment and global configuration", async () => {
    const baseline = await buildMigrationWorkbenchArtifacts({
      repositoryRoot,
      temporaryRoot: makeTempDir("migration-hermetic-baseline"),
    });
    const hostileHome = makeTempDir("migration-hostile-git-home");
    fs.writeFileSync(
      path.join(hostileHome, ".gitconfig"),
      "[diff]\n\texternal = /bin/false\n\talgorithm = patience\n[color]\n\tui = always\n[core]\n\tquotePath = false\n",
    );

    const hostileKeys = [
      "HOME",
      "XDG_CONFIG_HOME",
      "GIT_CONFIG_COUNT",
      "GIT_CONFIG_KEY_0",
      "GIT_CONFIG_VALUE_0",
      "GIT_EXTERNAL_DIFF",
    ] as const;
    const previous = new Map(hostileKeys.map((key) => [key, process.env[key]]));
    try {
      process.env.HOME = hostileHome;
      process.env.XDG_CONFIG_HOME = hostileHome;
      process.env.GIT_CONFIG_COUNT = "1";
      process.env.GIT_CONFIG_KEY_0 = "diff.algorithm";
      process.env.GIT_CONFIG_VALUE_0 = "histogram";
      process.env.GIT_EXTERNAL_DIFF = "/bin/false";
      const hostile = await buildMigrationWorkbenchArtifacts({
        repositoryRoot,
        temporaryRoot: makeTempDir("migration-hermetic-hostile"),
      });
      for (const [repositoryPath, baselineBytes] of baseline.artifacts) {
        expect(hostile.artifacts.get(repositoryPath)?.equals(baselineBytes), repositoryPath).toBe(true);
      }

      const report = JSON.parse(
        hostile.artifacts
          .get("examples/migration-workbench/public/artifacts/v1/migration-report.v1.json")
          ?.toString("utf8") ?? "{}",
      ) as { patchProof?: { command?: { argv?: string[] } } };
      expect(report.patchProof?.command?.argv).toEqual(
        expect.arrayContaining([
          "color.ui=false",
          "core.quotePath=true",
          "diff.algorithm=myers",
          "diff.indentHeuristic=false",
          "--unified=3",
          "--inter-hunk-context=0",
          "--diff-algorithm=myers",
          "--no-color",
        ]),
      );
    } finally {
      for (const key of hostileKeys) {
        const value = previous.get(key);
        if (value === undefined) {
          delete process.env[key];
        } else {
          process.env[key] = value;
        }
      }
    }
  }, 60_000);

  it("locks every callback and promise Resolver method before any DNS packet can escape", async () => {
    const listenerRoot = makeTempDir("migration-dns-listener");
    const counterPath = path.join(listenerRoot, "packets.txt");
    const listener = await startUdpCounter(counterPath);
    try {
      await sendUdpControl(listener.port);
      await waitForCounter(counterPath, 1);

      const guardUrl = pathToFileURL(
        path.join(repositoryRoot, "scripts/lib/migration-workbench-network-guard.mjs"),
      ).href;
      const probeSource = `
        import dns from "node:dns";
        import dnsPromises from "node:dns/promises";
        const callbackResolver = new dns.Resolver();
        const promiseResolver = new dnsPromises.Resolver();
        callbackResolver.setServers(["127.0.0.1:${listener.port}"]);
        promiseResolver.setServers(["127.0.0.1:${listener.port}"]);
        function methodNames(instance) {
          const names = [];
          let prototype = Object.getPrototypeOf(instance);
          while (prototype && prototype !== Object.prototype) {
            for (const name of Reflect.ownKeys(prototype)) {
              const descriptor = Object.getOwnPropertyDescriptor(prototype, name);
              if (typeof name === "string" && name !== "constructor" && descriptor && typeof descriptor.value === "function") names.push(name);
            }
            prototype = Object.getPrototypeOf(prototype);
          }
          return [...new Set(names)];
        }
        const callbackMethods = methodNames(callbackResolver);
        const promiseMethods = methodNames(promiseResolver);
        const guard = await import(${JSON.stringify(guardUrl)});
        function invokeEvery(instance, names) {
          return Object.fromEntries(names.map((name) => {
            let code = null;
            try { instance[name]("blocked.test", () => {}); } catch (error) { code = error?.code ?? null; }
            return [name, code];
          }));
        }
        const callbackResults = invokeEvery(callbackResolver, callbackMethods);
        const promiseResults = invokeEvery(promiseResolver, promiseMethods);
        process.stdout.write(JSON.stringify({
          callbackMethods,
          promiseMethods,
          callbackResults,
          promiseResults,
          attempts: guard.snapshotDeniedNetworkAttempts(),
        }));
      `;
      const result = runBoundedCommand(process.execPath, ["--input-type=module", "-e", probeSource], {
        cwd: repositoryRoot,
        env: process.env,
        label: "DNS Resolver guard probe",
        timeoutMs: 10_000,
      });
      const probe = JSON.parse(String(result.stdout)) as {
        callbackMethods: string[];
        promiseMethods: string[];
        callbackResults: Record<string, string | null>;
        promiseResults: Record<string, string | null>;
        attempts: string[];
      };
      expect(probe.callbackMethods).toEqual(
        expect.arrayContaining(["resolveAny", "resolveMx", "setServers", "cancel"]),
      );
      expect(probe.promiseMethods).toEqual(expect.arrayContaining(["resolveAny", "resolveMx", "setServers", "cancel"]));
      expect(Object.values(probe.callbackResults).every((code) => code === "HONUA_NETWORK_DENIED")).toBe(true);
      expect(Object.values(probe.promiseResults).every((code) => code === "HONUA_NETWORK_DENIED")).toBe(true);
      expect(probe.attempts).toEqual(
        expect.arrayContaining(["dns.Resolver.resolveAny", "dns.promises.Resolver.resolveAny"]),
      );

      await new Promise((resolve) => setTimeout(resolve, 250));
      expect(Number.parseInt(fs.readFileSync(counterPath, "utf8"), 10)).toBe(1);
    } finally {
      listener.child.kill("SIGTERM");
    }
  }, 30_000);

  it("isolates environment, reads, writes, child processes, workers, network, and hangs", () => {
    const outsideRoot = makeTempDir("migration-isolation-outside");
    const sentinelPath = path.join(outsideRoot, "sentinel.txt");
    const escapedWritePath = path.join(outsideRoot, "escaped-write.txt");
    fs.writeFileSync(sentinelPath, "outside-sentinel");
    const secret = `secret-${Date.now()}-${Math.random()}`;
    const previousSecret = process.env.HONUA_MIGRATION_TEST_SECRET;
    process.env.HONUA_MIGRATION_TEST_SECRET = secret;
    try {
      const probeSource = `
        import fs from "node:fs";
        import { spawnSync } from "node:child_process";
        import { Worker } from "node:worker_threads";
        const result = {
          envSecret: process.env.HONUA_MIGRATION_TEST_SECRET ?? null,
          protocolInput: fs.readFileSync(0, "utf8") || null,
        };
        try { fs.readFileSync(${JSON.stringify(sentinelPath)}, "utf8"); result.readDenied = false; }
        catch (error) { result.readDenied = error?.code === "ERR_ACCESS_DENIED"; }
        try { fs.writeFileSync(${JSON.stringify(escapedWritePath)}, "escaped"); result.writeDenied = false; }
        catch (error) { result.writeDenied = error?.code === "ERR_ACCESS_DENIED"; }
        try { spawnSync(process.execPath, ["--version"]); result.childDenied = false; }
        catch (error) { result.childDenied = error?.code === "ERR_ACCESS_DENIED"; }
        try { const worker = new Worker("", { eval: true }); await worker.terminate(); result.workerDenied = false; }
        catch (error) { result.workerDenied = error?.code === "ERR_ACCESS_DENIED"; }
        export default result;
      `;
      const probe = executeIsolatedGeneratedModule({
        repositoryRoot,
        generatedTargetBytes: Buffer.from(probeSource, "utf8"),
      });
      expect(probe.value).toEqual({
        envSecret: null,
        protocolInput: null,
        readDenied: true,
        writeDenied: true,
        childDenied: true,
        workerDenied: true,
      });
      expect(fs.readFileSync(sentinelPath, "utf8")).toBe("outside-sentinel");
      expect(fs.existsSync(escapedWritePath)).toBe(false);

      const networkProbe = Buffer.from(
        `let denied = false; try { await fetch("http://127.0.0.1:9/"); } catch { denied = true; } export default { denied };`,
        "utf8",
      );
      let networkError = "";
      try {
        executeIsolatedGeneratedModule({ repositoryRoot, generatedTargetBytes: networkProbe });
      } catch (error) {
        networkError = error instanceof Error ? error.message : String(error);
      }
      expect(networkError).toMatch(/denied network operation/i);
      expect(networkError).not.toContain(secret);

      const spoofedEnvelope = Buffer.from(
        `import fs from "node:fs"; fs.writeSync(1, JSON.stringify({ protocol: "honua.migration-workbench.runner.v1", nonce: "${"0".repeat(
          64,
        )}", value: { spoofed: true }, networkAttempts: [] })); process.exit(0);`,
        "utf8",
      );
      expect(() => executeIsolatedGeneratedModule({ repositoryRoot, generatedTargetBytes: spoofedEnvelope })).toThrow(
        /invalid result envelope/i,
      );

      const intrinsicForgeryTarget = Buffer.from(
        `
          import fs from "node:fs";
          const nativeStringify = JSON.stringify.bind(JSON);
          const forgedValue = { trusted: "forged" };
          JSON.stringify = (value) => nativeStringify(value?.nonce
            ? { protocol: value.protocol, nonce: value.nonce, value: forgedValue, networkAttempts: [] }
            : forgedValue);
          JSON.parse = () => forgedValue;
          Object.prototype.toJSON = () => forgedValue;
          Array.prototype.join = () => "";
          Array.prototype[Symbol.iterator] = function* () { yield "nonce"; };
          Object.freeze = (value) => value;
          process.stdout.write = () => true;
          fs.writeSync = () => 0;
          export default { trusted: "actual" };
        `,
        "utf8",
      );
      const intrinsicForgery = executeIsolatedGeneratedModule({
        repositoryRoot,
        generatedTargetBytes: intrinsicForgeryTarget,
      });
      expect(intrinsicForgery.value).toEqual({ trusted: "actual" });
      expect(intrinsicForgery.value).not.toEqual({ trusted: "forged" });

      const hangingTarget = Buffer.from(
        "setInterval(() => {}, 1000); await new Promise(() => {}); export default {};",
        "utf8",
      );
      expect(() =>
        executeIsolatedGeneratedModule({
          repositoryRoot,
          generatedTargetBytes: hangingTarget,
          timeoutMs: 300,
        }),
      ).toThrow(/timed out after 300ms/i);
    } finally {
      if (previousSecret === undefined) {
        delete process.env.HONUA_MIGRATION_TEST_SECRET;
      } else {
        process.env.HONUA_MIGRATION_TEST_SECRET = previousSecret;
      }
    }
  }, 30_000);

  it("applies staged artifacts transactionally and rolls handled failures back", () => {
    const artifacts = readCommittedArtifactSet();
    const transactionRepository = makeTempDir("migration-transaction-repository");
    const originals = new Map<string, Buffer>();
    for (const repositoryPath of artifactPaths) {
      const outputPath = path.join(transactionRepository, repositoryPath);
      fs.mkdirSync(path.dirname(outputPath), { recursive: true });
      const original = Buffer.from(`original:${repositoryPath}\n`, "utf8");
      fs.writeFileSync(outputPath, original);
      originals.set(repositoryPath, original);
    }
    const retiredPath = path.join(
      transactionRepository,
      "examples/migration-workbench/public/artifacts/v1/retired.v0.json",
    );
    const retiredGeneratedPath = path.join(
      transactionRepository,
      "examples/migration-workbench/src/generated/retired-generated.js",
    );
    fs.writeFileSync(retiredPath, "retired");
    fs.writeFileSync(retiredGeneratedPath, "retired-generated");

    expect(() =>
      materializeArtifactSet({
        mode: "write",
        repositoryRoot: transactionRepository,
        artifacts,
        testHooks: {
          afterReplacement(replacementCount) {
            if (replacementCount === artifactPaths.length + 2) {
              throw new Error("injected replacement failure");
            }
          },
        },
      }),
    ).toThrow(/all handled replacements were rolled back.*injected replacement failure/i);
    for (const [repositoryPath, original] of originals) {
      expect(fs.readFileSync(path.join(transactionRepository, repositoryPath)).equals(original), repositoryPath).toBe(
        true,
      );
    }
    expect(fs.readFileSync(retiredPath, "utf8")).toBe("retired");
    expect(fs.readFileSync(retiredGeneratedPath, "utf8")).toBe("retired-generated");

    materializeArtifactSet({
      mode: "write",
      repositoryRoot: transactionRepository,
      artifacts,
    });
    expect(fs.existsSync(retiredPath)).toBe(false);
    expect(fs.existsSync(retiredGeneratedPath)).toBe(false);
    expect(() =>
      materializeArtifactSet({
        mode: "check",
        repositoryRoot: transactionRepository,
        artifacts,
      }),
    ).not.toThrow();
  }, 60_000);

  it("preserves committed artifacts when transaction cleanup fails after the commit point", () => {
    const artifacts = readCommittedArtifactSet();
    const transactionRepository = makeTempDir("migration-transaction-cleanup-repository");
    for (const repositoryPath of artifactPaths) {
      const outputPath = path.join(transactionRepository, repositoryPath);
      fs.mkdirSync(path.dirname(outputPath), { recursive: true });
      fs.writeFileSync(outputPath, `original:${repositoryPath}\n`);
    }

    expect(() =>
      materializeArtifactSet({
        mode: "write",
        repositoryRoot: transactionRepository,
        artifacts,
        testHooks: {
          beforeCleanup(transactionRoot) {
            fs.rmSync(path.join(transactionRoot, "backups", "artifact-000"), { force: true });
            throw new Error("injected committed cleanup failure");
          },
        },
      }),
    ).toThrow(/committed.*cleanup failed.*preserved.*not rolled back.*injected committed cleanup failure/i);

    for (const [repositoryPath, expectedBytes] of artifacts) {
      expect(
        fs.readFileSync(path.join(transactionRepository, repositoryPath)).equals(expectedBytes),
        repositoryPath,
      ).toBe(true);
    }
  });

  it("reports incomplete recovery and preserves the installed replacement when a required rollback backup is missing", () => {
    const artifacts = readCommittedArtifactSet();
    const transactionRepository = makeTempDir("migration-transaction-missing-backup-repository");
    const originals = new Map<string, Buffer>();
    for (const repositoryPath of artifactPaths) {
      const outputPath = path.join(transactionRepository, repositoryPath);
      fs.mkdirSync(path.dirname(outputPath), { recursive: true });
      const original = Buffer.from(`original:${repositoryPath}\n`, "utf8");
      fs.writeFileSync(outputPath, original);
      originals.set(repositoryPath, original);
    }

    expect(() =>
      materializeArtifactSet({
        mode: "write",
        repositoryRoot: transactionRepository,
        artifacts,
        testHooks: {
          afterReplacement(replacementCount) {
            if (replacementCount !== 2) return;
            const transactionParent = path.join(transactionRepository, ".tmp");
            const transactionName = fs
              .readdirSync(transactionParent)
              .find((name) => name.startsWith("migration-workbench-materialize-"));
            if (!transactionName) throw new Error("transaction root was not created");
            fs.rmSync(path.join(transactionParent, transactionName, "backups", "artifact-000"), { force: true });
            throw new Error("injected rollback with missing backup");
          },
        },
      }),
    ).toThrow(/rollback was incomplete.*required rollback backup is missing.*injected rollback with missing backup/i);

    const firstArtifactPath = artifactPaths[0];
    expect(
      fs.readFileSync(path.join(transactionRepository, firstArtifactPath)).equals(artifacts.get(firstArtifactPath)!),
    ).toBe(true);
    expect(
      fs.readFileSync(path.join(transactionRepository, artifactPaths[1])).equals(originals.get(artifactPaths[1])!),
    ).toBe(true);
  });

  it("uses one immutable source snapshot and rejects live-source or prepared-dist TOCTOU mutation", async () => {
    const fakeRoot = makeFakeRepository();
    const fixtureScenarioPath = path.join(fakeRoot, "examples/arcgis-source-app/src/workbench-scenario.js");
    const fixtureScenarioBytes = fs.readFileSync(fixtureScenarioPath);

    await expect(
      buildMigrationWorkbenchArtifacts({
        repositoryRoot: fakeRoot,
        temporaryRoot: makeTempDir("migration-source-toctou"),
        testHooks: {
          afterCommand(commandId) {
            if (commandId === "honua-compat-demo") fs.appendFileSync(fixtureScenarioPath, "\n// concurrent edit\n");
          },
        },
      }),
    ).rejects.toThrow(/live migration workbench source inputs changed/i);
    fs.writeFileSync(fixtureScenarioPath, fixtureScenarioBytes);

    const cliPath = path.join(fakeRoot, "dist/src/migration/cli.js");
    const cliBytes = fs.readFileSync(cliPath);
    await expect(
      buildMigrationWorkbenchArtifacts({
        repositoryRoot: fakeRoot,
        temporaryRoot: makeTempDir("migration-prepared-dist-toctou"),
        testHooks: {
          afterCommand(commandId) {
            if (commandId === "honua-compat-demo") fs.appendFileSync(cliPath, "\n// concurrent dist edit\n");
          },
        },
      }),
    ).rejects.toThrow(/prepared SDK artifact is stale or incomplete/i);
    fs.writeFileSync(cliPath, cliBytes);

    await materializeMigrationWorkbenchArtifacts({ mode: "write", repositoryRoot: fakeRoot });
    const committed = new Map(
      artifactPaths.map((repositoryPath) => [repositoryPath, fs.readFileSync(path.join(fakeRoot, repositoryPath))]),
    );
    await expect(
      materializeMigrationWorkbenchArtifacts({
        mode: "write",
        repositoryRoot: fakeRoot,
        testHooks: {
          beforePublication() {
            fs.appendFileSync(fixtureScenarioPath, "\n// edit before publication\n");
          },
        },
      }),
    ).rejects.toThrow(/live migration workbench source inputs changed/i);
    for (const [repositoryPath, expectedBytes] of committed) {
      expect(fs.readFileSync(path.join(fakeRoot, repositoryPath)).equals(expectedBytes), repositoryPath).toBe(true);
    }
  }, 120_000);

  it("exercises the real generator CLI for missing, stale, unexpected, symlink, special-file, write, and check states", () => {
    const fakeRoot = makeFakeRepository();
    expectGeneratorSuccess(runGenerator(fakeRoot, "--write"));
    expectGeneratorSuccess(runGenerator(fakeRoot, "--check"));

    const manifestPath = path.join(fakeRoot, artifactPaths[0]);
    const manifestBytes = fs.readFileSync(manifestPath);
    fs.unlinkSync(manifestPath);
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /manifest\.v1\.json is missing/i);
    fs.writeFileSync(manifestPath, manifestBytes);

    fs.appendFileSync(manifestPath, "stale");
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /manifest\.v1\.json differs/i);
    fs.writeFileSync(manifestPath, manifestBytes);

    const retiredPath = path.join(fakeRoot, "examples/migration-workbench/public/artifacts/v1/retired.v0.json");
    fs.writeFileSync(retiredPath, "retired");
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /unexpected retired artifact entry/i);
    expectGeneratorSuccess(runGenerator(fakeRoot, "--write"));
    expect(fs.existsSync(retiredPath)).toBe(false);

    const retiredGeneratedPath = path.join(fakeRoot, "examples/migration-workbench/src/generated/retired-generated.js");
    fs.writeFileSync(retiredGeneratedPath, "retired-generated");
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /unexpected retired artifact entry/i);
    expectGeneratorSuccess(runGenerator(fakeRoot, "--write"));
    expect(fs.existsSync(retiredGeneratedPath)).toBe(false);

    const outsideRoot = makeTempDir("migration-cli-outside");
    const sentinelPath = path.join(outsideRoot, "sentinel.txt");
    fs.writeFileSync(sentinelPath, "do-not-change");
    fs.unlinkSync(manifestPath);
    fs.symlinkSync(sentinelPath, manifestPath, "file");
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /unsafe symbolic link/i);
    expectGeneratorFailure(runGenerator(fakeRoot, "--write"), /unsafe symbolic link/i);
    expect(fs.readFileSync(sentinelPath, "utf8")).toBe("do-not-change");
    fs.unlinkSync(manifestPath);
    fs.writeFileSync(manifestPath, manifestBytes);

    fs.unlinkSync(manifestPath);
    runBoundedCommand("mkfifo", [manifestPath], {
      cwd: fakeRoot,
      label: "create artifact FIFO fixture",
      timeoutMs: 5_000,
    });
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /regular file|special file/i);
    fs.unlinkSync(manifestPath);
    fs.writeFileSync(manifestPath, manifestBytes);

    const generatedDirectory = path.join(fakeRoot, "examples/migration-workbench/src/generated");
    fs.unlinkSync(path.join(generatedDirectory, "migrated-main.js"));
    fs.rmdirSync(generatedDirectory);
    const outsideGenerated = path.join(outsideRoot, "generated");
    fs.mkdirSync(outsideGenerated);
    fs.symlinkSync(outsideGenerated, generatedDirectory, "dir");
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /unsafe symbolic link/i);
    expectGeneratorFailure(runGenerator(fakeRoot, "--write"), /unsafe symbolic link/i);
    expect(fs.existsSync(path.join(outsideGenerated, "migrated-main.js"))).toBe(false);
    expect(fs.readFileSync(sentinelPath, "utf8")).toBe("do-not-change");
  }, 120_000);

  it("rejects required file and directory links without touching outside sentinels", () => {
    const fakeRoot = makeFakeRepository();
    const outsideRoot = makeTempDir("migration-required-input-outside");
    const outsideFile = path.join(outsideRoot, "expected.json");
    fs.writeFileSync(outsideFile, '{"sentinel":"unchanged"}\n');
    const expectedPath = path.join(fakeRoot, "examples/migration-workbench/fixtures/expected-behavior.v1.json");
    fs.unlinkSync(expectedPath);
    fs.symlinkSync(outsideFile, expectedPath, "file");
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /unsafe symbolic link/i);
    expect(fs.readFileSync(outsideFile, "utf8")).toBe('{"sentinel":"unchanged"}\n');

    fs.unlinkSync(expectedPath);
    copyIntoFakeRepository(fakeRoot, "examples/migration-workbench/fixtures/expected-behavior.v1.json");
    const fixturePath = path.join(fakeRoot, "examples/arcgis-source-app");
    fs.rmSync(fixturePath, { recursive: true });
    fs.symlinkSync(outsideRoot, fixturePath, "dir");
    expectGeneratorFailure(runGenerator(fakeRoot, "--check"), /unsafe symbolic link/i);
    expect(fs.readFileSync(outsideFile, "utf8")).toBe('{"sentinel":"unchanged"}\n');
  }, 30_000);

  it("rejects arbitrary materialization paths and explicitly times out blocking children", async () => {
    const generated = await buildMigrationWorkbenchArtifacts({
      repositoryRoot,
      temporaryRoot: makeTempDir("migration-allowlist-build"),
    });
    const targetRoot = makeTempDir("migration-allowlist-target");
    const invalidArtifacts = new Map(generated.artifacts);
    invalidArtifacts.set("../outside.txt", Buffer.from("escape"));
    expect(() =>
      materializeArtifactSet({
        mode: "write",
        repositoryRoot: targetRoot,
        artifacts: invalidArtifacts,
      }),
    ).toThrow(/fixed repository-path allowlist/i);
    expect(fs.existsSync(path.join(path.dirname(targetRoot), "outside.txt"))).toBe(false);

    expect(() =>
      runBoundedCommand(process.execPath, ["-e", "setInterval(() => {}, 1000)"], {
        cwd: targetRoot,
        label: "blocking child regression",
        timeoutMs: 200,
      }),
    ).toThrow(/blocking child regression timed out after 200ms/i);
  }, 30_000);
});
