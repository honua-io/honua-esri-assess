import path from "node:path";

/** Resolve the package-local CLI built by the test pre-step. */
export function getPreparedMigrationCliPath(): string {
  return path.resolve(import.meta.dirname, "../../dist/migration/cli.js");
}

export function getPreparedEsriCompatEntryPath(): string {
  throw new Error("SDK runtime compatibility tests are outside this package boundary");
}
