import { describe, expect, it } from "vitest";

import {
  MIGRATION_EVIDENCE_STATES,
  MIGRATION_MANIFEST_ARTIFACT_KIND,
  MIGRATION_MANIFEST_ARTIFACT_VERSION,
  MIGRATION_PARITY_EVIDENCE_ARTIFACT_KIND,
  MIGRATION_PARITY_EVIDENCE_ARTIFACT_VERSION,
  MIGRATION_SOURCE_INVENTORY_ARTIFACT_KIND,
  MIGRATION_SOURCE_INVENTORY_ARTIFACT_VERSION,
  type MigrationCompatibilityAssessment,
  type MigrationManifestArtifact,
  type MigrationParityEvidenceArtifact,
  type MigrationReadinessAttestation,
  type MigrationSourceInventoryArtifact,
} from "../src/migration-entry.js";

const compatibility = {
  level: "compatible",
  code: "COMPATIBLE",
  reason: "Supported by the migration toolkit",
  warnings: [],
  manualSteps: [],
} satisfies MigrationCompatibilityAssessment;

describe("migration admin artifact contracts", () => {
  it("exposes stable source inventory kind/version and nested inventory fields", () => {
    const artifact: MigrationSourceInventoryArtifact = {
      artifactKind: MIGRATION_SOURCE_INVENTORY_ARTIFACT_KIND,
      artifactVersion: MIGRATION_SOURCE_INVENTORY_ARTIFACT_VERSION,
      sourceKind: "arcgis-geoservices-rest",
      source: {
        displayName: "Parcels FeatureServer",
        baseUrl: "https://source.example/arcgis/rest/services/Parcels/FeatureServer",
        product: "ArcGIS Server",
        version: "11.2",
        serviceType: "FeatureServer",
      },
      authPosture: {
        mode: "anonymous",
        credentialsSupplied: false,
        accessConfirmed: true,
        notes: [],
      },
      scanCompleteness: {
        status: "failed",
        warnings: ["Anonymous discovery was blocked"],
        missingArtifacts: ["layers"],
      },
      summary: {
        containerCount: 1,
        resourceCount: 1,
        styleCount: 1,
        externalDependencyCount: 1,
        compatibleCount: 0,
        partiallyCompatibleCount: 0,
        incompatibleCount: 1,
      },
      overallCompatibility: {
        ...compatibility,
        level: "incompatible",
        code: "ARCGIS_TOKEN_REQUIRED",
        reason: "The source requires a token",
        manualSteps: ["Provide source access before import planning"],
      },
      containers: [{ id: "service:parcels", kind: "service", name: "Parcels", compatibility }],
      resources: [
        {
          id: "layer:0",
          containerId: "service:parcels",
          kind: "feature-layer",
          name: "Parcels",
          geometryType: "esriGeometryPolygon",
          hasAttachments: true,
          capabilities: ["Query"],
          spatialReferences: [
            {
              role: "service",
              sourceValue: "EPSG:4326",
              srid: 4326,
              crsUri: "http://www.opengis.net/def/crs/EPSG/0/4326",
              axisOrder: "long-lat",
              isGeographic: true,
            },
          ],
          fields: [
            {
              name: "status",
              alias: "Status",
              fieldType: "esriFieldTypeString",
              nullable: true,
              domainType: "codedValue",
              domainName: "StatusDomain",
              domainValues: [{ code: "open", name: "Open" }],
            },
          ],
          styleIds: ["renderer:0"],
          externalDependencyIds: ["attachments:0"],
          compatibility,
        },
      ],
      styles: [
        {
          id: "renderer:0",
          containerId: "service:parcels",
          kind: "renderer",
          name: "default",
          format: "arcgis-drawingInfo",
          resourceIds: ["layer:0"],
          externalDependencyIds: [],
          metadata: { rendererType: "simple" },
          compatibility,
        },
      ],
      externalDependencies: [
        {
          id: "attachments:0",
          containerId: "service:parcels",
          resourceId: "layer:0",
          kind: "attachments",
          name: "Layer attachments",
          metadata: {},
          spatialReferences: [],
          compatibility,
        },
      ],
    };

    expect(artifact.artifactKind).toBe("honua.migration.source-inventory");
    expect(artifact.artifactVersion).toBe("1.0");
    expect(artifact.scanCompleteness.status).toBe("failed");
    expect(artifact.resources[0]?.fields[0]?.domainValues?.[0]).toEqual({ code: "open", name: "Open" });
    expect(artifact.resources[0]?.spatialReferences[0]?.srid).toBe(4326);
  });

  it("exposes stable manifest kind/version and target review fields", () => {
    const manifest: MigrationManifestArtifact = {
      artifactKind: MIGRATION_MANIFEST_ARTIFACT_KIND,
      artifactVersion: MIGRATION_MANIFEST_ARTIFACT_VERSION,
      sourceArtifactKind: MIGRATION_SOURCE_INVENTORY_ARTIFACT_KIND,
      sourceArtifactVersion: MIGRATION_SOURCE_INVENTORY_ARTIFACT_VERSION,
      sourceKind: "geoserver-rest",
      source: { displayName: "GeoServer", baseUrl: "https://source.example/geoserver/rest" },
      summary: {
        sourceResourceCount: 1,
        targetResourceCount: 1,
        styleActionCount: 1,
        manualReviewCount: 1,
        unsupportedCount: 0,
      },
      targetResources: [
        {
          sourceResourceId: "layer:roads",
          sourceKind: "layer",
          action: "publish",
          targetServiceName: "geoserver",
          targetResourceName: "roads",
          fields: [],
          capabilities: ["Query"],
          spatialReferences: [],
          styleIds: ["style:roads"],
          externalDependencyIds: [],
          compatibility,
        },
      ],
      styleActions: [
        {
          sourceStyleId: "style:roads",
          action: "manual-review",
          format: "sld",
          resourceIds: ["layer:roads"],
          externalDependencyIds: [],
          compatibility,
        },
      ],
      manualReviewItems: [
        {
          sourceId: "style:roads",
          kind: "style",
          code: "MANUAL_REVIEW",
          severity: "manual-review",
          reason: "Review style fidelity",
          manualSteps: ["Compare generated style"],
          warnings: [],
        },
      ],
      unsupportedItems: [],
    };

    expect(manifest.artifactKind).toBe("honua.migration.manifest");
    expect(manifest.sourceArtifactKind).toBe("honua.migration.source-inventory");
    expect(manifest.targetResources[0]?.targetServiceName).toBe("geoserver");
    expect(manifest.manualReviewItems[0]?.severity).toBe("manual-review");
  });

  it("preserves parity evidence and readiness attestation state values", () => {
    const evidence: MigrationParityEvidenceArtifact = {
      artifactKind: MIGRATION_PARITY_EVIDENCE_ARTIFACT_KIND,
      artifactVersion: MIGRATION_PARITY_EVIDENCE_ARTIFACT_VERSION,
      sourceKind: "geoserver-rest",
      source: { displayName: "GeoServer", baseUrl: "https://source.example/geoserver/rest" },
      overallState: MIGRATION_EVIDENCE_STATES.unknown,
      summary: "Pilot review is incomplete",
      manifestAvailable: true,
      sections: [
        {
          id: "data",
          title: "Data parity",
          state: MIGRATION_EVIDENCE_STATES.fail,
          items: [
            {
              id: "feature-counts",
              state: MIGRATION_EVIDENCE_STATES.pass,
              summary: "Feature counts match",
              evidence: ["source=10 target=10"],
              remediation: [],
              relatedIds: ["layer:roads"],
            },
          ],
        },
      ],
      cutoverReadiness: {
        state: MIGRATION_EVIDENCE_STATES["notApplicable"],
        items: [
          {
            id: "rollback-plan",
            title: "Rollback plan approved",
            state: MIGRATION_EVIDENCE_STATES["notApplicable"],
            evidence: ["Pilot only"],
            remediation: [],
            owner: "ops",
          },
        ],
      },
    };
    const attestation: MigrationReadinessAttestation = {
      items: [
        {
          id: "rollback-plan",
          state: MIGRATION_EVIDENCE_STATES.unknown,
          evidence: [],
          owner: "ops",
        },
      ],
    };

    expect(Object.values(MIGRATION_EVIDENCE_STATES)).toEqual(["pass", "fail", "unknown", "not-applicable"]);
    expect(evidence.artifactKind).toBe("honua.migration.parity-evidence-pack");
    expect(evidence.sections[0]?.items[0]?.state).toBe("pass");
    expect(evidence.cutoverReadiness.items[0]?.state).toBe("not-applicable");
    expect(attestation.items[0]?.state).toBe("unknown");
  });
});
