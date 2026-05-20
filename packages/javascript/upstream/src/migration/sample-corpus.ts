import fs from "node:fs";
import path from "node:path";

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]);
const SKIP_DIRS = new Set(["node_modules", "dist", ".git"]);
const ARCGIS_SERVICE_URL_REGEX =
  /https?:\/\/[^\s"'`<>)]+?\/arcgis\/rest\/services\/[^\s"'`<>)]+?\/(?:FeatureServer|MapServer|ImageServer|VectorTileServer|GeometryServer|GPServer|GeocodeServer|RouteServer|NAServer)(?:\/[A-Za-z0-9_-]+)?(?:\/\d+)?(?:\?[^\s"'`<>)]+)?/gi;
const PORTAL_ITEM_OBJECT_REGEX =
  /\bportalItem\s*:\s*\{[\s\S]{0,320}?\bid\s*:\s*["']([A-Za-z0-9_-]{6,})["'][\s\S]{0,320}?\}/g;
const PORTAL_ITEM_ID_REGEX = /\b(?:itemId|portalItemId)\s*:\s*["']([A-Za-z0-9_-]{6,})["']/g;
const API_KEY_REGEX = /\b(?:apiKey|api_key)\b/i;
const OAUTH_REGEX = /\b(?:OAuthInfo|IdentityManager|registerToken|checkSignInStatus|getCredential)\b/i;
const PREMIUM_REGEX = /\b(?:Directions|RouteLayer|RouteTask|ClosestFacility|ServiceArea|UtilityNetwork)\b/i;

export type EsriSampleCorpusSchemaVersion = "honua.esri-sample-corpus.v1";

export type EsriSampleCorpusLane = "pr-fixture" | "manual-live" | "scheduled-live";

export type EsriSampleCorpusSampleStatus = "ci-fixture" | "live-evidence" | "skipped";

export type EsriSampleSkipReason =
  | "requires-api-key"
  | "requires-oauth"
  | "premium-service"
  | "private-content"
  | "unclear-content-terms"
  | "unsupported-sample-family";

export type ArcGisServiceKind =
  | "FeatureServer"
  | "MapServer"
  | "ImageServer"
  | "VectorTileServer"
  | "GeometryServer"
  | "GPServer"
  | "GeocodeServer"
  | "RouteServer"
  | "NAServer"
  | "unknown";

export interface EsriSampleCorpusManifest {
  schemaVersion: EsriSampleCorpusSchemaVersion;
  generatedBy: "honua";
  guardrails: EsriSampleCorpusGuardrails;
  samples: EsriSampleCorpusSample[];
}

export interface EsriSampleCorpusGuardrails {
  noVendoredEsriSampleCode: boolean;
  noCommittedEsriServiceData: boolean;
  prCiUsesFixtureOnly: boolean;
  liveRunsRequireOptIn: boolean;
  liveRunLanes: EsriSampleCorpusLane[];
  notes: string[];
}

export interface EsriSampleCorpusSample {
  id: string;
  title: string;
  source: EsriSampleSourceReference;
  fixture: EsriSampleFixtureReference;
  status: EsriSampleCorpusSampleStatus;
  license: EsriSampleLicenseMetadata;
  terms: EsriSampleTermsMetadata;
  skipReasons?: EsriSampleSkipReason[];
  expected?: EsriSampleExpectedReferences;
}

export interface EsriSampleSourceReference {
  url: string;
  sampleCodePath?: string;
  referenceOnly: boolean;
  retrievedAt?: string;
}

export interface EsriSampleFixtureReference {
  root: string;
  entrypoints: string[];
  ownership: "honua";
  description: string;
}

export interface EsriSampleLicenseMetadata {
  label: string;
  url: string;
  notice: string;
}

export interface EsriSampleTermsMetadata {
  sampleCode: string;
  serviceContent: string;
  liveEvidence: string;
}

export interface EsriSampleExpectedReferences {
  serviceKinds?: ArcGisServiceKind[];
  portalItemIds?: string[];
  guardrailFlags?: EsriSampleGuardrailFlag[];
}

export interface ArcGisServiceReference {
  url: string;
  normalizedUrl: string;
  kind: ArcGisServiceKind;
  servicePath?: string;
  layerId?: number;
}

export interface PortalItemReference {
  id: string;
}

export type EsriSampleGuardrailFlag =
  | "api-key-reference"
  | "oauth-reference"
  | "premium-service-reference"
  | "external-live-service-reference";

export interface EsriSampleReferenceExtraction {
  serviceUrls: ArcGisServiceReference[];
  portalItems: PortalItemReference[];
  guardrailFlags: EsriSampleGuardrailFlag[];
}

export interface EsriSampleFixtureAnalysis extends EsriSampleReferenceExtraction {
  sampleId: string;
  filesScanned: number;
  status: EsriSampleCorpusSampleStatus;
  skipReasons: EsriSampleSkipReason[];
}

export interface EsriSampleCorpusSummary {
  sampleCount: number;
  fixtureCiCount: number;
  liveEvidenceCount: number;
  skippedCount: number;
  guardrailFailures: string[];
}

export function loadEsriSampleCorpusManifest(manifestPath: string): EsriSampleCorpusManifest {
  const parsed = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as unknown;
  return parseEsriSampleCorpusManifest(parsed, manifestPath);
}

export function parseEsriSampleCorpusManifest(value: unknown, sourceName = "manifest"): EsriSampleCorpusManifest {
  const record = expectRecord(value, sourceName);
  if (record.schemaVersion !== "honua.esri-sample-corpus.v1") {
    throw new Error(`${sourceName} must use schemaVersion honua.esri-sample-corpus.v1.`);
  }
  if (record.generatedBy !== "honua") {
    throw new Error(`${sourceName} must be generatedBy honua.`);
  }

  const guardrails = expectRecord(
    record.guardrails,
    `${sourceName}.guardrails`,
  ) as unknown as EsriSampleCorpusGuardrails;
  const samples = expectArray(record.samples, `${sourceName}.samples`).map((sample, index) =>
    parseSample(sample, `${sourceName}.samples[${index}]`),
  );

  return {
    schemaVersion: "honua.esri-sample-corpus.v1",
    generatedBy: "honua",
    guardrails: {
      noVendoredEsriSampleCode: expectBoolean(
        guardrails.noVendoredEsriSampleCode,
        `${sourceName}.guardrails.noVendoredEsriSampleCode`,
      ),
      noCommittedEsriServiceData: expectBoolean(
        guardrails.noCommittedEsriServiceData,
        `${sourceName}.guardrails.noCommittedEsriServiceData`,
      ),
      prCiUsesFixtureOnly: expectBoolean(
        guardrails.prCiUsesFixtureOnly,
        `${sourceName}.guardrails.prCiUsesFixtureOnly`,
      ),
      liveRunsRequireOptIn: expectBoolean(
        guardrails.liveRunsRequireOptIn,
        `${sourceName}.guardrails.liveRunsRequireOptIn`,
      ),
      liveRunLanes: expectStringArray(
        guardrails.liveRunLanes,
        `${sourceName}.guardrails.liveRunLanes`,
      ) as EsriSampleCorpusLane[],
      notes: expectStringArray(guardrails.notes, `${sourceName}.guardrails.notes`),
    },
    samples,
  };
}

export function summarizeEsriSampleCorpus(manifest: EsriSampleCorpusManifest): EsriSampleCorpusSummary {
  const guardrailFailures: string[] = [];
  if (!manifest.guardrails.noVendoredEsriSampleCode) {
    guardrailFailures.push("guardrails.noVendoredEsriSampleCode must remain true");
  }
  if (!manifest.guardrails.noCommittedEsriServiceData) {
    guardrailFailures.push("guardrails.noCommittedEsriServiceData must remain true");
  }
  if (!manifest.guardrails.prCiUsesFixtureOnly) {
    guardrailFailures.push("guardrails.prCiUsesFixtureOnly must remain true");
  }
  if (!manifest.guardrails.liveRunsRequireOptIn) {
    guardrailFailures.push("guardrails.liveRunsRequireOptIn must remain true");
  }

  for (const sample of manifest.samples) {
    if (!sample.source.referenceOnly) {
      guardrailFailures.push(`${sample.id}: source.referenceOnly must remain true`);
    }
    if (sample.fixture.ownership !== "honua") {
      guardrailFailures.push(`${sample.id}: fixture.ownership must be honua`);
    }
    if (sample.status === "skipped" && (!sample.skipReasons || sample.skipReasons.length === 0)) {
      guardrailFailures.push(`${sample.id}: skipped samples must record skipReasons`);
    }
  }

  return {
    sampleCount: manifest.samples.length,
    fixtureCiCount: manifest.samples.filter((sample) => sample.status === "ci-fixture").length,
    liveEvidenceCount: manifest.samples.filter((sample) => sample.status === "live-evidence").length,
    skippedCount: manifest.samples.filter((sample) => sample.status === "skipped").length,
    guardrailFailures,
  };
}

export function analyzeEsriSampleFixture(
  sample: EsriSampleCorpusSample,
  options: { manifestDir: string },
): EsriSampleFixtureAnalysis {
  const fixtureRoot = path.resolve(options.manifestDir, sample.fixture.root);
  const entrypointFiles = sample.fixture.entrypoints.map((entrypoint) => path.resolve(fixtureRoot, entrypoint));
  const files = entrypointFiles.length > 0 ? entrypointFiles : collectSourceFiles(fixtureRoot);
  const combined: EsriSampleReferenceExtraction = {
    serviceUrls: [],
    portalItems: [],
    guardrailFlags: [],
  };

  for (const file of files) {
    const extraction = extractEsriSampleReferences(fs.readFileSync(file, "utf8"));
    combined.serviceUrls.push(...extraction.serviceUrls);
    combined.portalItems.push(...extraction.portalItems);
    combined.guardrailFlags.push(...extraction.guardrailFlags);
  }

  const serviceUrls = uniqueBy(combined.serviceUrls, (item) => item.normalizedUrl);
  const portalItems = uniqueBy(combined.portalItems, (item) => item.id);
  const guardrailFlags = Array.from(new Set(combined.guardrailFlags)).sort();

  return {
    sampleId: sample.id,
    filesScanned: files.length,
    status: sample.status,
    skipReasons: sample.skipReasons ?? [],
    serviceUrls,
    portalItems,
    guardrailFlags,
  };
}

export function extractEsriSampleReferences(source: string): EsriSampleReferenceExtraction {
  const serviceUrls: ArcGisServiceReference[] = [];
  const portalItems: PortalItemReference[] = [];
  const guardrailFlags = new Set<EsriSampleGuardrailFlag>();

  for (const match of source.matchAll(ARCGIS_SERVICE_URL_REGEX)) {
    const service = classifyArcGisServiceUrl(match[0]);
    serviceUrls.push(service);
    if (service.normalizedUrl.startsWith("http://") || service.normalizedUrl.startsWith("https://")) {
      guardrailFlags.add("external-live-service-reference");
    }
    if (service.kind === "RouteServer" || service.kind === "NAServer") {
      guardrailFlags.add("premium-service-reference");
    }
  }

  for (const match of source.matchAll(PORTAL_ITEM_OBJECT_REGEX)) {
    portalItems.push({ id: match[1] });
  }
  for (const match of source.matchAll(PORTAL_ITEM_ID_REGEX)) {
    portalItems.push({ id: match[1] });
  }

  if (API_KEY_REGEX.test(source)) {
    guardrailFlags.add("api-key-reference");
  }
  if (OAUTH_REGEX.test(source)) {
    guardrailFlags.add("oauth-reference");
  }
  if (PREMIUM_REGEX.test(source)) {
    guardrailFlags.add("premium-service-reference");
  }

  return {
    serviceUrls: uniqueBy(serviceUrls, (item) => item.normalizedUrl),
    portalItems: uniqueBy(portalItems, (item) => item.id),
    guardrailFlags: Array.from(guardrailFlags).sort(),
  };
}

export function classifyArcGisServiceUrl(url: string): ArcGisServiceReference {
  const cleanedUrl = url.replace(/[),.;\]]+$/, "");
  const parsed = new URL(cleanedUrl);
  parsed.search = "";
  parsed.hash = "";
  const normalizedUrl = parsed.toString().replace(/\/$/, "");
  const serviceMatch = normalizedUrl.match(
    /\/arcgis\/rest\/services\/(.+?)\/(FeatureServer|MapServer|ImageServer|VectorTileServer|GeometryServer|GPServer|GeocodeServer|RouteServer|NAServer)(?:\/([A-Za-z0-9_-]+))?(?:\/(\d+))?$/i,
  );

  if (!serviceMatch) {
    return {
      url: cleanedUrl,
      normalizedUrl,
      kind: "unknown",
    };
  }

  const kind = serviceMatch[2] as ArcGisServiceKind;
  // For NAServer, the third capture is the network-analyst sub-service name
  // (e.g., Route_World, ClosestFacility_World) ? fold it into servicePath so
  // downstream consumers see it. For other kinds it's the numeric layer id.
  let servicePath = serviceMatch[1];
  let layerToken: string | undefined;
  if (kind === "NAServer") {
    if (serviceMatch[3]) {
      servicePath = `${servicePath}/NAServer/${serviceMatch[3]}`;
    }
    layerToken = serviceMatch[4];
  } else {
    layerToken = serviceMatch[3] ?? serviceMatch[4];
  }
  const layerId = layerToken === undefined ? undefined : Number.parseInt(layerToken, 10);
  return {
    url: cleanedUrl,
    normalizedUrl,
    kind,
    servicePath,
    layerId: Number.isFinite(layerId) ? layerId : undefined,
  };
}

function parseSample(value: unknown, sourceName: string): EsriSampleCorpusSample {
  const record = expectRecord(value, sourceName);
  const status = expectString(record.status, `${sourceName}.status`) as EsriSampleCorpusSampleStatus;
  const skipReasons =
    record.skipReasons === undefined
      ? undefined
      : (expectStringArray(record.skipReasons, `${sourceName}.skipReasons`) as EsriSampleSkipReason[]);

  return {
    id: expectString(record.id, `${sourceName}.id`),
    title: expectString(record.title, `${sourceName}.title`),
    source: expectRecord(record.source, `${sourceName}.source`) as unknown as EsriSampleSourceReference,
    fixture: expectRecord(record.fixture, `${sourceName}.fixture`) as unknown as EsriSampleFixtureReference,
    status,
    license: expectRecord(record.license, `${sourceName}.license`) as unknown as EsriSampleLicenseMetadata,
    terms: expectRecord(record.terms, `${sourceName}.terms`) as unknown as EsriSampleTermsMetadata,
    skipReasons,
    expected: record.expected as EsriSampleExpectedReferences | undefined,
  };
}

function collectSourceFiles(rootDir: string): string[] {
  const queue = [rootDir];
  const result: string[] = [];
  while (queue.length > 0) {
    const current = queue.pop()!;
    const entries = fs.readdirSync(current, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (!SKIP_DIRS.has(entry.name)) {
          queue.push(fullPath);
        }
      } else if (SOURCE_EXTENSIONS.has(path.extname(entry.name))) {
        result.push(fullPath);
      }
    }
  }
  return result.sort();
}

function uniqueBy<T>(items: T[], getKey: (item: T) => string): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const item of items) {
    const key = getKey(item);
    if (!seen.has(key)) {
      seen.add(key);
      result.push(item);
    }
  }
  return result;
}

function expectRecord(value: unknown, sourceName: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${sourceName} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function expectArray(value: unknown, sourceName: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${sourceName} must be an array.`);
  }
  return value;
}

function expectString(value: unknown, sourceName: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${sourceName} must be a non-empty string.`);
  }
  return value;
}

function expectBoolean(value: unknown, sourceName: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${sourceName} must be a boolean.`);
  }
  return value;
}

function expectStringArray(value: unknown, sourceName: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string" || item.length === 0)) {
    throw new Error(`${sourceName} must be an array of non-empty strings.`);
  }
  return value as string[];
}
