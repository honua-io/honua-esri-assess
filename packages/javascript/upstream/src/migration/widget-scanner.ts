import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import {
  ARCGIS_WIDGET_DEPRECATION_RELEASE,
  ARCGIS_WIDGET_REMOVAL_RELEASE,
  ARCGIS_WIDGET_REMOVAL_TIMEFRAME,
  WIDGET_DISPOSITION_DATA_VERSION,
  WIDGET_SURVIVAL_GUIDE_PATH,
  type WidgetDispositionKind,
  type WidgetMigrationBucket,
  getWidgetDisposition,
  widgetMigrationBucket,
  widgetModulePathInfo,
  widgetSurvivalGuideAnchor,
} from "./widget-dispositions.js";

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"]);
const SKIP_DIRS = new Set(["node_modules", "dist", ".git"]);

export type WidgetImportStyle = "esm-import" | "esm-dynamic-import" | "cjs-require" | "amd-require" | "arcgis-import";

export interface WidgetUsageHit {
  /** Path relative to the scan root, POSIX separators. */
  file: string;
  /** 1-based line of the module specifier string literal. */
  line: number;
  widget: string;
  modulePath: string;
  importStyle: WidgetImportStyle;
  /** True when the specifier addresses a widget support module (e.g. a ViewModel). */
  supportModule: boolean;
}

export interface WidgetScanResult {
  rootDir: string;
  filesScanned: number;
  filesWithWidgetUsage: number;
  hits: WidgetUsageHit[];
}

export interface WidgetReadinessRow {
  widget: string;
  /**
   * True for rows aggregating widget *support*-module imports (e.g.
   * `@arcgis/core/widgets/Search/SearchViewModel`). The codemod only rewrites
   * the exact widget module, so these rows never inherit the widget's
   * disposition and always count as manual.
   */
  supportModule: boolean;
  disposition: WidgetDispositionKind | "unknown" | "support-module";
  bucket: WidgetMigrationBucket;
  target: string;
  /** Repo-relative deep link into the generated survival guide. */
  guideLink: string;
  count: number;
  sites: readonly WidgetUsageHit[];
}

export interface WidgetReadinessSummary {
  totalSites: number;
  automatedSites: number;
  assistedSites: number;
  manualSites: number;
  automatedWidgets: number;
  assistedWidgets: number;
  manualWidgets: number;
  /** Share of usage sites with an automated disposition, 0-100. 100 when no widgets are used. */
  automatedPct: number;
}

export interface WidgetReadinessReport {
  rootDir: string;
  dispositionDataVersion: string;
  deprecationRelease: string;
  removalRelease: string;
  removalTimeframe: string;
  filesScanned: number;
  filesWithWidgetUsage: number;
  widgets: WidgetReadinessRow[];
  summary: WidgetReadinessSummary;
  summaryLine: string;
}

export interface WidgetGateEvaluation {
  gatePct: number;
  automatedPct: number;
  passed: boolean;
  failures: string[];
}

export function scanWidgetUsage(rootDir: string): WidgetScanResult {
  const absoluteRoot = path.resolve(rootDir);
  const files = collectSourceFiles(absoluteRoot);
  const hits: WidgetUsageHit[] = [];

  for (const file of files) {
    const source = fs.readFileSync(file, "utf8");
    if (!source.includes("widgets/")) {
      continue;
    }
    const relativeFile = path.relative(absoluteRoot, file).split(path.sep).join("/");
    hits.push(...findWidgetUsageInSource(source, file, relativeFile));
  }

  hits.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line || a.modulePath.localeCompare(b.modulePath));

  return {
    rootDir: absoluteRoot,
    filesScanned: files.length,
    filesWithWidgetUsage: new Set(hits.map((hit) => hit.file)).size,
    hits,
  };
}

export function buildWidgetReadinessReport(scan: WidgetScanResult): WidgetReadinessReport {
  const rowsByKey = new Map<string, WidgetUsageHit[]>();
  for (const hit of scan.hits) {
    const key = `${hit.widget}::${hit.supportModule ? "support" : "widget"}`;
    const bucket = rowsByKey.get(key);
    if (bucket) {
      bucket.push(hit);
    } else {
      rowsByKey.set(key, [hit]);
    }
  }

  const widgets: WidgetReadinessRow[] = [];
  for (const sites of rowsByKey.values()) {
    const { widget, supportModule } = sites[0];
    const disposition = getWidgetDisposition(widget);
    if (supportModule) {
      // The codemod rewrites only the exact widget module; support-module
      // imports (ViewModels, sub-components) stay unmigrated, so they must
      // not inherit the widget's disposition or count toward the gate.
      widgets.push({
        widget,
        supportModule: true,
        disposition: "support-module",
        bucket: "manual",
        target:
          `Support-module import ? honua-migrate only rewrites the root ${widget} widget module; ` +
          `migrate these by hand (root ${widget} disposition: ${disposition?.disposition ?? "unknown"}).`,
        guideLink: `${WIDGET_SURVIVAL_GUIDE_PATH}#${widgetSurvivalGuideAnchor(widget)}`,
        count: sites.length,
        sites,
      });
      continue;
    }
    widgets.push({
      widget,
      supportModule: false,
      disposition: disposition?.disposition ?? "unknown",
      bucket: disposition ? widgetMigrationBucket(disposition.disposition) : "manual",
      target: disposition
        ? disposition.target
        : `Not in widget-disposition data v${WIDGET_DISPOSITION_DATA_VERSION}; treat as manual and report it.`,
      guideLink: `${WIDGET_SURVIVAL_GUIDE_PATH}#${widgetSurvivalGuideAnchor(widget)}`,
      count: sites.length,
      sites,
    });
  }
  widgets.sort(
    (a, b) =>
      b.count - a.count || a.widget.localeCompare(b.widget) || Number(a.supportModule) - Number(b.supportModule),
  );

  const summary = summarizeWidgetRows(widgets);
  return {
    rootDir: scan.rootDir,
    dispositionDataVersion: WIDGET_DISPOSITION_DATA_VERSION,
    deprecationRelease: ARCGIS_WIDGET_DEPRECATION_RELEASE,
    removalRelease: ARCGIS_WIDGET_REMOVAL_RELEASE,
    removalTimeframe: ARCGIS_WIDGET_REMOVAL_TIMEFRAME,
    filesScanned: scan.filesScanned,
    filesWithWidgetUsage: scan.filesWithWidgetUsage,
    widgets,
    summary,
    summaryLine: buildSummaryLine(summary),
  };
}

export function evaluateWidgetGate(report: WidgetReadinessReport, gatePct: number): WidgetGateEvaluation {
  const automatedPct = report.summary.automatedPct;
  const failures: string[] = [];
  if (automatedPct < gatePct) {
    failures.push(
      `automated widget-migration share ${automatedPct.toFixed(1)}% is below the --gate threshold ${gatePct.toFixed(1)}%`,
    );
  }
  return { gatePct, automatedPct, passed: failures.length === 0, failures };
}

export function formatWidgetReadinessTable(report: WidgetReadinessReport): string {
  const lines: string[] = [];
  lines.push(
    `ArcGIS widget readiness ? deprecated at ${report.deprecationRelease}, removed at ${report.removalRelease} (${report.removalTimeframe})`,
  );
  lines.push(
    `filesScanned=${report.filesScanned} filesWithWidgetUsage=${report.filesWithWidgetUsage} widgetUsageSites=${report.summary.totalSites} dispositionData=v${report.dispositionDataVersion}`,
  );
  lines.push("");
  if (report.widgets.length === 0) {
    lines.push("No classic ArcGIS widget usage detected.");
  } else {
    const header = ["widget", "sites", "files", "disposition", "target"];
    const rows = report.widgets.map((row) => [
      rowDisplayName(row),
      String(row.count),
      String(new Set(row.sites.map((site) => site.file)).size),
      row.disposition,
      row.target,
    ]);
    const widths = header.map((column, index) => Math.max(column.length, ...rows.map((row) => row[index].length)));
    const renderRow = (cells: string[]): string =>
      cells
        .map((cell, index) => cell.padEnd(widths[index]))
        .join("  ")
        .trimEnd();
    lines.push(renderRow(header));
    lines.push(renderRow(widths.map((width) => "-".repeat(width))));
    for (const row of rows) {
      lines.push(renderRow(row));
    }
  }
  lines.push("");
  lines.push(report.summaryLine);
  lines.push(`Per-widget guidance: ${WIDGET_SURVIVAL_GUIDE_PATH}`);
  return lines.join("\n");
}

export function formatWidgetReadinessMarkdown(report: WidgetReadinessReport): string {
  const lines: string[] = [];
  lines.push("# ArcGIS widget readiness report");
  lines.push("");
  lines.push(
    `Classic ArcGIS JS widgets are deprecated at ${report.deprecationRelease} and are removed at ` +
      `${report.removalRelease} (${report.removalTimeframe}). Disposition data v${report.dispositionDataVersion}.`,
  );
  lines.push("");
  lines.push(`- Files scanned: ${report.filesScanned}`);
  lines.push(`- Files with widget usage: ${report.filesWithWidgetUsage}`);
  lines.push(`- Widget usage sites: ${report.summary.totalSites}`);
  lines.push("");
  lines.push(`${report.summaryLine}`);
  lines.push("");
  lines.push("| Widget | Sites | Disposition | Target |");
  lines.push("| --- | --- | --- | --- |");
  for (const row of report.widgets) {
    lines.push(
      `| [${rowDisplayName(row)}](${row.guideLink}) | ${row.count} | \`${row.disposition}\` | ${escapeMarkdownTableCell(row.target)} |`,
    );
  }
  if (report.widgets.length === 0) {
    lines.push("| _none detected_ | 0 | ? | ? |");
  }
  lines.push("");
  if (report.widgets.length > 0) {
    lines.push("## File inventory");
    lines.push("");
    for (const row of report.widgets) {
      lines.push(`### ${rowDisplayName(row)}`);
      lines.push("");
      for (const site of row.sites) {
        lines.push(`- \`${site.file}:${site.line}\` ? \`${site.modulePath}\` (${site.importStyle})`);
      }
      lines.push("");
    }
  }
  return `${lines.join("\n").trimEnd()}\n`;
}

function summarizeWidgetRows(widgets: readonly WidgetReadinessRow[]): WidgetReadinessSummary {
  let automatedSites = 0;
  let assistedSites = 0;
  let manualSites = 0;
  let automatedWidgets = 0;
  let assistedWidgets = 0;
  let manualWidgets = 0;
  for (const row of widgets) {
    if (row.bucket === "automated") {
      automatedSites += row.count;
      automatedWidgets += 1;
    } else if (row.bucket === "assisted") {
      assistedSites += row.count;
      assistedWidgets += 1;
    } else {
      manualSites += row.count;
      manualWidgets += 1;
    }
  }
  const totalSites = automatedSites + assistedSites + manualSites;
  return {
    totalSites,
    automatedSites,
    assistedSites,
    manualSites,
    automatedWidgets,
    assistedWidgets,
    manualWidgets,
    automatedPct: totalSites === 0 ? 100 : (automatedSites / totalSites) * 100,
  };
}

function buildSummaryLine(summary: WidgetReadinessSummary): string {
  const split =
    `${summary.automatedSites} automated / ${summary.assistedSites} assisted / ${summary.manualSites} manual ` +
    `of ${summary.totalSites} widget usage sites (${summary.automatedPct.toFixed(1)}% automated)`;
  return (
    `${split}. Every classic ArcGIS JS widget is deprecated at ${ARCGIS_WIDGET_DEPRECATION_RELEASE} and is ` +
    `removed at ${ARCGIS_WIDGET_REMOVAL_RELEASE} ? ${ARCGIS_WIDGET_REMOVAL_TIMEFRAME}.`
  );
}

function rowDisplayName(row: WidgetReadinessRow): string {
  return row.supportModule ? `${row.widget} (support modules)` : row.widget;
}

function escapeMarkdownTableCell(value: string): string {
  // Escape backslashes first so pre-existing backslashes cannot combine with
  // the pipe escaping into ambiguous sequences (CodeQL js/incomplete-sanitization).
  return value.replace(/\\/g, "\\\\").replace(/\|/g, "\\|");
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
        continue;
      }
      if (SOURCE_EXTENSIONS.has(path.extname(entry.name))) {
        result.push(fullPath);
      }
    }
  }

  return result;
}

function scriptKindForFile(file: string): ts.ScriptKind {
  const extension = path.extname(file);
  if (extension === ".ts" || extension === ".mts" || extension === ".cts") return ts.ScriptKind.TS;
  if (extension === ".tsx") return ts.ScriptKind.TSX;
  if (extension === ".jsx") return ts.ScriptKind.JSX;
  return ts.ScriptKind.JS;
}

function findWidgetUsageInSource(source: string, file: string, relativeFile: string): WidgetUsageHit[] {
  const sourceFile = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, scriptKindForFile(file));
  const hits: WidgetUsageHit[] = [];

  const record = (literal: ts.StringLiteralLike, importStyle: WidgetImportStyle): void => {
    const moduleInfo = widgetModulePathInfo(literal.text);
    if (!moduleInfo) {
      return;
    }
    const { line } = sourceFile.getLineAndCharacterOfPosition(literal.getStart(sourceFile));
    hits.push({
      file: relativeFile,
      line: line + 1,
      widget: moduleInfo.widget,
      modulePath: literal.text,
      importStyle,
      supportModule: moduleInfo.supportModule,
    });
  };

  const recordArrayElements = (array: ts.ArrayLiteralExpression, importStyle: WidgetImportStyle): void => {
    for (const element of array.elements) {
      if (ts.isStringLiteralLike(element)) {
        record(element, importStyle);
      }
    }
  };

  const visit = (node: ts.Node): void => {
    if (
      (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
      node.moduleSpecifier !== undefined &&
      ts.isStringLiteralLike(node.moduleSpecifier)
    ) {
      record(node.moduleSpecifier, "esm-import");
    } else if (ts.isCallExpression(node)) {
      const firstArg = node.arguments.length > 0 ? node.arguments[0] : undefined;
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        if (firstArg && ts.isStringLiteralLike(firstArg)) {
          record(firstArg, "esm-dynamic-import");
        }
      } else if (ts.isIdentifier(node.expression)) {
        const callee = node.expression.text;
        if ((callee === "require" || callee === "define") && firstArg && ts.isArrayLiteralExpression(firstArg)) {
          recordArrayElements(firstArg, "amd-require");
        } else if (callee === "require" && firstArg && ts.isStringLiteralLike(firstArg)) {
          record(firstArg, "cjs-require");
        }
      } else if (
        ts.isPropertyAccessExpression(node.expression) &&
        ts.isIdentifier(node.expression.expression) &&
        node.expression.expression.text === "$arcgis" &&
        node.expression.name.text === "import"
      ) {
        if (firstArg && ts.isStringLiteralLike(firstArg)) {
          record(firstArg, "arcgis-import");
        } else if (firstArg && ts.isArrayLiteralExpression(firstArg)) {
          recordArrayElements(firstArg, "arcgis-import");
        }
      }
    }
    ts.forEachChild(node, visit);
  };

  visit(sourceFile);
  return hits;
}
