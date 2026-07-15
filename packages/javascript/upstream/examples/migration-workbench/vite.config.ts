import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { Plugin, UserConfig } from "vite";

import { createSampleViteConfig } from "../_kit/vite.config.js";

const exampleRoot = path.dirname(fileURLToPath(import.meta.url));
const generatedTarget = path.join(exampleRoot, "src/generated/migrated-main.js");

const rawGeneratedTargetPlugin: Plugin = {
  name: "honua-migration-workbench-raw-generated-target",
  buildStart() {
    const metadata = fs.lstatSync(generatedTarget);
    if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > 1024 * 1024) {
      throw new Error("migration workbench generated target must be a bounded regular file");
    }
    this.emitFile({
      type: "asset",
      fileName: "artifacts/v1/migrated-main.js",
      source: fs.readFileSync(generatedTarget),
    });
  },
};

const sampleConfig = createSampleViteConfig(import.meta.url, {
  sdkEntrypoints: ["@honua/sdk-js/esri-compat"],
});

export default {
  ...sampleConfig,
  plugins: [...(sampleConfig.plugins ?? []), rawGeneratedTargetPlugin],
  build: {
    ...sampleConfig.build,
    // The committed browser assertions intentionally include public
    // compatibility constructor names. Preserve those names in both source and
    // packed qualification builds.
    minify: false,
  },
} satisfies UserConfig;
