import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  ARCGIS_WIDGET_REMOVAL_RELEASE,
  ARCGIS_WIDGET_REMOVAL_TIMEFRAME,
  WIDGET_DISPOSITIONS,
  widgetModulePathInfo,
  widgetNameFromModulePath,
} from "../src/migration/widget-dispositions.js";
import {
  buildWidgetReadinessReport,
  evaluateWidgetGate,
  formatWidgetReadinessMarkdown,
  formatWidgetReadinessTable,
  scanWidgetUsage,
} from "../src/migration/widget-scanner.js";

const FIXTURE_ROOT = path.join(process.cwd(), "test", "fixtures", "esri-widget-cliff-app");

const tempDirs: string[] = [];

function makeTempProject(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "honua-widget-scan-"));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

describe("widgetNameFromModulePath", () => {
  it("extracts widget names from ESM and AMD specifiers", () => {
    expect(widgetNameFromModulePath("@arcgis/core/widgets/Legend")).toBe("Legend");
    expect(widgetNameFromModulePath("@arcgis/core/widgets/Legend.js")).toBe("Legend");
    expect(widgetNameFromModulePath("@arcgis/core/widgets/Search/SearchViewModel")).toBe("Search");
    expect(widgetModulePathInfo("@arcgis/core/widgets/Search/SearchViewModel")).toEqual({
      widget: "Search",
      supportModule: true,
    });
    expect(widgetModulePathInfo("esri/widgets/Legend")).toEqual({ widget: "Legend", supportModule: false });
    expect(widgetNameFromModulePath("esri/widgets/TimeSlider")).toBe("TimeSlider");
    expect(widgetNameFromModulePath("@arcgis/core/layers/FeatureLayer")).toBeUndefined();
    expect(widgetNameFromModulePath("esri/Map")).toBeUndefined();
  });
});

describe("scanWidgetUsage", () => {
  it("detects ESM widget imports with file and line", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "app.ts"),
      [
        "import MapView from '@arcgis/core/views/MapView';",
        "import Legend from '@arcgis/core/widgets/Legend';",
        "import Expand from '@arcgis/core/widgets/Expand.js';",
        "export { default as Search } from '@arcgis/core/widgets/Search';",
        "void MapView; void Legend; void Expand;",
      ].join("\n"),
      "utf8",
    );

    const scan = scanWidgetUsage(root);
    expect(scan.filesScanned).toBe(1);
    expect(scan.filesWithWidgetUsage).toBe(1);
    expect(scan.hits).toEqual([
      {
        file: "app.ts",
        line: 2,
        widget: "Legend",
        modulePath: "@arcgis/core/widgets/Legend",
        importStyle: "esm-import",
        supportModule: false,
      },
      {
        file: "app.ts",
        line: 3,
        widget: "Expand",
        modulePath: "@arcgis/core/widgets/Expand.js",
        importStyle: "esm-import",
        supportModule: false,
      },
      {
        file: "app.ts",
        line: 4,
        widget: "Search",
        modulePath: "@arcgis/core/widgets/Search",
        importStyle: "esm-import",
        supportModule: false,
      },
    ]);
  });

  it("detects AMD require and define string arrays", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "legacy.js"),
      [
        "require(['esri/Map', 'esri/widgets/LayerList', 'esri/widgets/Directions'], function (Map, LayerList, Directions) {",
        "  void new LayerList({}); void new Directions({});",
        "});",
        "define(['esri/widgets/BasemapGallery'], function (BasemapGallery) {",
        "  return BasemapGallery;",
        "});",
      ].join("\n"),
      "utf8",
    );

    const scan = scanWidgetUsage(root);
    expect(scan.hits).toEqual([
      {
        file: "legacy.js",
        line: 1,
        widget: "Directions",
        modulePath: "esri/widgets/Directions",
        importStyle: "amd-require",
        supportModule: false,
      },
      {
        file: "legacy.js",
        line: 1,
        widget: "LayerList",
        modulePath: "esri/widgets/LayerList",
        importStyle: "amd-require",
        supportModule: false,
      },
      {
        file: "legacy.js",
        line: 4,
        widget: "BasemapGallery",
        modulePath: "esri/widgets/BasemapGallery",
        importStyle: "amd-require",
        supportModule: false,
      },
    ]);
  });

  it("detects dynamic $arcgis.import string and array specifiers", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "cdn.js"),
      [
        "async function boot(view) {",
        "  const Daylight = await $arcgis.import('@arcgis/core/widgets/Daylight.js');",
        "  const [Sketch] = await $arcgis.import(['esri/widgets/Sketch', 'esri/layers/GraphicsLayer']);",
        "  void new Daylight({ view }); void new Sketch({ view });",
        "}",
        "export { boot };",
      ].join("\n"),
      "utf8",
    );

    const scan = scanWidgetUsage(root);
    expect(scan.hits).toEqual([
      {
        file: "cdn.js",
        line: 2,
        widget: "Daylight",
        modulePath: "@arcgis/core/widgets/Daylight.js",
        importStyle: "arcgis-import",
        supportModule: false,
      },
      {
        file: "cdn.js",
        line: 3,
        widget: "Sketch",
        modulePath: "esri/widgets/Sketch",
        importStyle: "arcgis-import",
        supportModule: false,
      },
    ]);
  });

  it("detects dynamic import() and CommonJS require specifiers", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "mixed.cjs"),
      [
        "const Legend = require('@arcgis/core/widgets/Legend').default;",
        "async function lazy() {",
        "  const { default: Print } = await import('@arcgis/core/widgets/Print');",
        "  return { Legend, Print };",
        "}",
        "module.exports = { lazy };",
      ].join("\n"),
      "utf8",
    );

    const scan = scanWidgetUsage(root);
    expect(scan.hits).toEqual([
      {
        file: "mixed.cjs",
        line: 1,
        widget: "Legend",
        modulePath: "@arcgis/core/widgets/Legend",
        importStyle: "cjs-require",
        supportModule: false,
      },
      {
        file: "mixed.cjs",
        line: 3,
        widget: "Print",
        modulePath: "@arcgis/core/widgets/Print",
        importStyle: "esm-dynamic-import",
        supportModule: false,
      },
    ]);
  });

  it("detects widget imports in NodeNext .mts and .cts sources", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "modern.mts"),
      "import Legend from '@arcgis/core/widgets/Legend';" + "\n" + "void Legend;",
      "utf8",
    );
    fs.writeFileSync(
      path.join(root, "legacy.cts"),
      "const Print = require('@arcgis/core/widgets/Print').default;" + "\n" + "module.exports = { Print };",
      "utf8",
    );

    const scan = scanWidgetUsage(root);
    expect(scan.filesScanned).toBe(2);
    expect(scan.hits).toEqual([
      {
        file: "legacy.cts",
        line: 1,
        widget: "Print",
        modulePath: "@arcgis/core/widgets/Print",
        importStyle: "cjs-require",
        supportModule: false,
      },
      {
        file: "modern.mts",
        line: 1,
        widget: "Legend",
        modulePath: "@arcgis/core/widgets/Legend",
        importStyle: "esm-import",
        supportModule: false,
      },
    ]);
  });

  it("ignores non-widget modules and skips node_modules", () => {
    const root = makeTempProject();
    fs.mkdirSync(path.join(root, "node_modules", "pkg"), { recursive: true });
    fs.writeFileSync(
      path.join(root, "node_modules", "pkg", "index.js"),
      "import Legend from '@arcgis/core/widgets/Legend';\nvoid Legend;\n",
      "utf8",
    );
    fs.writeFileSync(
      path.join(root, "clean.ts"),
      "import FeatureLayer from '@arcgis/core/layers/FeatureLayer';\nvoid FeatureLayer;\n",
      "utf8",
    );

    const scan = scanWidgetUsage(root);
    expect(scan.filesScanned).toBe(1);
    expect(scan.hits).toEqual([]);
    expect(scan.filesWithWidgetUsage).toBe(0);
  });
});

describe("buildWidgetReadinessReport", () => {
  it("aggregates per-widget counts, dispositions, and the automated/assisted/manual split", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "app.ts"),
      [
        "import Legend from '@arcgis/core/widgets/Legend';",
        "import Legend2 from '@arcgis/core/widgets/Legend.js';",
        "import Editor from '@arcgis/core/widgets/Editor';",
        "import Daylight from '@arcgis/core/widgets/Daylight';",
        "void Legend; void Legend2; void Editor; void Daylight;",
      ].join("\n"),
      "utf8",
    );

    const report = buildWidgetReadinessReport(scanWidgetUsage(root));
    expect(report.summary.totalSites).toBe(4);
    expect(report.summary.automatedSites).toBe(2);
    expect(report.summary.assistedSites).toBe(1);
    expect(report.summary.manualSites).toBe(1);
    expect(report.summary.automatedPct).toBe(50);
    expect(report.summaryLine).toContain(ARCGIS_WIDGET_REMOVAL_RELEASE);
    expect(report.summaryLine).toContain(ARCGIS_WIDGET_REMOVAL_TIMEFRAME);

    const legend = report.widgets.find((row) => row.widget === "Legend");
    expect(legend?.count).toBe(2);
    expect(legend?.disposition).toBe("automated");
    expect(legend?.guideLink).toBe("docs/widget-survival-guide.md#legend");
    expect(report.widgets.find((row) => row.widget === "Editor")?.bucket).toBe("assisted");
    expect(report.widgets.find((row) => row.widget === "Daylight")?.bucket).toBe("manual");
  });

  it("does not inherit the widget disposition for support-module imports", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "app.ts"),
      [
        "import SearchViewModel from '@arcgis/core/widgets/Search/SearchViewModel';",
        "import Search from '@arcgis/core/widgets/Search';",
        "void SearchViewModel; void Search;",
      ].join("\n"),
      "utf8",
    );

    const report = buildWidgetReadinessReport(scanWidgetUsage(root));
    expect(report.widgets).toHaveLength(2);
    const widgetRow = report.widgets.find((row) => !row.supportModule);
    const supportRow = report.widgets.find((row) => row.supportModule);
    expect(widgetRow?.widget).toBe("Search");
    expect(widgetRow?.disposition).toBe("automated");
    expect(widgetRow?.bucket).toBe("automated");
    expect(supportRow?.widget).toBe("Search");
    expect(supportRow?.disposition).toBe("support-module");
    expect(supportRow?.bucket).toBe("manual");
    expect(supportRow?.target).toContain("only rewrites the root Search widget module");
    expect(report.summary.automatedSites).toBe(1);
    expect(report.summary.manualSites).toBe(1);
    expect(report.summary.automatedPct).toBe(50);
  });

  it("treats widget modules outside the disposition data as manual and says so", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "app.ts"),
      "import FloorFilter from '@arcgis/core/widgets/FloorFilter';\nvoid FloorFilter;\n",
      "utf8",
    );

    const report = buildWidgetReadinessReport(scanWidgetUsage(root));
    expect(WIDGET_DISPOSITIONS.some((entry) => entry.widget === "FloorFilter")).toBe(false);
    const row = report.widgets.find((item) => item.widget === "FloorFilter");
    expect(row?.disposition).toBe("unknown");
    expect(row?.bucket).toBe("manual");
    expect(row?.target).toContain("Not in widget-disposition data");
  });

  it("reports a 100% automated share when no widgets are used", () => {
    const root = makeTempProject();
    fs.writeFileSync(path.join(root, "clean.ts"), "export const ok = true;\n", "utf8");

    const report = buildWidgetReadinessReport(scanWidgetUsage(root));
    expect(report.summary.totalSites).toBe(0);
    expect(report.summary.automatedPct).toBe(100);
    expect(evaluateWidgetGate(report, 100).passed).toBe(true);
  });
});

describe("evaluateWidgetGate", () => {
  it("passes at or above the threshold and fails below it", () => {
    const root = makeTempProject();
    fs.writeFileSync(
      path.join(root, "app.ts"),
      [
        "import Legend from '@arcgis/core/widgets/Legend';",
        "import Daylight from '@arcgis/core/widgets/Daylight';",
        "void Legend; void Daylight;",
      ].join("\n"),
      "utf8",
    );

    const report = buildWidgetReadinessReport(scanWidgetUsage(root));
    expect(report.summary.automatedPct).toBe(50);
    expect(evaluateWidgetGate(report, 50).passed).toBe(true);
    const failed = evaluateWidgetGate(report, 80);
    expect(failed.passed).toBe(false);
    expect(failed.failures[0]).toContain("--gate threshold 80.0%");
  });
});

describe("widget readiness report on the esri-widget-cliff-app fixture", () => {
  it("matches the JSON report snapshot", () => {
    const report = buildWidgetReadinessReport(scanWidgetUsage(FIXTURE_ROOT));
    expect({ ...report, rootDir: "<fixture>" }).toMatchSnapshot();
  });

  it("matches the markdown report snapshot", () => {
    const report = buildWidgetReadinessReport(scanWidgetUsage(FIXTURE_ROOT));
    expect(formatWidgetReadinessMarkdown(report)).toMatchSnapshot();
  });

  it("renders a human table with the deadline framing", () => {
    const report = buildWidgetReadinessReport(scanWidgetUsage(FIXTURE_ROOT));
    const table = formatWidgetReadinessTable(report);
    expect(table).toContain("widget");
    expect(table).toContain("disposition");
    expect(table).toContain("Legend");
    expect(table).toContain(ARCGIS_WIDGET_REMOVAL_TIMEFRAME);
    expect(table).toContain("docs/widget-survival-guide.md");
  });
});
