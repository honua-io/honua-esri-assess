import type {
  ArcGisScanReport,
  ContentImportReport,
  ContentReconcileReport,
  GeoservicesImportJobReport,
  JsMigrationReport,
  LayerReconciliationReport,
  MigrationReadiness,
} from "../../../src/migration-entry.js";

export type WorkbenchMode = "demo" | "live";
export type WorkbenchStageId = "scan" | "readiness" | "codemod" | "content" | "import" | "reconciliation" | "report";
export type WorkbenchStageStatus = "complete" | "manual" | "blocked" | "waiting" | "running" | "failed";
export type WorkbenchActionSeverity = "manual" | "blocked" | "warning";
export type WorkbenchArtifactKind = "scan" | "codemod" | "content" | "import" | "reconciliation" | "report";

export interface HonuaCloudImportConfig {
  readonly enabled: boolean;
  readonly adminBaseUrl?: string;
  readonly adminApiKey?: string;
  readonly sourceServiceUrl?: string;
  readonly layerId?: number;
  readonly tableName?: string;
  readonly pollIntervalMs?: number;
  readonly timeoutMs?: number;
}

export interface MigrationWorkbenchConfig {
  readonly mode: WorkbenchMode;
  readonly generatedAt?: string;
  readonly fixtureName?: string;
  readonly cloudImport: HonuaCloudImportConfig;
}

export interface WorkbenchMetric {
  readonly label: string;
  readonly value: string;
  readonly tone?: "neutral" | "good" | "warning" | "danger";
}

export interface WorkbenchArtifact {
  readonly id: string;
  readonly kind: WorkbenchArtifactKind;
  readonly label: string;
  readonly href: string;
  readonly description: string;
}

export interface WorkbenchStage {
  readonly id: WorkbenchStageId;
  readonly title: string;
  readonly status: WorkbenchStageStatus;
  readonly summary: string;
  readonly metrics: readonly WorkbenchMetric[];
  readonly artifacts: readonly WorkbenchArtifact[];
  readonly userMessages: readonly string[];
}

export interface WorkbenchSourceSummary {
  readonly title: string;
  readonly fixtureName: string;
  readonly owner: string;
  readonly sourcePortal: string;
  readonly sourceServiceUrl: string;
  readonly sourceServiceId: string;
  readonly targetServiceId: string;
  readonly layerId: number;
  readonly appRoot: string;
  readonly compatibilityProfile: string;
}

export interface WorkbenchContentItem {
  readonly id: string;
  readonly title: string;
  readonly type: "web-map" | "hosted-feature-layer";
  readonly status: "converted" | "materialized" | "manual" | "blocked";
  readonly artifactPath: string;
  readonly userMessage: string;
  readonly warningCount?: number;
  readonly featureCount?: number;
}

export interface WorkbenchImportItem {
  readonly id: string;
  readonly title: string;
  readonly mode: WorkbenchMode;
  readonly sourceServiceUrl: string;
  readonly layerId: number;
  readonly tableName: string;
  readonly status: "simulated" | "configured" | "running" | "completed" | "failed" | "blocked";
  readonly statusLabel: string;
  readonly artifactPath?: string;
  readonly jobId?: string;
  readonly processedFeatures?: number;
  readonly totalFeatures?: number;
  readonly userMessage: string;
}

export interface WorkbenchReconciliationSummary {
  readonly status: "pass" | "manual" | "fail";
  readonly countDelta: number;
  readonly sourceFeatureCount: number;
  readonly targetFeatureCount: number;
  readonly missingTargetKeys: readonly string[];
  readonly extraTargetKeys: readonly string[];
  readonly userMessage: string;
}

export interface WorkbenchActionItem {
  readonly id: string;
  readonly severity: WorkbenchActionSeverity;
  readonly sourceStage: WorkbenchStageId;
  readonly title: string;
  readonly userMessage: string;
  readonly nextStep: string;
  readonly relatedArtifact?: string;
}

export interface MigrationWorkbenchArtifacts {
  readonly source: WorkbenchSourceSummary;
  readonly scan: ArcGisScanReport;
  readonly migration: JsMigrationReport;
  readonly contentImport: ContentImportReport;
  readonly contentReconcile: ContentReconcileReport;
  readonly layerReconciliation: LayerReconciliationReport;
}

export interface MigrationWorkbenchWorkflow {
  readonly generatedAt: string;
  readonly reportId: string;
  readonly mode: WorkbenchMode;
  readonly fixtureName: string;
  readonly source: WorkbenchSourceSummary;
  readonly cloudImport: HonuaCloudImportConfig;
  readonly readiness: MigrationReadiness;
  readonly stages: readonly WorkbenchStage[];
  readonly actionItems: readonly WorkbenchActionItem[];
  readonly contentItems: readonly WorkbenchContentItem[];
  readonly importItems: readonly WorkbenchImportItem[];
  readonly reconciliation: WorkbenchReconciliationSummary;
  readonly artifacts: readonly WorkbenchArtifact[];
}

export interface MigrationWorkbenchReport {
  readonly schemaVersion: "honua-migration-workbench-report.v1";
  readonly reportId: string;
  readonly generatedAt: string;
  readonly mode: WorkbenchMode;
  readonly fixtureName: string;
  readonly source: WorkbenchSourceSummary;
  readonly summary: {
    readonly readiness: MigrationReadiness;
    readonly stageCount: number;
    readonly manualActionCount: number;
    readonly blockedActionCount: number;
    readonly contentItems: number;
    readonly importItems: number;
    readonly reconciliationStatus: WorkbenchReconciliationSummary["status"];
  };
  readonly stages: readonly WorkbenchStage[];
  readonly actionItems: readonly WorkbenchActionItem[];
  readonly contentItems: readonly WorkbenchContentItem[];
  readonly importItems: readonly WorkbenchImportItem[];
  readonly reconciliation: WorkbenchReconciliationSummary;
  readonly artifacts: readonly WorkbenchArtifact[];
  readonly notes: readonly string[];
}

export interface LiveImportProgress {
  readonly item: WorkbenchImportItem;
  readonly job?: GeoservicesImportJobReport;
}
