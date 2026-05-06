import type { MigrationWorkbenchConfig, WorkbenchMode } from "./types.js";

function readEnv(name: string): string | undefined {
  const value = import.meta.env[name];
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : undefined;
}

function readBool(name: string): boolean {
  const value = readEnv(name);
  return value === "1" || value === "true" || value === "yes";
}

function readNumber(name: string): number | undefined {
  const value = readEnv(name);
  if (!value) return undefined;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export function loadMigrationWorkbenchConfig(): MigrationWorkbenchConfig {
  const liveImportEnabled = readBool("VITE_HONUA_MIGRATION_WORKBENCH_LIVE_IMPORT");
  const mode: WorkbenchMode = liveImportEnabled ? "live" : "demo";

  return {
    mode,
    fixtureName: readEnv("VITE_HONUA_MIGRATION_WORKBENCH_FIXTURE"),
    generatedAt: readEnv("VITE_HONUA_MIGRATION_WORKBENCH_GENERATED_AT"),
    cloudImport: {
      enabled: liveImportEnabled,
      adminBaseUrl: readEnv("VITE_HONUA_CLOUD_ADMIN_BASE_URL"),
      adminApiKey: readEnv("VITE_HONUA_CLOUD_ADMIN_API_KEY"),
      sourceServiceUrl: readEnv("VITE_ARCGIS_SOURCE_SERVICE_URL"),
      layerId: readNumber("VITE_ARCGIS_SOURCE_LAYER_ID"),
      tableName: readEnv("VITE_HONUA_IMPORT_TABLE_NAME"),
      pollIntervalMs: readNumber("VITE_HONUA_IMPORT_POLL_INTERVAL_MS"),
      timeoutMs: readNumber("VITE_HONUA_IMPORT_TIMEOUT_MS"),
    },
  };
}
