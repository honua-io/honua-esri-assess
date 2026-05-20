import path from "node:path";

import { describe, expect, it } from "vitest";

import {
  analyzeEsriSampleFixture,
  classifyArcGisServiceUrl,
  extractEsriSampleReferences,
  loadEsriSampleCorpusManifest,
  summarizeEsriSampleCorpus,
} from "../src/migration/sample-corpus.js";

const corpusRoot = path.join(import.meta.dirname, "fixtures", "esri-sample-corpus");
const manifestPath = path.join(corpusRoot, "manifest.json");

describe("Esri sample migration corpus", () => {
  it("loads the curated manifest with licensing and CI guardrails", () => {
    const manifest = loadEsriSampleCorpusManifest(manifestPath);
    const summary = summarizeEsriSampleCorpus(manifest);

    expect(manifest.schemaVersion).toBe("honua.esri-sample-corpus.v1");
    expect(manifest.guardrails).toEqual(
      expect.objectContaining({
        noVendoredEsriSampleCode: true,
        noCommittedEsriServiceData: true,
        prCiUsesFixtureOnly: true,
        liveRunsRequireOptIn: true,
      }),
    );
    expect(summary).toEqual({
      sampleCount: 3,
      fixtureCiCount: 1,
      liveEvidenceCount: 0,
      skippedCount: 2,
      guardrailFailures: [],
    });
    expect(manifest.samples.every((sample) => sample.source.referenceOnly)).toBe(true);
    expect(manifest.samples.every((sample) => sample.fixture.ownership === "honua")).toBe(true);
    expect(manifest.samples.map((sample) => sample.license.notice)).toEqual([
      "Do not vendor Esri sample source without a separate license and notice review.",
      "Do not vendor Esri sample source without a separate license and notice review.",
      "Do not vendor Esri sample source without a separate license and notice review.",
    ]);
  });

  it("extracts service URLs, Portal items, and auth guardrail flags from fixture snippets", () => {
    const manifest = loadEsriSampleCorpusManifest(manifestPath);
    const analyses = manifest.samples.map((sample) => analyzeEsriSampleFixture(sample, { manifestDir: corpusRoot }));

    expect(analyses).toEqual([
      expect.objectContaining({
        sampleId: "feature-layer-popup-public",
        filesScanned: 1,
        status: "ci-fixture",
        skipReasons: [],
        portalItems: [{ id: "0123456789abcdef0123456789abcdef" }],
        guardrailFlags: ["external-live-service-reference"],
      }),
      expect.objectContaining({
        sampleId: "routing-api-key-skipped",
        status: "skipped",
        skipReasons: ["requires-api-key", "premium-service"],
        guardrailFlags: ["api-key-reference", "external-live-service-reference", "premium-service-reference"],
      }),
      expect.objectContaining({
        sampleId: "private-portal-skipped",
        status: "skipped",
        skipReasons: ["requires-oauth", "private-content"],
        portalItems: [{ id: "privatePortalItem001" }],
        guardrailFlags: ["oauth-reference"],
      }),
    ]);

    expect(analyses[0].serviceUrls).toEqual([
      {
        url: "https://sampleserver.example.com/arcgis/rest/services/Public/Incidents/FeatureServer/0",
        normalizedUrl: "https://sampleserver.example.com/arcgis/rest/services/Public/Incidents/FeatureServer/0",
        kind: "FeatureServer",
        servicePath: "Public/Incidents",
        layerId: 0,
      },
    ]);
    expect(analyses[1].serviceUrls).toEqual([
      {
        url: "https://route.example.com/arcgis/rest/services/World/Route/NAServer/Route_World",
        normalizedUrl: "https://route.example.com/arcgis/rest/services/World/Route/NAServer/Route_World",
        kind: "NAServer",
        servicePath: "World/Route/NAServer/Route_World",
        layerId: undefined,
      },
      {
        url: "https://route.example.com/arcgis/rest/services/World/RouteServer",
        normalizedUrl: "https://route.example.com/arcgis/rest/services/World/RouteServer",
        kind: "RouteServer",
        servicePath: "World",
        layerId: undefined,
      },
    ]);
  });

  it("classifies ArcGIS service URLs without retaining query strings", () => {
    expect(
      classifyArcGisServiceUrl(
        "https://example.com/arcgis/rest/services/Hosted/Parcels/MapServer/2?f=json&token=not-retained",
      ),
    ).toEqual({
      url: "https://example.com/arcgis/rest/services/Hosted/Parcels/MapServer/2?f=json&token=not-retained",
      normalizedUrl: "https://example.com/arcgis/rest/services/Hosted/Parcels/MapServer/2",
      kind: "MapServer",
      servicePath: "Hosted/Parcels",
      layerId: 2,
    });
  });

  it("recognizes NAServer routing endpoints and flags them as premium-service references", () => {
    const extraction = extractEsriSampleReferences(`
      const routeUrl = "https://route.arcgis.com/arcgis/rest/services/World/Route/NAServer/Route_World";
      const closestUrl = "https://route.arcgis.com/arcgis/rest/services/World/ClosestFacility/NAServer/ClosestFacility_World";
    `);

    expect(extraction.serviceUrls).toHaveLength(2);
    expect(extraction.serviceUrls.every((entry) => entry.kind === "NAServer")).toBe(true);
    expect(extraction.guardrailFlags).toContain("premium-service-reference");
  });

  it("classifies NAServer URLs with the network-analyst sub-service name folded into servicePath", () => {
    expect(
      classifyArcGisServiceUrl("https://route.arcgis.com/arcgis/rest/services/World/Route/NAServer/Route_World"),
    ).toEqual({
      url: "https://route.arcgis.com/arcgis/rest/services/World/Route/NAServer/Route_World",
      normalizedUrl: "https://route.arcgis.com/arcgis/rest/services/World/Route/NAServer/Route_World",
      kind: "NAServer",
      servicePath: "World/Route/NAServer/Route_World",
      layerId: undefined,
    });
  });

  it("deduplicates references found through common sample code shapes", () => {
    const extraction = extractEsriSampleReferences(`
      const serviceUrl = "https://example.com/arcgis/rest/services/Hosted/Parcels/FeatureServer/0";
      const duplicate = "https://example.com/arcgis/rest/services/Hosted/Parcels/FeatureServer/0?f=json";
      const webmap = { itemId: "abcdef0123456789abcdef0123456789" };
      const map = { portalItem: { id: "abcdef0123456789abcdef0123456789" } };
    `);

    expect(extraction.serviceUrls).toHaveLength(1);
    expect(extraction.portalItems).toEqual([{ id: "abcdef0123456789abcdef0123456789" }]);
    expect(extraction.guardrailFlags).toEqual(["external-live-service-reference"]);
  });
});
