import fs from "node:fs";
import http, { type IncomingMessage, type ServerResponse } from "node:http";
import os from "node:os";
import path from "node:path";

import { afterAll, describe, expect, it } from "vitest";

import { createRawGeneratedTargetPlugin } from "../examples/migration-workbench/vite.config.js";

const tempDirs: string[] = [];
type DevMiddleware = (request: IncomingMessage, response: ServerResponse, next: (error?: unknown) => void) => void;

afterAll(() => {
  for (const temporaryRoot of tempDirs) {
    fs.rmSync(temporaryRoot, { recursive: true, force: true });
  }
});

async function startPluginServer(targetPath: string): Promise<{
  readonly url: string;
  close(): Promise<void>;
}> {
  const plugin = createRawGeneratedTargetPlugin(targetPath);
  let middleware: DevMiddleware | undefined;
  const configureServer = plugin.configureServer;
  if (typeof configureServer !== "function") {
    throw new Error("generated target plugin must expose a configureServer hook");
  }
  configureServer.call(
    {} as never,
    {
      middlewares: {
        use(handler: DevMiddleware) {
          middleware = handler;
        },
      },
    } as never,
  );
  const registeredMiddleware = middleware;
  if (!registeredMiddleware) throw new Error("generated target plugin did not register middleware");

  const server = http.createServer((request, response) => {
    registeredMiddleware(request, response, (error?: unknown) => {
      if (error) {
        response.writeHead(500, { "content-type": "text/plain; charset=utf-8" });
        response.end(error instanceof Error ? error.message : String(error));
        return;
      }
      response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      response.end("Not found");
    });
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve();
    });
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("plugin test server did not bind");
  return {
    url: `http://127.0.0.1:${address.port}`,
    close: () =>
      new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      }),
  };
}

describe("migration workbench Vite dev server", () => {
  it("serves the manifest-bound generated target at its public artifact URL", async () => {
    const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), "honua-workbench-vite-"));
    tempDirs.push(temporaryRoot);
    const targetPath = path.join(temporaryRoot, "migrated-main.js");
    const target = "export const migrationProof = true;\n";
    fs.writeFileSync(targetPath, target);
    const server = await startPluginServer(targetPath);

    try {
      const response = await fetch(`${server.url}/artifacts/v1/migrated-main.js?cache-bust=1`);
      expect(response.status).toBe(200);
      expect(response.headers.get("content-type")).toBe("text/javascript; charset=utf-8");
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(await response.text()).toBe(target);

      const head = await fetch(`${server.url}/artifacts/v1/migrated-main.js`, { method: "HEAD" });
      expect(head.status).toBe(200);
      expect(head.headers.get("content-length")).toBe(String(Buffer.byteLength(target)));
      expect(await head.text()).toBe("");

      expect((await fetch(`${server.url}/artifacts/v1/not-an-artifact.js`)).status).toBe(404);
    } finally {
      await server.close();
    }
  });
});
