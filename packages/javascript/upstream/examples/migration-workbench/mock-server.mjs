import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createFixtureBuildEnvironment } from "../../scripts/lib/fixture-build-environment.mjs";

const exampleRoot = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(exampleRoot, "../..");
const distRoot = path.resolve(exampleRoot, "dist");

const MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".patch": "text/x-diff; charset=utf-8",
  ".svg": "image/svg+xml",
};

function buildDemoIfNeeded() {
  const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
  const result = spawnSync(npmCommand, ["run", "demo:migration-workbench:build", "--silent"], {
    cwd: projectRoot,
    stdio: "inherit",
    env: createFixtureBuildEnvironment(),
  });
  if (result.status !== 0) {
    throw new Error("Failed to build the migration workbench before starting its fixture server.");
  }
}

function boundedStaticFile(pathname) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    return undefined;
  }
  if (decoded.includes("\0")) return undefined;
  const requestedPath = decoded === "/" || !path.extname(decoded) ? "/index.html" : decoded;
  const candidate = path.resolve(distRoot, `.${requestedPath}`);
  if (!candidate.startsWith(`${distRoot}${path.sep}`)) return undefined;
  if (!fs.existsSync(candidate)) return undefined;
  const metadata = fs.lstatSync(candidate);
  if (!metadata.isFile() || metadata.isSymbolicLink()) return undefined;
  const canonicalDistRoot = fs.realpathSync(distRoot);
  const canonicalCandidate = fs.realpathSync(candidate);
  if (!canonicalCandidate.startsWith(`${canonicalDistRoot}${path.sep}`)) return undefined;
  return canonicalCandidate;
}

function serveFile(request, response, filePath) {
  const body = fs.readFileSync(filePath);
  response.writeHead(200, {
    "content-type": MIME_TYPES[path.extname(filePath)] ?? "application/octet-stream",
    "content-length": body.byteLength,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(request.method === "HEAD" ? undefined : body);
}

async function activeConnections(server) {
  return new Promise((resolve, reject) => {
    server.getConnections((error, count) => (error ? reject(error) : resolve(count)));
  });
}

export async function startMigrationWorkbenchFixtureServer({ build = true } = {}) {
  if (build) buildDemoIfNeeded();

  const server = http.createServer((request, response) => {
    if (request.method !== "GET" && request.method !== "HEAD") {
      response.writeHead(405, {
        "content-type": "text/plain; charset=utf-8",
        allow: "GET, HEAD",
        "cache-control": "no-store",
      });
      response.end("Method not allowed");
      return;
    }

    const requestUrl = new URL(request.url ?? "/", "http://127.0.0.1");
    if (requestUrl.pathname === "/favicon.ico") {
      response.writeHead(204, { "cache-control": "no-store" });
      response.end();
      return;
    }

    const staticFile = boundedStaticFile(requestUrl.pathname);
    if (staticFile) {
      serveFile(request, response, staticFile);
      return;
    }

    response.writeHead(404, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
    response.end("Not found");
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });

  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("Failed to bind the migration workbench fixture server.");
  }

  let closePromise;
  return {
    server,
    url: `http://127.0.0.1:${address.port}`,
    async close() {
      closePromise ??= (async () => {
        server.closeIdleConnections?.();
        await new Promise((resolve, reject) => {
          server.close((error) => (error ? reject(error) : resolve()));
        });
        const evidence = {
          closed: true,
          listeningAfterClose: server.listening,
          activeConnectionsAfterClose: await activeConnections(server),
        };
        if (evidence.listeningAfterClose || evidence.activeConnectionsAfterClose !== 0) {
          throw new Error(`Migration workbench fixture did not close cleanly: ${JSON.stringify(evidence)}`);
        }
        return evidence;
      })();
      return closePromise;
    },
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const arguments_ = process.argv.slice(2);
  const evidenceOnce = arguments_.length === 1 && arguments_[0] === "--evidence-once";
  if (arguments_.length > 0 && !evidenceOnce) {
    throw new Error("Unknown migration workbench fixture server argument");
  }

  const { server, url, close } = await startMigrationWorkbenchFixtureServer();
  process.stdout.write(`migrationWorkbenchMockUrl=${url}\n`);

  if (evidenceOnce) {
    let probe;
    let closure;
    try {
      const response = await fetch(url);
      const body = Buffer.from(await response.arrayBuffer());
      probe = {
        method: "GET",
        path: "/",
        status: response.status,
        bodyBytes: body.byteLength,
        bodySha256: createHash("sha256").update(body).digest("hex"),
        contentType: response.headers.get("content-type"),
      };
      if (!response.ok) throw new Error(`Fixture evidence probe failed with HTTP ${response.status}`);
    } finally {
      closure = await close();
    }
    const endpoint = new URL(url);
    process.stdout.write(
      `fixtureEvidence=${JSON.stringify({
        transport: "loopback-http",
        networkScope: "loopback-only",
        host: endpoint.hostname,
        port: Number(endpoint.port),
        ready: true,
        started: true,
        probe,
        ...closure,
      })}\n`,
    );
    process.exit(0);
  }

  const shutdown = async () => {
    await close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}
