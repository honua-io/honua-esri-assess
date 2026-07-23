import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { Plugin, UserConfig } from "vite";

import { createSampleViteConfig } from "../_kit/vite.config.js";

const exampleRoot = path.dirname(fileURLToPath(import.meta.url));
const generatedTarget = path.join(exampleRoot, "src/generated/migrated-main.js");
const generatedTargetPublicPath = "/artifacts/v1/migrated-main.js";

function readGeneratedTarget(targetPath: string): Buffer {
  const metadata = fs.lstatSync(targetPath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > 1024 * 1024) {
    throw new Error("migration workbench generated target must be a bounded regular file");
  }
  return fs.readFileSync(targetPath);
}

export function createRawGeneratedTargetPlugin(targetPath = generatedTarget): Plugin {
  let buildMode = false;
  return {
    name: "honua-migration-workbench-raw-generated-target",
    configResolved(config) {
      buildMode = config.command === "build";
    },
    buildStart() {
      if (!buildMode) return;
      this.emitFile({
        type: "asset",
        fileName: generatedTargetPublicPath.slice(1),
        source: readGeneratedTarget(targetPath),
      });
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        let requestUrl: URL;
        try {
          requestUrl = new URL(request.url ?? "/", "http://127.0.0.1");
        } catch {
          next();
          return;
        }
        if (requestUrl.pathname !== generatedTargetPublicPath) {
          next();
          return;
        }
        if (request.method !== "GET" && request.method !== "HEAD") {
          response.writeHead(405, {
            allow: "GET, HEAD",
            "cache-control": "no-store",
            "content-type": "text/plain; charset=utf-8",
            "x-content-type-options": "nosniff",
          });
          response.end("Method not allowed");
          return;
        }

        try {
          const body = readGeneratedTarget(targetPath);
          response.writeHead(200, {
            "cache-control": "no-store",
            "content-length": body.byteLength,
            "content-type": "text/javascript; charset=utf-8",
            "x-content-type-options": "nosniff",
          });
          response.end(request.method === "HEAD" ? undefined : body);
        } catch (error) {
          next(error instanceof Error ? error : new Error(String(error)));
        }
      });
    },
  };
}

const rawGeneratedTargetPlugin = createRawGeneratedTargetPlugin();

const sampleConfig = createSampleViteConfig(import.meta.url, {
  sdkEntrypoints: ["@honua/sdk-js/esri-compat"],
});

const config: UserConfig = {
  ...sampleConfig,
  plugins: [...(sampleConfig.plugins ?? []), rawGeneratedTargetPlugin],
  build: {
    ...sampleConfig.build,
    // The committed browser assertions intentionally include public
    // compatibility constructor names. Preserve those names in both source and
    // packed qualification builds.
    minify: false,
  },
};

export default config;
