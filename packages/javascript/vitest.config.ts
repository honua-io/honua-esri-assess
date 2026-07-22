import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["upstream/test/migration*.test.ts"],
    exclude: [
      "upstream/test/migration-workbench-artifacts*.test.ts",
      "upstream/test/migration-workbench-vite.test.ts"
    ],
    fileParallelism: false
  }
});
