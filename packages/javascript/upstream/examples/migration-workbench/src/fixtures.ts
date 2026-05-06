import type {
  WorkbenchActionItem,
  WorkbenchArtifact,
  WorkbenchContentItem,
  WorkbenchImportItem,
  WorkbenchMetric,
  WorkbenchReconciliationSummary,
  WorkbenchSourceSummary,
} from "./types.js";

export const WORKBENCH_FIXED_GENERATED_AT = "2026-05-05T18:00:00.000Z";
export const WORKBENCH_FIXTURE_NAME = "esri-demo-feature-table-relates-app";

export const WORKBENCH_SOURCE: WorkbenchSourceSummary = {
  title: "ArcGIS Hydrant Inspection Workbench",
  fixtureName: WORKBENCH_FIXTURE_NAME,
  owner: "City Utilities",
  sourcePortal: "https://org.maps.arcgis.com",
  sourceServiceUrl: "https://org.maps.arcgis.com/arcgis/rest/services/Hydrants/FeatureServer",
  sourceServiceId: "Hydrants",
  targetServiceId: "hydrants_honua",
  layerId: 0,
  appRoot: "test/fixtures/esri-demo-feature-table-relates-app",
  compatibilityProfile: "Honua JS compat + content import MVP",
};

export const WORKBENCH_SCAN_METRICS: readonly WorkbenchMetric[] = [
  { label: "Files scanned", value: "2" },
  { label: "ArcGIS imports", value: "7" },
  { label: "Risk flags", value: "2", tone: "warning" },
];

export const WORKBENCH_CODEMOD_METRICS: readonly WorkbenchMetric[] = [
  { label: "Auto migrated", value: "11", tone: "good" },
  { label: "Manual call sites", value: "2", tone: "warning" },
  { label: "Unhandled modules", value: "0", tone: "good" },
];

export const WORKBENCH_CONTENT_ITEMS: readonly WorkbenchContentItem[] = [
  {
    id: "wm-hydrant-ops",
    title: "Hydrant inspection operations map",
    type: "web-map",
    status: "manual",
    artifactPath: "artifacts/webmaps/hydrant-inspections.honua.json",
    warningCount: 2,
    userMessage:
      "The web map converted, but popup Arcade and action-column behavior need a GIS analyst review before publish.",
  },
  {
    id: "svc-hydrants-0",
    title: "Hydrants layer",
    type: "hosted-feature-layer",
    status: "materialized",
    artifactPath: "artifacts/hosted-layers/hydrants/layer-0.features.geojson",
    featureCount: 128,
    userMessage: "Feature data is exported as a materialized GeoJSON artifact and imported through a Honua Cloud job.",
  },
  {
    id: "scene-cctv",
    title: "CCTV camera scene layer",
    type: "hosted-feature-layer",
    status: "blocked",
    artifactPath: "artifacts/blocked/scene-cctv.json",
    featureCount: 14,
    userMessage:
      "This 3D scene layer is blocked for the first slice; rebuild it as a supported 2D feature layer or defer it.",
  },
];

export const WORKBENCH_IMPORT_ITEMS: readonly WorkbenchImportItem[] = [
  {
    id: "import-hydrants-0",
    title: "Hydrants layer import",
    mode: "demo",
    sourceServiceUrl: WORKBENCH_SOURCE.sourceServiceUrl,
    layerId: 0,
    tableName: "hydrants_layer_0",
    status: "simulated",
    statusLabel: "Demo import completed",
    artifactPath: "artifacts/hosted-layers/hydrants/layer-0.features.geojson",
    jobId: "demo-hydrants-0",
    processedFeatures: 128,
    totalFeatures: 128,
    userMessage: "Demo mode replays the Honua Cloud import result from fixtures; no cloud write was attempted.",
  },
  {
    id: "import-cctv-scene",
    title: "CCTV camera scene layer import",
    mode: "demo",
    sourceServiceUrl: "https://org.maps.arcgis.com/arcgis/rest/services/CCTV/SceneServer",
    layerId: 0,
    tableName: "cctv_scene_layer",
    status: "blocked",
    statusLabel: "Blocked before import",
    artifactPath: "artifacts/blocked/scene-cctv.json",
    processedFeatures: 0,
    totalFeatures: 14,
    userMessage: "The layer is listed in the report as blocked and is not hidden behind a feature-query cache.",
  },
];

export const WORKBENCH_RECONCILIATION: WorkbenchReconciliationSummary = {
  status: "manual",
  countDelta: 0,
  sourceFeatureCount: 128,
  targetFeatureCount: 128,
  missingTargetKeys: [],
  extraTargetKeys: ["honua_import_job_id", "honua_imported_at"],
  userMessage:
    "Feature counts and source attributes reconcile, but the converted web map remains manual because unsupported popup behavior needs review.",
};

export const WORKBENCH_FIXTURE_ACTIONS: readonly WorkbenchActionItem[] = [
  {
    id: "manual-popup-arcade",
    severity: "manual",
    sourceStage: "content",
    title: "Review popup expressions",
    userMessage:
      "The converted web map has Arcade popup logic that Honua can preserve as report context but cannot automatically rewrite.",
    nextStep:
      "Open the converted web map artifact, replace the Arcade expression with supported field formatting, then rerun reconciliation.",
    relatedArtifact: "artifacts/webmaps/hydrant-inspections.honua.json",
  },
  {
    id: "manual-feature-table-actions",
    severity: "manual",
    sourceStage: "codemod",
    title: "Rebuild FeatureTable action callbacks",
    userMessage:
      "FeatureTable action-column callbacks were detected. Honua marks the call site for a developer to reconnect it to the app workspace.",
    nextStep: "Use the migration TODO in the codemod report to wire the action to the linked selection model.",
    relatedArtifact: "reports/codemod-report.json",
  },
  {
    id: "blocked-scene-layer",
    severity: "blocked",
    sourceStage: "content",
    title: "Replace 3D scene layer",
    userMessage:
      "The CCTV scene layer cannot be imported by this workflow because the first slice only materializes 2D feature data artifacts.",
    nextStep: "Export or rebuild the source as a 2D FeatureServer layer before enabling live import.",
    relatedArtifact: "artifacts/blocked/scene-cctv.json",
  },
];

export const WORKBENCH_BASE_ARTIFACTS: readonly WorkbenchArtifact[] = [
  {
    id: "scan-json",
    kind: "scan",
    label: "Scan JSON",
    href: "reports/arcgis-scan.json",
    description: "Raw ArcGIS import inventory and risk flags.",
  },
  {
    id: "codemod-report",
    kind: "codemod",
    label: "Codemod report",
    href: "reports/codemod-report.json",
    description: "Readiness, rewrite metrics, and manual migration TODOs.",
  },
  {
    id: "content-manifest",
    kind: "content",
    label: "Content manifest",
    href: "artifacts/content-export-manifest.json",
    description: "Materialized web map, service metadata, and feature data artifact list.",
  },
  {
    id: "import-report",
    kind: "import",
    label: "Import report",
    href: "reports/content-import-report.json",
    description: "Honua Cloud import job results or deterministic demo replay.",
  },
  {
    id: "reconcile-report",
    kind: "reconciliation",
    label: "Reconciliation report",
    href: "reports/content-reconcile-report.json",
    description: "Feature count, schema, and manual web map parity checks.",
  },
];
