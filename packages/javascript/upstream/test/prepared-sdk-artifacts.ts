import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

/** Resolve the package-local CLI built by the test pre-step. */
export function getPreparedMigrationCliPath(): string {
  return path.resolve(import.meta.dirname, "../../dist/migration/cli.js");
}

export function getPreparedEsriCompatEntryPath(): string {
  return pathToFileURL(createRequire(import.meta.url).resolve("@honua/sdk-js/esri-compat")).href;
}
