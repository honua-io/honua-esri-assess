export { scanArcGisUsage, summarizeArcGisScan } from "./migration/scanner.js";
export type { ArcGisImportHit, ArcGisScanReport } from "./migration/scanner.js";
export {
  MIGRATION_EVIDENCE_STATES,
  MIGRATION_MANIFEST_ARTIFACT_KIND,
  MIGRATION_MANIFEST_ARTIFACT_VERSION,
  MIGRATION_PARITY_EVIDENCE_ARTIFACT_KIND,
  MIGRATION_PARITY_EVIDENCE_ARTIFACT_VERSION,
  MIGRATION_SOURCE_INVENTORY_ARTIFACT_KIND,
  MIGRATION_SOURCE_INVENTORY_ARTIFACT_VERSION,
} from "./core/types.js";
export type {
  MigrationCompatibilityAssessment,
  MigrationCutoverReadinessItem,
  MigrationCutoverReadinessSummary,
  MigrationEvidenceState,
  MigrationExternalDependency,
  MigrationInventoryAuthPosture,
  MigrationInventoryCodedValue,
  MigrationInventoryCompleteness,
  MigrationInventoryContainer,
  MigrationInventoryField,
  MigrationInventoryResource,
  MigrationInventoryScanRequest,
  MigrationInventorySourceKind,
  MigrationInventoryStyle,
  MigrationInventorySummary,
  MigrationManifestArtifact,
  MigrationManifestReviewItem,
  MigrationManifestStyleAction,
  MigrationManifestSummary,
  MigrationManifestTargetResource,
  MigrationParityEvidenceArtifact,
  MigrationParityEvidenceItem,
  MigrationParityEvidenceSection,
  MigrationReadinessAttestation,
  MigrationReadinessAttestationItem,
  MigrationSourceIdentity,
  MigrationSourceInventoryArtifact,
  MigrationSpatialReferenceInfo,
} from "./core/types.js";
export { runEsriCompatCodemod } from "./migration/codemod.js";
export type {
  CodemodConstructorKind,
  CodemodTarget,
  CodemodFileResult,
  CodemodKindMetrics,
  CodemodMetrics,
  CodemodMetricsByKind,
  EsriCompatCodemodOptions,
  EsriCompatCodemodResult,
  MigrationTodo,
} from "./migration/codemod.js";
export { SUPPORTED_ARCGIS_MODULES } from "./migration/codemod.js";
export { buildJsMigrationReport } from "./migration/report.js";
export type {
  ArcGisModuleSummary,
  ArcGisUsageStyle,
  JsMigrationReport,
  ManualInterventionMetric,
  ManualRewriteMetric,
  MigrationGateResult,
  MigrationReadiness,
  MigrationReasonSummary,
} from "./migration/report.js";
export { evaluateMigrationGates } from "./migration/gating.js";
export type { MigrationGateEvaluation, MigrationGateOptions } from "./migration/gating.js";
export { runLayerReconciliation, summarizeLayerReconciliation } from "./migration/reconcile.js";
export type { LayerReconciliationOptions, LayerReconciliationReport } from "./migration/reconcile.js";
export {
  parseGeoservicesServiceUrl,
  runGeoservicesImportJob,
  runMigrationDemo,
} from "./migration/demo.js";
export type {
  GeoservicesImportJobReport,
  GeoservicesImportStageOptions,
  MigrationDemoOptions,
  MigrationDemoReport,
  ParsedGeoservicesServiceUrl,
} from "./migration/demo.js";
export {
  runContentScan,
  runContentExport,
  runContentImport,
  runContentReconcile,
} from "./migration/content.js";
export type {
  ContentPortalItemSummary,
  ContentScanOptions,
  ContentScanReport,
  ExportedWebMap,
  ExportedHostedLayerEntry,
  ExportedHostedService,
  ContentExportManifest,
  ContentExportOptions,
  ContentExportReport,
  ImportedHostedLayerReport,
  ImportedWebMapReport,
  ContentImportOptions,
  ContentImportReport,
  ReconciledHostedLayerReport,
  ReconciledWebMapReport,
  ContentReconcileOptions,
  ContentReconcileReport,
} from "./migration/content.js";
export {
  analyzeEsriSampleFixture,
  classifyArcGisServiceUrl,
  extractEsriSampleReferences,
  loadEsriSampleCorpusManifest,
  parseEsriSampleCorpusManifest,
  summarizeEsriSampleCorpus,
} from "./migration/sample-corpus.js";
export type {
  ArcGisServiceKind,
  ArcGisServiceReference,
  EsriSampleCorpusGuardrails,
  EsriSampleCorpusLane,
  EsriSampleCorpusManifest,
  EsriSampleCorpusSample,
  EsriSampleCorpusSampleStatus,
  EsriSampleCorpusSchemaVersion,
  EsriSampleCorpusSummary,
  EsriSampleExpectedReferences,
  EsriSampleFixtureAnalysis,
  EsriSampleFixtureReference,
  EsriSampleGuardrailFlag,
  EsriSampleLicenseMetadata,
  EsriSampleReferenceExtraction,
  EsriSampleSkipReason,
  EsriSampleSourceReference,
  EsriSampleTermsMetadata,
  PortalItemReference,
} from "./migration/sample-corpus.js";
export {
  MIGRATION_DEMO_FALLBACK_TARGET,
  MIGRATION_DEMO_ISSUE_NUMBER,
  MIGRATION_DEMO_PRIMARY_TARGET,
  MIGRATION_DEMO_TARGETS,
} from "./migration/demo-targets.js";
export type { MigrationDemoFixtureTarget } from "./migration/demo-targets.js";
export { getJsParityMatrix, JS_PARITY_MATRIX, summarizeJsParityMatrix } from "./migration/parity-matrix.js";
export type {
  JsParityCategory,
  JsParityMatrixEntry,
  JsParityMatrixKind,
  JsParityStatus,
  JsParitySummary,
} from "./migration/parity-matrix.js";
export {
  getJsRuntimeParityMatrix,
  JS_RUNTIME_PARITY_MATRIX,
  summarizeJsRuntimeParity,
} from "./migration/runtime-matrix.js";
export type {
  JsRuntimeParityEntry,
  JsRuntimeParityStatus,
  JsRuntimeParitySurface,
  JsRuntimeParitySummary,
} from "./migration/runtime-matrix.js";
