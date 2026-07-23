import path from "node:path";

import { describe, expect, it } from "vitest";

import { emitEsriSampleCorpusEvidence } from "../src/migration/sample-corpus-evidence.js";
import { loadEsriSampleCorpusManifest } from "../src/migration/sample-corpus.js";

const corpusRoot = path.join(import.meta.dirname, "fixtures", "esri-sample-corpus");
const manifestPath = path.join(corpusRoot, "manifest.json");

describe("Esri sample corpus per-sample evidence", () => {
  it("runs the migration codemod against the public feature-layer fixture and records plausible evidence", () => {
    const evidence = emitEsriSampleCorpusEvidence({ manifestPath });
    const record = evidence.samples.find((sample) => sample.sampleId === "feature-layer-popup-public");

    expect(record).toBeDefined();
    if (!record) {
      return;
    }

    expect(record.status).toBe("migrated");
    expect(record.codemodTarget).toBe("honua-maplibre");
    expect(record.sourceRef.url).toMatch(/developers\.arcgis\.com/);
    expect(record.license.notice).toMatch(/Do not vendor Esri sample source/);
    expect(record.skipReasons).toEqual([]);

    // Auto + manual + unsupported counts must be non-negative numbers and the
    // codemod must have scanned at least the entrypoint file. Exact values
    // intentionally not asserted ? they will shift as the codemod evolves.
    expect(record.filesScanned).toBeGreaterThan(0);
    expect(record.classification.auto).toBeGreaterThanOrEqual(0);
    expect(record.classification.manual).toBeGreaterThanOrEqual(0);
    expect(record.classification.unsupported).toBeGreaterThanOrEqual(0);
    expect(record.classification.auto + record.classification.manual).toBeGreaterThan(0);

    // Structural checks on derived fields.
    expect(Array.isArray(record.unsupportedApis)).toBe(true);
    for (const api of record.unsupportedApis) {
      expect(typeof api).toBe("string");
    }
    expect(record.manualTodos.total).toBe(record.classification.manual);
    expect(record.referencedServices.map((service) => service.kind)).toContain("FeatureServer");
    expect(record.urlRewriteSummary.total).toBe(record.referencedServices.length);
    expect(record.urlRewriteSummary.byKind.FeatureServer).toBeGreaterThanOrEqual(1);
    expect(record.portalItems).toEqual([{ id: "0123456789abcdef0123456789abcdef" }]);
  });

  it("records skipped samples with status 'skipped' and the manifest skip reason", () => {
    const manifest = loadEsriSampleCorpusManifest(manifestPath);
    const evidence = emitEsriSampleCorpusEvidence({ manifestPath });

    const routingRecord = evidence.samples.find((sample) => sample.sampleId === "routing-api-key-skipped");
    const portalRecord = evidence.samples.find((sample) => sample.sampleId === "private-portal-skipped");

    expect(routingRecord).toBeDefined();
    expect(portalRecord).toBeDefined();
    if (!routingRecord || !portalRecord) {
      return;
    }

    const routingManifest = manifest.samples.find((sample) => sample.id === "routing-api-key-skipped");
    const portalManifest = manifest.samples.find((sample) => sample.id === "private-portal-skipped");

    expect(routingRecord.status).toBe("skipped");
    expect(routingRecord.skipReasons).toEqual(routingManifest?.skipReasons);
    expect(routingRecord.reason).toContain("requires-api-key");
    expect(routingRecord.reason).toContain("premium-service");
    expect(routingRecord.classification).toEqual({ auto: 0, manual: 0, unsupported: 0 });
    expect(routingRecord.manualTodos.total).toBe(0);
    expect(routingRecord.unsupportedApis).toEqual([]);

    expect(portalRecord.status).toBe("skipped");
    expect(portalRecord.skipReasons).toEqual(portalManifest?.skipReasons);
    expect(portalRecord.reason).toContain("requires-oauth");
    expect(portalRecord.reason).toContain("private-content");
  });

  it("aggregates per-status counts that sum to the manifest length and dedupes unsupported APIs", () => {
    const manifest = loadEsriSampleCorpusManifest(manifestPath);
    const evidence = emitEsriSampleCorpusEvidence({ manifestPath });
    const { aggregate } = evidence;

    expect(aggregate.sampleCount).toBe(manifest.samples.length);
    expect(aggregate.codemodTarget).toBe("honua-maplibre");

    const summedStatus =
      aggregate.statusCounts.migrated + aggregate.statusCounts.skipped + aggregate.statusCounts.error;
    expect(summedStatus).toBe(manifest.samples.length);
    expect(aggregate.statusCounts.migrated).toBeGreaterThanOrEqual(1);
    expect(aggregate.statusCounts.skipped).toBeGreaterThanOrEqual(2);
    expect(aggregate.statusCounts.error).toBe(0);

    // Totals are non-negative sums over the per-sample classification counts.
    const expectedAuto = evidence.samples.reduce((sum, sample) => sum + sample.classification.auto, 0);
    const expectedManual = evidence.samples.reduce((sum, sample) => sum + sample.classification.manual, 0);
    expect(aggregate.totals.auto).toBe(expectedAuto);
    expect(aggregate.totals.manual).toBe(expectedManual);

    // Unique unsupported APIs are deduplicated and sorted.
    const sorted = [...aggregate.uniqueUnsupportedApis].sort();
    expect(aggregate.uniqueUnsupportedApis).toEqual(sorted);
    expect(new Set(aggregate.uniqueUnsupportedApis).size).toBe(aggregate.uniqueUnsupportedApis.length);
  });
});
