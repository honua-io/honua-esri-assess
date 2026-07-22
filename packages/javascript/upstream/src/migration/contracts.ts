/** Versioned migration artifacts owned by the migration package. */
export const MIGRATION_SOURCE_INVENTORY_ARTIFACT_KIND = "honua.migration.source-inventory";
export const MIGRATION_SOURCE_INVENTORY_ARTIFACT_VERSION = "1.0";
export const MIGRATION_MANIFEST_ARTIFACT_KIND = "honua.migration.manifest";
export const MIGRATION_MANIFEST_ARTIFACT_VERSION = "1.0";
export const MIGRATION_PARITY_EVIDENCE_ARTIFACT_KIND = "honua.migration.parity-evidence-pack";
export const MIGRATION_PARITY_EVIDENCE_ARTIFACT_VERSION = "1.0";

export const MIGRATION_EVIDENCE_STATES = {
  pass: "pass",
  fail: "fail",
  unknown: "unknown",
  notApplicable: "not-applicable",
} as const;

export type MigrationEvidenceState = (typeof MIGRATION_EVIDENCE_STATES)[keyof typeof MIGRATION_EVIDENCE_STATES];

export type MigrationInventorySourceKind =
  | "geoserver"
  | "geoserver-rest"
  | "geoservices"
  | "arcgis-geoservices-rest"
  | (string & {});

export interface MigrationInventoryScanRequest {
  sourceKind: MigrationInventorySourceKind;
  sourceUrl: string;
  username?: string;
  password?: string;
  timeoutSeconds?: number;
  includeStyleContent?: boolean;
  /** Request `/api/v1/admin/import/scan?export=json`; the response is still parsed as JSON. */
  exportJson?: boolean;
  signal?: AbortSignal;
}

export interface MigrationSourceInventoryArtifact {
  artifactKind: typeof MIGRATION_SOURCE_INVENTORY_ARTIFACT_KIND;
  artifactVersion: typeof MIGRATION_SOURCE_INVENTORY_ARTIFACT_VERSION;
  sourceKind: string;
  source: MigrationSourceIdentity;
  authPosture: MigrationInventoryAuthPosture;
  scanCompleteness: MigrationInventoryCompleteness;
  summary: MigrationInventorySummary;
  overallCompatibility: MigrationCompatibilityAssessment;
  containers: MigrationInventoryContainer[];
  resources: MigrationInventoryResource[];
  styles: MigrationInventoryStyle[];
  externalDependencies: MigrationExternalDependency[];
}

export interface MigrationSourceIdentity {
  displayName: string;
  baseUrl: string;
  product?: string;
  version?: string;
  build?: string;
  serviceType?: string;
}

export interface MigrationInventoryAuthPosture {
  mode: string;
  credentialsSupplied: boolean;
  accessConfirmed: boolean;
  notes: string[];
}

export interface MigrationInventoryCompleteness {
  /** `200 OK` can still carry `status: "failed"`; use this value as the planning gate. */
  status: "complete" | "partial" | "failed" | (string & {});
  warnings: string[];
  missingArtifacts: string[];
}

export interface MigrationInventorySummary {
  containerCount: number;
  resourceCount: number;
  styleCount: number;
  externalDependencyCount: number;
  compatibleCount: number;
  partiallyCompatibleCount: number;
  incompatibleCount: number;
}

export interface MigrationCompatibilityAssessment {
  level: "compatible" | "partial" | "incompatible" | (string & {});
  code?: string;
  reason: string;
  warnings: string[];
  manualSteps: string[];
}

export interface MigrationInventoryContainer {
  id: string;
  kind: string;
  name: string;
  title?: string;
  description?: string;
  isDefault?: boolean;
  compatibility: MigrationCompatibilityAssessment;
}

export interface MigrationInventoryResource {
  id: string;
  containerId: string;
  kind: string;
  name: string;
  title?: string;
  description?: string;
  geometryType?: string;
  featureCount?: number;
  hasAttachments?: boolean;
  capabilities: string[];
  spatialReferences: MigrationSpatialReferenceInfo[];
  fields: MigrationInventoryField[];
  styleIds: string[];
  externalDependencyIds: string[];
  compatibility: MigrationCompatibilityAssessment;
}

export interface MigrationInventoryField {
  name: string;
  alias?: string;
  fieldType: string;
  nullable?: boolean;
  domainType?: string;
  domainName?: string;
  domainValues?: MigrationInventoryCodedValue[];
}

export interface MigrationInventoryCodedValue {
  code: string;
  name: string;
}

export interface MigrationInventoryStyle {
  id: string;
  containerId: string;
  kind: string;
  name: string;
  format?: string;
  resourceIds: string[];
  externalDependencyIds: string[];
  metadata: Record<string, string>;
  compatibility: MigrationCompatibilityAssessment;
}

export interface MigrationExternalDependency {
  id: string;
  containerId: string;
  resourceId?: string;
  kind: string;
  name: string;
  dependencyType?: string;
  address?: string;
  metadata: Record<string, string>;
  spatialReferences: MigrationSpatialReferenceInfo[];
  compatibility: MigrationCompatibilityAssessment;
}

export interface MigrationSpatialReferenceInfo {
  role: string;
  sourceValue?: string;
  srid?: number;
  crsUri?: string;
  datum?: string;
  unit?: string;
  axisOrder?: string;
  isGeographic?: boolean;
}

export interface MigrationManifestArtifact {
  artifactKind: typeof MIGRATION_MANIFEST_ARTIFACT_KIND;
  artifactVersion: typeof MIGRATION_MANIFEST_ARTIFACT_VERSION;
  sourceArtifactKind: typeof MIGRATION_SOURCE_INVENTORY_ARTIFACT_KIND;
  sourceArtifactVersion: typeof MIGRATION_SOURCE_INVENTORY_ARTIFACT_VERSION;
  sourceKind: string;
  source: MigrationSourceIdentity;
  summary: MigrationManifestSummary;
  targetResources: MigrationManifestTargetResource[];
  styleActions: MigrationManifestStyleAction[];
  manualReviewItems: MigrationManifestReviewItem[];
  unsupportedItems: MigrationManifestReviewItem[];
}

export interface MigrationManifestSummary {
  sourceResourceCount: number;
  targetResourceCount: number;
  styleActionCount: number;
  manualReviewCount: number;
  unsupportedCount: number;
}

export interface MigrationManifestTargetResource {
  sourceResourceId: string;
  sourceKind: string;
  action: string;
  targetServiceName: string;
  targetResourceName: string;
  geometryType?: string;
  fields: MigrationInventoryField[];
  capabilities: string[];
  spatialReferences: MigrationSpatialReferenceInfo[];
  styleIds: string[];
  externalDependencyIds: string[];
  compatibility: MigrationCompatibilityAssessment;
}

export interface MigrationManifestStyleAction {
  sourceStyleId: string;
  action: string;
  format?: string;
  resourceIds: string[];
  externalDependencyIds: string[];
  compatibility: MigrationCompatibilityAssessment;
}

export interface MigrationManifestReviewItem {
  sourceId: string;
  kind: string;
  code: string;
  severity: string;
  reason: string;
  manualSteps: string[];
  warnings: string[];
}

export interface MigrationParityEvidenceArtifact {
  artifactKind: typeof MIGRATION_PARITY_EVIDENCE_ARTIFACT_KIND;
  artifactVersion: typeof MIGRATION_PARITY_EVIDENCE_ARTIFACT_VERSION;
  sourceKind: string;
  source: MigrationSourceIdentity;
  overallState: MigrationEvidenceState;
  summary: string;
  manifestAvailable: boolean;
  sections: MigrationParityEvidenceSection[];
  cutoverReadiness: MigrationCutoverReadinessSummary;
}

export interface MigrationParityEvidenceSection {
  id: string;
  title: string;
  state: MigrationEvidenceState;
  items: MigrationParityEvidenceItem[];
}

export interface MigrationParityEvidenceItem {
  id: string;
  state: MigrationEvidenceState;
  summary: string;
  evidence: string[];
  remediation: string[];
  relatedIds: string[];
}

export interface MigrationCutoverReadinessSummary {
  state: MigrationEvidenceState;
  items: MigrationCutoverReadinessItem[];
}

export interface MigrationCutoverReadinessItem {
  id: string;
  title: string;
  state: MigrationEvidenceState;
  evidence: string[];
  remediation: string[];
  owner?: string;
}

export interface MigrationReadinessAttestation {
  items: MigrationReadinessAttestationItem[];
}

export interface MigrationReadinessAttestationItem {
  id: string;
  state: MigrationEvidenceState;
  evidence: string[];
  owner?: string;
}
