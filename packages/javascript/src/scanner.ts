import fs from "node:fs";
import path from "node:path";

const EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]);
const SKIP = new Set(["node_modules", "dist", ".git"]);

export interface ImportHit { file: string; modulePath: string; importClause: string; symbols: string[] }
export interface ArcGisScanReport {
  rootDir: string; filesScanned: number; filesWithArcGisImports: number;
  imports: ImportHit[]; filesWithEsriLeafletImports: number; esriLeafletImportCount: number;
  esriLeafletImports: ImportHit[]; symbolUsageCounts: Record<string, number>; flags: string[];
}

export function collectSourceFiles(rootDir: string): string[] {
  const result: string[] = []; const queue = [path.resolve(rootDir)];
  while (queue.length) {
    const current = queue.pop(); if (!current) continue;
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory() && !SKIP.has(entry.name)) queue.push(full);
      else if (entry.isFile() && EXTENSIONS.has(path.extname(entry.name))) result.push(full);
    }
  }
  return result.sort();
}

export function scanArcGisUsage(rootDir: string): ArcGisScanReport {
  const imports: ImportHit[] = []; const esriLeafletImports: ImportHit[] = [];
  const flags = new Set<string>(); const symbolUsageCounts: Record<string, number> = {};
  const files = collectSourceFiles(rootDir);
  for (const file of files) {
    const source = fs.readFileSync(file, "utf8");
    const hits = findImports(source, file, /@arcgis\/core(?:\/[^"']+)?/);
    const leaflet = findImports(source, file, /(?:esri-leaflet|@esri\/leaflet)(?:\/[^"']+)?/);
    imports.push(...hits); esriLeafletImports.push(...leaflet);
    if (hits.some((hit) => hit.importClause.startsWith("export "))) flags.add("arcgis-reexports-detected");
    if (hits.some((hit) => hit.modulePath === "@arcgis/core")) flags.add("arcgis-barrel-imports-detected");
    if (leaflet.length) flags.add("esri-leaflet-imports-detected");
    if (/geometryEngine|applyEdits|FeatureTable/.test(source)) flags.add("manual-review-required");
    for (const hit of hits) for (const symbol of hit.symbols) {
      const count = source.match(new RegExp(`\\b${escapeRegExp(symbol)}\\b`, "g"))?.length ?? 0;
      symbolUsageCounts[symbol] = (symbolUsageCounts[symbol] ?? 0) + count;
    }
  }
  return { rootDir: path.resolve(rootDir), filesScanned: files.length,
    filesWithArcGisImports: new Set(imports.map((item) => item.file)).size, imports,
    filesWithEsriLeafletImports: new Set(esriLeafletImports.map((item) => item.file)).size,
    esriLeafletImportCount: esriLeafletImports.length, esriLeafletImports, symbolUsageCounts,
    flags: [...flags].sort() };
}

function findImports(source: string, file: string, modulePattern: RegExp): ImportHit[] {
  const results: ImportHit[] = []; const matcher = /((?:import|export)\s+(?:type\s+)?[^;\n]+?\s+from\s+|import\s*)["']([^"']+)["']/g;
  for (const match of source.matchAll(matcher)) if (modulePattern.test(match[2] ?? "")) {
    const clause = `${match[1] ?? ""}${match[2] ?? ""}`;
    const symbols = [...(clause.matchAll(/\b([A-Z][A-Za-z0-9_]*)\b/g))].map((item) => item[1]!).filter((x) => x !== "from");
    results.push({ file, modulePath: match[2]!, importClause: clause, symbols });
  }
  return results;
}
function escapeRegExp(value: string): string { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
export function summarizeArcGisScan(report: ArcGisScanReport): string {
  return `filesScanned=${report.filesScanned} filesWithArcGisImports=${report.filesWithArcGisImports} importCount=${report.imports.length} esriLeafletImportCount=${report.esriLeafletImportCount} flags=[${report.flags.join(",") || "none"}]`;
}
