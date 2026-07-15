import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";

const exampleRoot = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(exampleRoot, "../..");

export default defineConfig({
  root: exampleRoot,
  resolve: {
    alias: [
      {
        find: "@honua/sdk-js/esri-compat",
        replacement: path.resolve(repoRoot, "src/esri-compat-entry.ts"),
      },
      {
        find: "@honua/sdk-js",
        replacement: path.resolve(repoRoot, "src/index.ts"),
      },
    ],
  },
  server: {
    host: "127.0.0.1",
    fs: {
      allow: [repoRoot],
    },
  },
  preview: {
    host: "127.0.0.1",
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Slice 1 intentionally records public compatibility constructor names as
    // behavior evidence. Preserve those names in the bundled runtime evidence.
    minify: false,
  },
});
