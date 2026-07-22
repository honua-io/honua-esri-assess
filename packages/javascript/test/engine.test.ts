import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { runEsriCompatCodemod } from "../src/codemod.js";
import { createReconcilePlan } from "../src/reconcile.js";
import { scanArcGisUsage } from "../src/scanner.js";
import { scanWidgetUsage } from "../src/widgets.js";

function fixture(source: string): string { const root = fs.mkdtempSync(path.join(os.tmpdir(), "honua-migrate-")); fs.writeFileSync(path.join(root, "app.ts"), source); return root; }
describe("migration extraction", () => {
  it("scans ArcGIS and esri-leaflet usage", () => {
    const report = scanArcGisUsage(fixture('import FeatureLayer from "@arcgis/core/layers/FeatureLayer"; import "esri-leaflet"; new FeatureLayer();'));
    expect(report.imports).toHaveLength(1); expect(report.esriLeafletImportCount).toBe(1);
  });
  it("reports widget readiness", () => {
    const report = scanWidgetUsage(fixture('import Legend from "@arcgis/core/widgets/Legend";'));
    expect(report.summary.automated).toBe(1);
  });
  it("keeps codemod non-mutating unless explicitly enabled", () => {
    const root = fixture('import Map from "@arcgis/core/Map";'); const file = path.join(root, "app.ts");
    expect(runEsriCompatCodemod(root).changedFiles).toBe(1); expect(fs.readFileSync(file, "utf8")).toContain("@arcgis/core");
    runEsriCompatCodemod(root, { write: true }); expect(fs.readFileSync(file, "utf8")).toContain("@honua/sdk-js/esri-compat");
  });
  it("creates a read-only reconciliation plan", () => expect(createReconcilePlan("source", "target", 0).mode).toBe("plan"));
});
