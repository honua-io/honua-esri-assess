import fs from "node:fs";
import path from "node:path";

import { parseWebMap } from "../webmap/parse.js";
import type { WebMapJson } from "../webmap/types.js";
import { type GeoservicesImportJobReport, runGeoservicesImportJob } from "./demo.js";

const DEFAULT_PORTAL_PAGE_SIZE = 100;
const DEFAULT_LAYER_QUERY_PAGE_SIZE = 2_000;
const DEFAULT_IMPORT_TIMEOUT_MS = 10 * 60 * 1_000;
const DEFAULT_IMPORT_POLL_INTERVAL_MS = 2_000;
const REDACTED_SECRET = "[REDACTED]";

const MANUAL_INTERVENTION_WARNING_CODES = new Set([
  "unsupported-renderer",
  "unsupported-layer-type",
  "unsupported-feature-collection",
  "unsupported-arcade-expression",
  "unsupported-3d-property",
  "complex-arcade",
  "complex-label-expression",
]);

export interface ContentPortalItemSummary {
  id: string;
  title: string;
  type: string;
  owner?: string;
  url?: string;
}

export interface ContentScanOptions {
  portalUrl: string;
  token?: string;
  owner?: string;
  pageSize?: number;
  fetchFn?: typeof fetch;
}

export interface ContentScanReport {
  generatedAt: string;
  portalUrl: string;
  webMaps: ContentPortalItemSummary[];
  hostedFeatureServices: ContentPortalItemSummary[];
}

export interface ExportedWebMap {
  itemId: string;
  title: string;
  webMapPath: string;
}

export interface ExportedHostedLayerEntry {
  layerId: number;
  layerName?: string;
  layerMetadataPath: string;
  featureCount?: number;
  featureSetPath?: string;
  geoJsonPath?: string;
}

export interface ExportedHostedService {
  itemId: string;
  title: string;
  serviceUrl: string;
  serviceMetadataPath: string;
  layers: ExportedHostedLayerEntry[];
}

export interface ContentExportManifest {
  generatedAt: string;
  portalUrl: string;
  webMaps: ExportedWebMap[];
  hostedFeatureServices: ExportedHostedService[];
}

export interface ContentExportOptions extends ContentScanOptions {
  outputDir: string;
  includeWebMaps?: boolean;
  includeHostedLayers?: boolean;
  includeFeatures?: boolean;
  maxFeaturesPerLayer?: number;
  layerQueryPageSize?: number;
}

export interface ContentExportReport {
  generatedAt: string;
  portalUrl: string;
  outputDir: string;
  scan: ContentScanReport;
  manifestPath: string;
  exportedWebMaps: ExportedWebMap[];
  exportedHostedFeatureServices: ExportedHostedService[];
}

export interface ImportedHostedLayerReport {
  itemId: string;
  layerId: number;
  tableName: string;
  status: "completed" | "failed";
  errorMessage?: string;
  job?: GeoservicesImportJobReport;
  sourceFeatureCount?: number;
}

export interface ImportedWebMapReport {
  itemId: string;
  title: string;
  status: "converted" | "failed";
  outputPath?: string;
  warningCount?: number;
  manualInterventionNeeded?: boolean;
  rewrittenUrlCount?: number;
  errorMessage?: string;
}

export interface ContentImportOptions {
  sourceDir: string;
  targetBaseUrl: string;
  adminApiKey?: string;
  outputDir?: string;
  includeWebMaps?: boolean;
  includeHostedLayers?: boolean;
  sourceUrlPrefix?: string;
  targetUrlPrefix?: string;
  tablePrefix?: string;
  timeoutMs?: number;
  pollIntervalMs?: number;
  fetchFn?: typeof fetch;
}

export interface ContentImportReport {
  generatedAt: string;
  sourceDir: string;
  outputDir: string;
  targetBaseUrl: string;
  manifestPath: string;
  importedHostedLayers: ImportedHostedLayerReport[];
  importedWebMaps: ImportedWebMapReport[];
  summary: {
    hostedLayersCompleted: number;
    hostedLayersFailed: number;
    webMapsConverted: number;
    webMapsFailed: number;
    webMapsManualIntervention: number;
  };
  reportPath: string;
}

export interface ReconciledHostedLayerReport {
  itemId: string;
  layerId: number;
  tableName: string;
  status: "pass" | "fail";
  sourceFeatureCount?: number;
  targetProcessedCount?: number;
  reason?: string;
}

export interface ReconciledWebMapReport {
  itemId: string;
  title: string;
  status: "pass" | "manual" | "fail";
  warningCount?: number;
  reason?: string;
}

export interface ContentReconcileOptions {
  sourceDir: string;
  importReportPath?: string;
  outputPath?: string;
}

export interface ContentReconcileReport {
  generatedAt: string;
  sourceDir: string;
  manifestPath: string;
  importReportPath: string;
  hostedLayers: ReconciledHostedLayerReport[];
  webMaps: ReconciledWebMapReport[];
  summary: {
    hostedLayersPassed: number;
    hostedLayersFailed: number;
    webMapsPassed: number;
    webMapsManual: number;
    webMapsFailed: number;
  };
  reportPath: string;
}

export async function runContentScan(options: ContentScanOptions): Promise<ContentScanReport> {
  const fetchFn = options.fetchFn ?? fetch;
  const sharingRestBase = resolvePortalSharingRestBase(options.portalUrl);
  const pageSize = options.pageSize ?? DEFAULT_PORTAL_PAGE_SIZE;

  const ownerClause = options.owner ? ` AND owner:${quotePortalQueryValue(options.owner)}` : "";

  const webMaps = await searchPortalItems(
    sharingRestBase,
    `type:${quotePortalQueryValue("Web Map")}${ownerClause}`,
    pageSize,
    options.token,
    fetchFn,
  );

  const hostedServices = await searchPortalItems(
    sharingRestBase,
    `typekeywords:${quotePortalQueryValue("Hosted Service")} AND type:${quotePortalQueryValue("Feature Service")}${ownerClause}`,
    pageSize,
    options.token,
    fetchFn,
  );

  return {
    generatedAt: new Date().toISOString(),
    portalUrl: normalizeBaseUrl(options.portalUrl),
    webMaps: webMaps.map(toContentPortalItemSummary),
    hostedFeatureServices: hostedServices
      .filter((item) => typeof item.url === "string" && item.url.includes("FeatureServer"))
      .map(toContentPortalItemSummary),
  };
}

export async function runContentExport(options: ContentExportOptions): Promise<ContentExportReport> {
  const fetchFn = options.fetchFn ?? fetch;
  const includeWebMaps = options.includeWebMaps !== false;
  const includeHostedLayers = options.includeHostedLayers !== false;
  const includeFeatures = options.includeFeatures !== false;

  const outputDir = path.resolve(options.outputDir);
  fs.mkdirSync(outputDir, { recursive: true });

  const scan = await runContentScan(options);

  const exportedWebMaps: ExportedWebMap[] = [];
  if (includeWebMaps) {
    const webMapsDir = path.join(outputDir, "webmaps");
    fs.mkdirSync(webMapsDir, { recursive: true });

    for (const item of scan.webMaps) {
      const itemId = item.id;
      const data = await fetchPortalItemData(scan.portalUrl, itemId, options.token, fetchFn);
      const fileName = `${safeFileName(item.title || itemId)}-${itemId}.webmap.json`;
      const absolutePath = path.join(webMapsDir, fileName);
      fs.writeFileSync(absolutePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
      exportedWebMaps.push({
        itemId,
        title: item.title,
        webMapPath: path.relative(outputDir, absolutePath),
      });
    }
  }

  const exportedHostedFeatureServices: ExportedHostedService[] = [];
  if (includeHostedLayers) {
    const layersRootDir = path.join(outputDir, "hosted-layers");
    fs.mkdirSync(layersRootDir, { recursive: true });

    for (const item of scan.hostedFeatureServices) {
      if (!item.url) {
        continue;
      }

      const serviceDir = path.join(layersRootDir, `${safeFileName(item.title || item.id)}-${item.id}`);
      fs.mkdirSync(serviceDir, { recursive: true });

      const serviceMetadata = asRecord(
        await fetchArcGisJson(fetchFn, item.url, options.token),
        "Hosted service metadata",
      );
      const serviceMetadataPath = path.join(serviceDir, "service-metadata.json");
      fs.writeFileSync(serviceMetadataPath, `${JSON.stringify(serviceMetadata, null, 2)}\n`, "utf8");

      const layers = asArray(serviceMetadata.layers);
      const exportedLayers: ExportedHostedLayerEntry[] = [];
      for (const layerValue of layers) {
        const layer = asRecord(layerValue, "Hosted layer metadata");
        const layerId = readRequiredNumber(layer, "id");
        const layerName = readOptionalString(layer, "name");
        const layerUrl = `${normalizeBaseUrl(item.url)}/${layerId}`;

        const layerMetadata = await fetchArcGisJson(fetchFn, layerUrl, options.token);
        const layerMetadataPath = path.join(serviceDir, `layer-${layerId}.metadata.json`);
        fs.writeFileSync(layerMetadataPath, `${JSON.stringify(layerMetadata, null, 2)}\n`, "utf8");

        let featureCount: number | undefined;
        let featureSetPath: string | undefined;
        let geoJsonPath: string | undefined;

        if (includeFeatures) {
          const featureSet = await queryAllLayerFeatures({
            layerUrl,
            token: options.token,
            fetchFn,
            pageSize: options.layerQueryPageSize ?? DEFAULT_LAYER_QUERY_PAGE_SIZE,
            maxFeatures: options.maxFeaturesPerLayer,
          });

          featureCount = featureSet.features.length;
          const featureSetFilePath = path.join(serviceDir, `layer-${layerId}.features.esri.json`);
          fs.writeFileSync(featureSetFilePath, `${JSON.stringify(featureSet, null, 2)}\n`, "utf8");
          featureSetPath = path.relative(outputDir, featureSetFilePath);

          const geoJson = convertEsriFeatureSetToGeoJson(featureSet);
          if (geoJson) {
            const geoJsonFilePath = path.join(serviceDir, `layer-${layerId}.features.geojson`);
            fs.writeFileSync(geoJsonFilePath, `${JSON.stringify(geoJson, null, 2)}\n`, "utf8");
            geoJsonPath = path.relative(outputDir, geoJsonFilePath);
          }
        }

        exportedLayers.push({
          layerId,
          layerName,
          layerMetadataPath: path.relative(outputDir, layerMetadataPath),
          featureCount,
          featureSetPath,
          geoJsonPath,
        });
      }

      exportedHostedFeatureServices.push({
        itemId: item.id,
        title: item.title,
        serviceUrl: item.url,
        serviceMetadataPath: path.relative(outputDir, serviceMetadataPath),
        layers: exportedLayers,
      });
    }
  }

  const manifest: ContentExportManifest = {
    generatedAt: new Date().toISOString(),
    portalUrl: scan.portalUrl,
    webMaps: exportedWebMaps,
    hostedFeatureServices: exportedHostedFeatureServices,
  };

  const manifestPath = path.join(outputDir, "content-export-manifest.json");
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

  return {
    generatedAt: new Date().toISOString(),
    portalUrl: scan.portalUrl,
    outputDir,
    scan,
    manifestPath,
    exportedWebMaps,
    exportedHostedFeatureServices,
  };
}

export async function runContentImport(options: ContentImportOptions): Promise<ContentImportReport> {
  const fetchFn = options.fetchFn ?? fetch;
  const sourceDir = path.resolve(options.sourceDir);
  const outputDir = path.resolve(options.outputDir ?? path.join(sourceDir, "content-import"));
  fs.mkdirSync(outputDir, { recursive: true });

  const manifestPath = path.join(sourceDir, "content-export-manifest.json");
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Missing content export manifest: ${manifestPath}`);
  }

  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as ContentExportManifest;

  const includeHostedLayers = options.includeHostedLayers !== false;
  const includeWebMaps = options.includeWebMaps !== false;

  const importedHostedLayers: ImportedHostedLayerReport[] = [];

  if (includeHostedLayers) {
    const usedTableNames = new Set<string>();

    for (const service of manifest.hostedFeatureServices) {
      for (const layer of service.layers) {
        const baseName = layer.layerName || service.title || `${service.itemId}_${layer.layerId}`;
        const tableName = makeUniqueTableName(
          `${options.tablePrefix ?? ""}${safeFileName(baseName, "_")}`,
          usedTableNames,
        );

        try {
          const job = await runGeoservicesImportJob({
            adminBaseUrl: options.targetBaseUrl,
            adminApiKey: options.adminApiKey,
            sourceServiceUrl: service.serviceUrl,
            layerId: layer.layerId,
            tableName,
            timeoutMs: options.timeoutMs ?? DEFAULT_IMPORT_TIMEOUT_MS,
            pollIntervalMs: options.pollIntervalMs ?? DEFAULT_IMPORT_POLL_INTERVAL_MS,
            fetchFn,
            autoPublish: true,
          });

          importedHostedLayers.push({
            itemId: service.itemId,
            layerId: layer.layerId,
            tableName,
            status: "completed",
            job,
            sourceFeatureCount: layer.featureCount,
          });
        } catch (error) {
          importedHostedLayers.push({
            itemId: service.itemId,
            layerId: layer.layerId,
            tableName,
            status: "failed",
            errorMessage: error instanceof Error ? error.message : String(error),
            sourceFeatureCount: layer.featureCount,
          });
        }
      }
    }
  }

  const importedWebMaps: ImportedWebMapReport[] = [];

  if (includeWebMaps) {
    const webMapsOutDir = path.join(outputDir, "webmaps");
    fs.mkdirSync(webMapsOutDir, { recursive: true });

    for (const webMap of manifest.webMaps) {
      const inputPath = path.resolve(sourceDir, webMap.webMapPath);
      try {
        const input = JSON.parse(fs.readFileSync(inputPath, "utf8")) as WebMapJson;
        const { webMapJson, rewrittenUrlCount } = rewriteWebMapUrls(
          input,
          options.sourceUrlPrefix,
          options.targetUrlPrefix,
        );
        const parsed = parseWebMap(webMapJson);
        const manualInterventionNeeded = parsed.warnings.some((warning) =>
          MANUAL_INTERVENTION_WARNING_CODES.has(warning.code),
        );

        const outputPath = path.join(
          webMapsOutDir,
          `${safeFileName(webMap.title || webMap.itemId)}-${webMap.itemId}.honua.json`,
        );
        fs.writeFileSync(
          outputPath,
          `${JSON.stringify(
            {
              generatedAt: new Date().toISOString(),
              sourcePath: webMap.webMapPath,
              rewrittenUrlCount,
              result: parsed,
            },
            null,
            2,
          )}\n`,
          "utf8",
        );

        importedWebMaps.push({
          itemId: webMap.itemId,
          title: webMap.title,
          status: "converted",
          outputPath: path.relative(outputDir, outputPath),
          warningCount: parsed.warnings.length,
          manualInterventionNeeded,
          rewrittenUrlCount,
        });
      } catch (error) {
        importedWebMaps.push({
          itemId: webMap.itemId,
          title: webMap.title,
          status: "failed",
          errorMessage: error instanceof Error ? error.message : String(error),
        });
      }
    }
  }

  const report: ContentImportReport = {
    generatedAt: new Date().toISOString(),
    sourceDir,
    outputDir,
    targetBaseUrl: normalizeBaseUrl(options.targetBaseUrl),
    manifestPath,
    importedHostedLayers,
    importedWebMaps,
    summary: {
      hostedLayersCompleted: importedHostedLayers.filter((layer) => layer.status === "completed").length,
      hostedLayersFailed: importedHostedLayers.filter((layer) => layer.status === "failed").length,
      webMapsConverted: importedWebMaps.filter((map) => map.status === "converted").length,
      webMapsFailed: importedWebMaps.filter((map) => map.status === "failed").length,
      webMapsManualIntervention: importedWebMaps.filter((map) => map.manualInterventionNeeded === true).length,
    },
    reportPath: path.join(outputDir, "content-import-report.json"),
  };

  fs.writeFileSync(report.reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  return report;
}

export function runContentReconcile(options: ContentReconcileOptions): ContentReconcileReport {
  const sourceDir = path.resolve(options.sourceDir);
  const manifestPath = path.join(sourceDir, "content-export-manifest.json");
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Missing content export manifest: ${manifestPath}`);
  }

  const importReportPath = path.resolve(
    options.importReportPath ?? path.join(sourceDir, "content-import", "content-import-report.json"),
  );
  if (!fs.existsSync(importReportPath)) {
    throw new Error(`Missing content import report: ${importReportPath}`);
  }

  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as ContentExportManifest;
  const importReport = JSON.parse(fs.readFileSync(importReportPath, "utf8")) as ContentImportReport;

  const layerFeatureCountByKey = new Map<string, number | undefined>();
  for (const service of manifest.hostedFeatureServices) {
    for (const layer of service.layers) {
      layerFeatureCountByKey.set(makeLayerKey(service.itemId, layer.layerId), layer.featureCount);
    }
  }

  const hostedLayers: ReconciledHostedLayerReport[] = importReport.importedHostedLayers.map((layer) => {
    if (layer.status !== "completed") {
      return {
        itemId: layer.itemId,
        layerId: layer.layerId,
        tableName: layer.tableName,
        status: "fail",
        sourceFeatureCount: layerFeatureCountByKey.get(makeLayerKey(layer.itemId, layer.layerId)),
        reason: layer.errorMessage ?? "import failed",
      };
    }

    const sourceFeatureCount = layerFeatureCountByKey.get(makeLayerKey(layer.itemId, layer.layerId));
    const targetProcessedCount = layer.job?.featuresProcessed;

    if (
      sourceFeatureCount !== undefined &&
      targetProcessedCount !== undefined &&
      Number.isFinite(sourceFeatureCount) &&
      Number.isFinite(targetProcessedCount) &&
      sourceFeatureCount !== targetProcessedCount
    ) {
      return {
        itemId: layer.itemId,
        layerId: layer.layerId,
        tableName: layer.tableName,
        status: "fail",
        sourceFeatureCount,
        targetProcessedCount,
        reason: `feature count mismatch: source=${sourceFeatureCount} target=${targetProcessedCount}`,
      };
    }

    return {
      itemId: layer.itemId,
      layerId: layer.layerId,
      tableName: layer.tableName,
      status: "pass",
      sourceFeatureCount,
      targetProcessedCount,
    };
  });

  const webMaps: ReconciledWebMapReport[] = importReport.importedWebMaps.map((webMap) => {
    if (webMap.status === "failed") {
      return {
        itemId: webMap.itemId,
        title: webMap.title,
        status: "fail",
        warningCount: webMap.warningCount,
        reason: webMap.errorMessage ?? "conversion failed",
      };
    }

    if (webMap.manualInterventionNeeded) {
      return {
        itemId: webMap.itemId,
        title: webMap.title,
        status: "manual",
        warningCount: webMap.warningCount,
        reason: "manual intervention required due to unsupported properties",
      };
    }

    return {
      itemId: webMap.itemId,
      title: webMap.title,
      status: "pass",
      warningCount: webMap.warningCount,
    };
  });

  const reportPath = path.resolve(options.outputPath ?? path.join(sourceDir, "content-reconcile-report.json"));
  const report: ContentReconcileReport = {
    generatedAt: new Date().toISOString(),
    sourceDir,
    manifestPath,
    importReportPath,
    hostedLayers,
    webMaps,
    summary: {
      hostedLayersPassed: hostedLayers.filter((layer) => layer.status === "pass").length,
      hostedLayersFailed: hostedLayers.filter((layer) => layer.status === "fail").length,
      webMapsPassed: webMaps.filter((map) => map.status === "pass").length,
      webMapsManual: webMaps.filter((map) => map.status === "manual").length,
      webMapsFailed: webMaps.filter((map) => map.status === "fail").length,
    },
    reportPath,
  };

  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  return report;
}

interface PortalSearchItem {
  id: string;
  title: string;
  type: string;
  owner?: string;
  url?: string;
}

async function fetchPortalItemData(
  portalUrl: string,
  itemId: string,
  token: string | undefined,
  fetchFn: typeof fetch,
): Promise<unknown> {
  const sharingRestBase = resolvePortalSharingRestBase(portalUrl);
  const url = buildUrl(`${sharingRestBase}/content/items/${encodeURIComponent(itemId)}/data`, {
    f: "json",
    ...(token ? { token } : {}),
  });
  return fetchJson(fetchFn, url);
}

async function searchPortalItems(
  sharingRestBase: string,
  query: string,
  pageSize: number,
  token: string | undefined,
  fetchFn: typeof fetch,
): Promise<PortalSearchItem[]> {
  const results: PortalSearchItem[] = [];
  let start = 1;

  for (;;) {
    const url = buildUrl(`${sharingRestBase}/search`, {
      f: "json",
      q: query,
      sortField: "title",
      sortOrder: "asc",
      num: String(pageSize),
      start: String(start),
      ...(token ? { token } : {}),
    });

    const payload = await fetchJson(fetchFn, url);
    const payloadRecord = asRecord(payload, "Portal search response");
    const pageResults = asArray(payloadRecord.results).map((value) => asRecord(value, "Portal search result"));

    for (const item of pageResults) {
      const id = readOptionalString(item, "id");
      const title = readOptionalString(item, "title");
      const type = readOptionalString(item, "type");
      if (!id || !title || !type) {
        continue;
      }
      results.push({
        id,
        title,
        type,
        owner: readOptionalString(item, "owner"),
        url: readOptionalString(item, "url"),
      });
    }

    const nextStart = readOptionalNumber(payloadRecord, "nextStart");
    if (!nextStart || nextStart <= 0) {
      break;
    }
    start = nextStart;
  }

  return results;
}

function toContentPortalItemSummary(item: PortalSearchItem): ContentPortalItemSummary {
  return {
    id: item.id,
    title: item.title,
    type: item.type,
    owner: item.owner,
    url: item.url,
  };
}

interface ArcGisFeatureSet {
  geometryType?: string;
  spatialReference?: Record<string, unknown>;
  features: Array<{
    attributes?: Record<string, unknown>;
    geometry?: Record<string, unknown>;
  }>;
}

async function queryAllLayerFeatures(options: {
  layerUrl: string;
  token?: string;
  fetchFn: typeof fetch;
  pageSize: number;
  maxFeatures?: number;
}): Promise<ArcGisFeatureSet> {
  const features: Array<{ attributes?: Record<string, unknown>; geometry?: Record<string, unknown> }> = [];
  let geometryType: string | undefined;
  let spatialReference: Record<string, unknown> | undefined;

  let offset = 0;

  for (;;) {
    const payload = await fetchArcGisJson(
      options.fetchFn,
      `${normalizeBaseUrl(options.layerUrl)}/query`,
      options.token,
      {
        where: "1=1",
        outFields: "*",
        returnGeometry: "true",
        resultOffset: String(offset),
        resultRecordCount: String(options.pageSize),
      },
    );

    const response = asRecord(payload, "Layer query response");
    if (!geometryType) {
      geometryType = readOptionalString(response, "geometryType");
    }
    if (!spatialReference) {
      const sr = response.spatialReference;
      if (isRecord(sr)) {
        spatialReference = sr;
      }
    }

    const pageFeatures = asArray(response.features).map((value) => asRecord(value, "Feature"));
    if (pageFeatures.length === 0) {
      break;
    }

    for (const feature of pageFeatures) {
      const attributes = isRecord(feature.attributes) ? feature.attributes : undefined;
      const geometry = isRecord(feature.geometry) ? feature.geometry : undefined;
      features.push({ attributes, geometry });
    }

    if (options.maxFeatures !== undefined && features.length >= options.maxFeatures) {
      features.splice(options.maxFeatures);
      break;
    }

    const exceededTransferLimit = response.exceededTransferLimit === true;
    if (!exceededTransferLimit && pageFeatures.length < options.pageSize) {
      break;
    }

    offset += pageFeatures.length;
  }

  return {
    geometryType,
    spatialReference,
    features,
  };
}

interface GeoJsonFeature {
  type: "Feature";
  properties: Record<string, unknown>;
  geometry: {
    type: string;
    coordinates: unknown;
  } | null;
}

interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
}

type GeoJsonPosition = [number, number];
type GeoJsonPolygon = {
  type: "Polygon";
  coordinates: GeoJsonPosition[][];
};
type GeoJsonMultiPolygon = {
  type: "MultiPolygon";
  coordinates: GeoJsonPosition[][][];
};
interface PolygonRingNode {
  positions: GeoJsonPosition[];
  absoluteArea: number;
  parentIndex: number;
  depth?: number;
}

function convertEsriFeatureSetToGeoJson(featureSet: ArcGisFeatureSet): GeoJsonFeatureCollection | undefined {
  const geometryType = featureSet.geometryType;
  if (!geometryType) {
    return undefined;
  }

  const features: GeoJsonFeature[] = featureSet.features.map((feature) => ({
    type: "Feature",
    properties: feature.attributes ?? {},
    geometry: convertEsriGeometryToGeoJson(feature.geometry, geometryType),
  }));

  return {
    type: "FeatureCollection",
    features,
  };
}

function convertEsriGeometryToGeoJson(
  geometry: Record<string, unknown> | undefined,
  geometryType: string,
): { type: string; coordinates: unknown } | null {
  if (!geometry) {
    return null;
  }

  if (geometryType === "esriGeometryPoint") {
    const x = asNumber(geometry.x);
    const y = asNumber(geometry.y);
    if (x === undefined || y === undefined) {
      return null;
    }
    return { type: "Point", coordinates: [x, y] };
  }

  if (geometryType === "esriGeometryMultipoint") {
    const points = asArray(geometry.points)
      .map((value) => asCoordinatePair(value))
      .filter((value): value is [number, number] => value !== undefined);
    return { type: "MultiPoint", coordinates: points };
  }

  if (geometryType === "esriGeometryPolyline") {
    const paths = asArray(geometry.paths)
      .map((value) => asCoordinateArray(value))
      .filter((value): value is number[][] => value.length > 0);

    if (paths.length === 1) {
      return { type: "LineString", coordinates: paths[0] };
    }
    return { type: "MultiLineString", coordinates: paths };
  }

  if (geometryType === "esriGeometryPolygon") {
    const rings = asArray(geometry.rings)
      .map((value) => asCoordinateArray(value))
      .filter((value): value is number[][] => value.length > 0);
    return convertPolygonRings(rings);
  }

  return null;
}

function computeRingSignedArea(ring: readonly number[][]): number {
  if (ring.length < 3) {
    return 0;
  }

  let area = 0;
  for (let index = 0; index < ring.length; index += 1) {
    const current = ring[index];
    const next = ring[(index + 1) % ring.length];
    if (!current || !next) {
      continue;
    }
    area += current[0] * next[1] - next[0] * current[1];
  }

  return area / 2;
}

function isPointOnSegment(point: GeoJsonPosition, segmentStart: GeoJsonPosition, segmentEnd: GeoJsonPosition): boolean {
  const epsilon = 1e-9;
  const crossProduct =
    (point[0] - segmentStart[0]) * (segmentEnd[1] - segmentStart[1]) -
    (point[1] - segmentStart[1]) * (segmentEnd[0] - segmentStart[0]);

  if (Math.abs(crossProduct) > epsilon) {
    return false;
  }

  const dotProduct =
    (point[0] - segmentStart[0]) * (segmentEnd[0] - segmentStart[0]) +
    (point[1] - segmentStart[1]) * (segmentEnd[1] - segmentStart[1]);
  if (dotProduct < -epsilon) {
    return false;
  }

  const segmentLengthSquared =
    (segmentEnd[0] - segmentStart[0]) * (segmentEnd[0] - segmentStart[0]) +
    (segmentEnd[1] - segmentStart[1]) * (segmentEnd[1] - segmentStart[1]);

  return dotProduct - segmentLengthSquared <= epsilon;
}

function isPointInsideRing(point: GeoJsonPosition, ring: readonly number[][]): boolean {
  if (ring.length < 3) {
    return false;
  }

  let isInside = false;
  for (let index = 0, previousIndex = ring.length - 1; index < ring.length; previousIndex = index, index += 1) {
    const current = ring[index] as GeoJsonPosition | undefined;
    const previous = ring[previousIndex] as GeoJsonPosition | undefined;
    if (!current || !previous) {
      continue;
    }

    if (isPointOnSegment(point, previous, current)) {
      return true;
    }

    const intersects =
      current[1] > point[1] !== previous[1] > point[1] &&
      point[0] < ((previous[0] - current[0]) * (point[1] - current[1])) / (previous[1] - current[1]) + current[0];
    if (intersects) {
      isInside = !isInside;
    }
  }

  return isInside;
}

function findContainingRingIndex(nodes: readonly PolygonRingNode[], currentIndex: number): number {
  const current = nodes[currentIndex];
  const samplePoint = current?.positions[0];
  if (!samplePoint) {
    return -1;
  }

  let containingRingIndex = -1;
  let smallestContainingArea = Number.POSITIVE_INFINITY;

  for (let index = 0; index < nodes.length; index += 1) {
    if (index === currentIndex) {
      continue;
    }

    const candidate = nodes[index];
    if (
      !candidate ||
      candidate.absoluteArea <= current.absoluteArea ||
      !isPointInsideRing(samplePoint, candidate.positions)
    ) {
      continue;
    }

    if (candidate.absoluteArea < smallestContainingArea) {
      smallestContainingArea = candidate.absoluteArea;
      containingRingIndex = index;
    }
  }

  return containingRingIndex;
}

function createPolygonRingNodes(rings: readonly number[][][]): PolygonRingNode[] {
  const nodes = rings.map((ring): PolygonRingNode => {
    const positions = ring as GeoJsonPosition[];
    const area = computeRingSignedArea(positions);
    return {
      positions,
      absoluteArea: Math.abs(area),
      parentIndex: -1,
    };
  });

  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    if (!node || node.positions.length < 3) {
      continue;
    }

    node.parentIndex = findContainingRingIndex(nodes, index);
  }

  return nodes;
}

function getRingDepth(nodes: PolygonRingNode[], index: number): number {
  const node = nodes[index];
  if (!node) {
    return 0;
  }
  if (node.depth !== undefined) {
    return node.depth;
  }

  node.depth = node.parentIndex < 0 ? 0 : getRingDepth(nodes, node.parentIndex) + 1;
  return node.depth;
}

function findExteriorAncestorIndex(nodes: PolygonRingNode[], index: number): number {
  let currentIndex = nodes[index]?.parentIndex ?? -1;
  while (currentIndex >= 0) {
    if (getRingDepth(nodes, currentIndex) % 2 === 0) {
      return currentIndex;
    }
    currentIndex = nodes[currentIndex]?.parentIndex ?? -1;
  }

  return -1;
}

function convertPolygonRings(rings: readonly number[][][]): GeoJsonPolygon | GeoJsonMultiPolygon {
  const nodes = createPolygonRingNodes(rings);
  const polygons: GeoJsonPosition[][][] = [];
  const polygonByRingIndex = new Map<number, number>();

  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    if (!node) {
      continue;
    }

    if (getRingDepth(nodes, index) % 2 === 0) {
      polygonByRingIndex.set(index, polygons.length);
      polygons.push([node.positions]);
    }
  }

  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    if (!node || getRingDepth(nodes, index) % 2 === 0) {
      continue;
    }

    const exteriorAncestorIndex = findExteriorAncestorIndex(nodes, index);
    const polygonIndex = polygonByRingIndex.get(exteriorAncestorIndex);
    if (polygonIndex === undefined) {
      polygonByRingIndex.set(index, polygons.length);
      polygons.push([node.positions]);
      continue;
    }

    polygons[polygonIndex]?.push(node.positions);
  }

  return polygons.length === 1
    ? {
        type: "Polygon",
        coordinates: toGeoJsonPolygonCoordinates(polygons[0] ?? []),
      }
    : {
        type: "MultiPolygon",
        coordinates: polygons.map(toGeoJsonPolygonCoordinates),
      };
}

function toGeoJsonPolygonCoordinates(polygon: readonly GeoJsonPosition[][]): GeoJsonPosition[][] {
  return polygon.map((ring, index) => rewindRingForGeoJson(ring, index === 0));
}

function rewindRingForGeoJson(ring: readonly GeoJsonPosition[], exterior: boolean): GeoJsonPosition[] {
  const coordinates = ring.map((coordinate): GeoJsonPosition => [coordinate[0], coordinate[1]]);
  const area = computeRingSignedArea(coordinates);
  if (area === 0) {
    return coordinates;
  }

  const hasExpectedWinding = exterior ? area > 0 : area < 0;
  return hasExpectedWinding ? coordinates : coordinates.reverse();
}

function asCoordinatePair(value: unknown): [number, number] | undefined {
  if (!Array.isArray(value) || value.length < 2) {
    return undefined;
  }
  const x = asNumber(value[0]);
  const y = asNumber(value[1]);
  if (x === undefined || y === undefined) {
    return undefined;
  }
  return [x, y];
}

function asCoordinateArray(value: unknown): number[][] {
  if (!Array.isArray(value)) {
    return [];
  }
  const coords: number[][] = [];
  for (const item of value) {
    const pair = asCoordinatePair(item);
    if (pair) {
      coords.push(pair);
    }
  }
  return coords;
}

async function fetchArcGisJson(
  fetchFn: typeof fetch,
  url: string,
  token?: string,
  extraParams?: Record<string, string>,
): Promise<unknown> {
  const requestUrl = buildUrl(url, {
    f: "json",
    ...(token ? { token } : {}),
    ...(extraParams ?? {}),
  });

  return fetchJson(fetchFn, requestUrl);
}

async function fetchJson(fetchFn: typeof fetch, url: string): Promise<unknown> {
  const response = await fetchFn(url, {
    method: "GET",
    headers: {
      Accept: "application/json",
      Connection: "close",
    },
  });

  const text = await response.text();
  let body: unknown = {};
  if (text.length > 0) {
    try {
      body = JSON.parse(text);
    } catch {
      body = {};
    }
  }

  if (!response.ok) {
    throw new Error(
      `HTTP ${response.status} for ${redactSensitiveUrl(url)}: ${redactSensitiveText(text).slice(0, 300)}`,
    );
  }

  if (isRecord(body) && isRecord(body.error)) {
    const code = readOptionalNumber(body.error, "code");
    const message = redactSensitiveText(readOptionalString(body.error, "message") ?? "ArcGIS error");
    throw new Error(`ArcGIS error${code ? ` ${code}` : ""}: ${message}`);
  }

  return body;
}

function resolvePortalSharingRestBase(portalUrl: string): string {
  const normalized = normalizeBaseUrl(portalUrl);
  const lower = normalized.toLowerCase();
  if (lower.endsWith("/sharing/rest")) {
    return normalized;
  }
  if (lower.includes("/sharing/rest/")) {
    return normalized.slice(0, lower.indexOf("/sharing/rest/") + "/sharing/rest".length);
  }
  return `${normalized}/sharing/rest`;
}

function quotePortalQueryValue(value: string): string {
  return `\"${value.replaceAll('"', '\\"')}\"`;
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

function redactSensitiveUrl(url: string): string {
  try {
    const parsed = new URL(url);
    for (const key of Array.from(parsed.searchParams.keys())) {
      if (isSensitiveKey(key)) {
        parsed.searchParams.set(key, REDACTED_SECRET);
      }
    }
    return parsed.toString();
  } catch {
    return redactSensitiveText(url);
  }
}

function redactSensitiveText(value: string): string {
  return value
    .replace(/([?&](?:token|api[_-]?key|access[_-]?token|auth[_-]?token)=)[^&#\s]*/gi, `$1${REDACTED_SECRET}`)
    .replace(/("(?:token|api[_-]?key|access[_-]?token|auth[_-]?token)"\s*:\s*")([^"]*)(")/gi, `$1${REDACTED_SECRET}$3`)
    .replace(/((?:token|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[=:]\s*)([^,\s]+)/gi, `$1${REDACTED_SECRET}`);
}

function isSensitiveKey(key: string): boolean {
  return /token|api[_-]?key|access[_-]?token|auth[_-]?token/i.test(key);
}

function buildUrl(base: string, params: Record<string, string>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    query.set(key, value);
  }

  return `${base}${base.includes("?") ? "&" : "?"}${query.toString()}`;
}

function makeUniqueTableName(baseName: string, used: Set<string>): string {
  const normalizedBase =
    baseName
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 48) || "layer";
  let candidate = normalizedBase;
  let suffix = 1;
  while (used.has(candidate)) {
    suffix += 1;
    const suffixValue = `_${suffix}`;
    candidate = `${normalizedBase.slice(0, Math.max(1, 48 - suffixValue.length))}${suffixValue}`;
  }
  used.add(candidate);
  return candidate;
}

function safeFileName(value: string, separator = "-"): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, separator)
      .replace(new RegExp(`${separator}+`, "g"), separator)
      .replace(new RegExp(`^${separator}+|${separator}+$`, "g"), "")
      .slice(0, 64) || "item"
  );
}

function rewriteWebMapUrls(
  input: WebMapJson,
  sourcePrefix: string | undefined,
  targetPrefix: string | undefined,
): { webMapJson: WebMapJson; rewrittenUrlCount: number } {
  const webMapJson = structuredClone(input);
  if (!sourcePrefix || !targetPrefix) {
    return { webMapJson, rewrittenUrlCount: 0 };
  }

  let rewrittenUrlCount = 0;
  const rewrite = (url: unknown): string | undefined => {
    if (typeof url !== "string") {
      return undefined;
    }
    if (!url.startsWith(sourcePrefix)) {
      return undefined;
    }
    return `${targetPrefix}${url.slice(sourcePrefix.length)}`;
  };

  for (const opLayer of webMapJson.operationalLayers ?? []) {
    const nextUrl = rewrite(opLayer.url);
    if (nextUrl) {
      opLayer.url = nextUrl;
      rewrittenUrlCount += 1;
    }
  }

  for (const baseMapLayer of webMapJson.baseMap?.baseMapLayers ?? []) {
    const nextUrl = rewrite(baseMapLayer.url);
    if (nextUrl) {
      baseMapLayer.url = nextUrl;
      rewrittenUrlCount += 1;
    }
  }

  return { webMapJson, rewrittenUrlCount };
}

function makeLayerKey(itemId: string, layerId: number): string {
  return `${itemId}:${layerId}`;
}

function asRecord(value: unknown, context: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`${context} was not a JSON object.`);
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function readRequiredNumber(source: Record<string, unknown>, key: string): number {
  const value = asNumber(source[key]);
  if (value === undefined) {
    throw new Error(`Expected \"${key}\" to be a number.`);
  }
  return value;
}

function readOptionalNumber(source: Record<string, unknown>, key: string): number | undefined {
  return asNumber(source[key]);
}

function readOptionalString(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key];
  return typeof value === "string" && value.length > 0 ? value : undefined;
}
