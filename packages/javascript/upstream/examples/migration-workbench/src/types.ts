export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | readonly JsonValue[] | { readonly [key: string]: JsonValue };

export interface ArtifactCommand {
  readonly id: string;
  readonly executable: string;
  readonly argv: readonly string[];
  readonly exitCode: number;
  readonly stdout?: string;
  readonly stderr?: string;
}

export interface ArtifactManifestFile {
  readonly repositoryPath: string;
  readonly mediaType: string;
  readonly bytes: number;
  readonly sha256: string;
}

export interface MigrationWorkbenchManifest {
  readonly schemaVersion: "honua.migration-workbench.manifest.v1";
  readonly artifactSet: string;
  readonly fixture: string;
  readonly provenance: MigrationProvenance;
  readonly commands: readonly ArtifactCommand[];
  readonly files: readonly ArtifactManifestFile[];
}

export interface MigrationProvenance {
  readonly fixture: string;
  readonly scenario: string;
  readonly sourceSnapshot: {
    readonly fixtureTreeSha256: string;
    readonly expectedBehaviorPath: string;
    readonly expectedBehaviorSha256: string;
    readonly combinedSha256: string;
  };
  readonly authorship: string;
  readonly licenseScope: string;
  readonly transformationEngine: {
    readonly path: string;
    readonly preparedArtifactFormat: string;
    readonly buildInputsSha256: string;
    readonly distSrcSha256: string;
  };
  readonly generatedTargetExecution: {
    readonly processBoundary: string;
    readonly permissionModel: string;
    readonly networkGuardScope: string;
    readonly trustBoundary: string;
    readonly guardedNetworkApiAttemptsObserved: number;
    readonly guardedProcessControlAttemptsObserved: number;
    readonly timeoutMs: number;
  };
  readonly sourceUpload: boolean;
  readonly credentialsRequired: boolean;
}

export interface CodemodKindMetric {
  readonly total: number;
  readonly autoMigrated: number;
  readonly manual: number;
}

export interface CodemodMetrics {
  readonly totalCodemodScopedCallSites: number;
  readonly autoMigratedCallSites: number;
  readonly manualCallSites: number;
  readonly byKind: Readonly<Record<string, CodemodKindMetric>>;
}

export interface MigrationGate {
  readonly gate: string;
  readonly passed: boolean;
  readonly detail: string;
}

export interface ManualTodo {
  readonly kind: string;
  readonly file: string;
  readonly line: number;
  readonly column: number;
  readonly reason: string;
  readonly difficulty: string;
}

export interface UnsupportedModule {
  readonly modulePath: string;
  readonly usageStyle: string;
  readonly count: number;
}

export interface MigrationReportBody {
  readonly readiness: string;
  readonly scanReport: {
    readonly rootDir: string;
    readonly filesScanned: number;
    readonly filesWithArcGisImports: number;
    readonly imports: readonly {
      readonly file: string;
      readonly modulePath: string;
      readonly importClause: string;
      readonly symbols: readonly string[];
    }[];
    readonly flags: readonly JsonValue[];
  };
  readonly codemodResult: {
    readonly rootDir: string;
    readonly target: string;
    readonly filesScanned: number;
    readonly filesChanged: number;
    readonly metrics: CodemodMetrics;
  };
  readonly gates: readonly MigrationGate[];
  readonly manualTodos: readonly ManualTodo[];
  readonly unhandledArcGisModules: readonly UnsupportedModule[];
  readonly manualRewriteMetric: {
    readonly numerator: number;
    readonly denominator: number;
    readonly ratio: number;
    readonly scope: string;
  };
  readonly manualInterventionMetric: {
    readonly numerator: number;
    readonly denominator: number;
    readonly ratio: number;
    readonly scope: string;
    readonly manualCodemodCallSites: number;
    readonly unhandledUsageHits: number;
  };
}

export interface BehaviorAssertion {
  readonly path: string;
  readonly expected: JsonValue;
  readonly observed: JsonValue;
  readonly passed: boolean;
}

export interface MigrationWorkbenchReportArtifact {
  readonly schemaVersion: "honua.migration-workbench.report.v1";
  readonly fixture: string;
  readonly target: "honua-compat";
  readonly provenance: MigrationProvenance;
  readonly commands: readonly ArtifactCommand[];
  readonly demo: {
    readonly fixtureName: string;
    readonly generatedAt: string;
    readonly codemodTarget: "honua-compat";
    readonly passed: boolean;
    readonly migration: MigrationReportBody;
  };
  readonly behaviorProof: {
    readonly passed: boolean;
    readonly expectations: JsonValue;
    readonly observations: JsonValue;
    readonly assertions: readonly BehaviorAssertion[];
  };
  readonly patchProof: {
    readonly applyCheckPassed: boolean;
    readonly targetTreeEqual: boolean;
    readonly directEntryComparisonPassed: boolean;
    readonly sourceTreeSha256: string;
    readonly targetTreeSha256: string;
    readonly appliedTreeSha256: string;
  };
}

export interface WidgetReadinessArtifact {
  readonly schemaVersion: "honua.migration-workbench.widget-readiness.v1";
  readonly fixture: string;
  readonly command: ArtifactCommand;
  readonly report: {
    readonly rootDir: string;
    readonly dispositionDataVersion: string;
    readonly deprecationRelease: string;
    readonly removalRelease: string;
    readonly removalTimeframe: string;
    readonly filesScanned: number;
    readonly filesWithWidgetUsage: number;
    readonly widgets: readonly WidgetGuidance[];
    readonly summary: {
      readonly totalSites: number;
      readonly automatedSites: number;
      readonly assistedSites: number;
      readonly manualSites: number;
      readonly automatedWidgets: number;
      readonly assistedWidgets: number;
      readonly manualWidgets: number;
      readonly automatedPct: number;
    };
    readonly summaryLine: string;
  };
}

export interface WidgetGuidance {
  readonly widget: string;
  readonly supportModule: boolean;
  readonly disposition: string;
  readonly bucket: "automated" | "assisted" | "manual";
  readonly target: string;
  readonly guideLink: string;
  readonly count: number;
  readonly sites: readonly {
    readonly file: string;
    readonly line: number;
    readonly modulePath: string;
    readonly importStyle: string;
  }[];
}

export interface MapLibreAssessmentArtifact {
  readonly schemaVersion: "honua.migration-workbench.maplibre-assessment.v1";
  readonly fixture: string;
  readonly command: ArtifactCommand;
  readonly report: MigrationReportBody & { readonly codemodTarget: "honua-maplibre" };
  readonly residuals: {
    readonly errors: readonly JsonValue[];
    readonly manualTodos: readonly ManualTodo[];
    readonly unsupportedModules: readonly UnsupportedModule[];
  };
}

export interface MigrationWorkbenchArtifactSet {
  readonly manifest: MigrationWorkbenchManifest;
  readonly migrationReport: MigrationWorkbenchReportArtifact;
  readonly widgetReadiness: WidgetReadinessArtifact;
  readonly maplibreAssessment: MapLibreAssessmentArtifact;
  readonly diff: string;
}

export type EvidenceTone = "good" | "warning" | "danger" | "neutral";

export interface EvidenceMetric {
  readonly id: string;
  readonly label: string;
  readonly value: number | string;
  readonly tone: EvidenceTone;
  readonly scope: string;
}

export interface AssertionMatrixRow extends BehaviorAssertion {
  readonly browserObserved: JsonValue | undefined;
  readonly browserPassed: boolean;
}

export interface MigrationWorkbenchViewModel {
  readonly fixture: string;
  readonly target: string;
  readonly artifactSet: string;
  readonly generatedAt: string;
  readonly source: {
    readonly path: string;
    readonly authorship: string;
    readonly licenseScope: string;
    readonly sourceUpload: boolean;
    readonly credentialsRequired: boolean;
  };
  readonly compatibility: {
    readonly readiness: string;
    readonly passed: boolean;
    readonly metrics: readonly EvidenceMetric[];
    readonly gates: readonly MigrationGate[];
    readonly mappings: readonly ({ readonly kind: string } & CodemodKindMetric)[];
    readonly manualTodos: readonly ManualTodo[];
    readonly unsupportedModules: readonly UnsupportedModule[];
  };
  readonly widgets: WidgetReadinessArtifact["report"];
  readonly maplibre: {
    readonly readiness: string;
    readonly metrics: readonly EvidenceMetric[];
    readonly gates: readonly MigrationGate[];
    readonly mappings: readonly ({ readonly kind: string } & CodemodKindMetric)[];
    readonly manualTodos: readonly ManualTodo[];
    readonly unsupportedModules: readonly UnsupportedModule[];
  };
  readonly assertions: readonly AssertionMatrixRow[];
  readonly browserProofPassed: boolean;
  readonly patchProof: MigrationWorkbenchReportArtifact["patchProof"];
  readonly commands: readonly ArtifactCommand[];
  readonly files: readonly (ArtifactManifestFile & { readonly href?: string })[];
  readonly diff: string;
  readonly provenance: MigrationProvenance;
}
