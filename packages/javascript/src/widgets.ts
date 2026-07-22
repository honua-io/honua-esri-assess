import fs from "node:fs";
import { collectSourceFiles } from "./scanner.js";

export type WidgetDisposition = "automated" | "assisted" | "manual";
const WIDGETS: Record<string, WidgetDisposition> = {
  "@arcgis/core/widgets/Legend": "automated", "@arcgis/core/widgets/LayerList": "automated",
  "@arcgis/core/widgets/Popup": "assisted", "@arcgis/core/widgets/Search": "manual",
  "@arcgis/core/widgets/Editor": "assisted", "@arcgis/core/widgets/FeatureTable": "manual"
};
export interface WidgetReadinessRow { modulePath: string; disposition: WidgetDisposition; occurrences: number }
export interface WidgetReadinessReport { rootDir: string; rows: WidgetReadinessRow[]; summary: Record<WidgetDisposition, number> }

export function scanWidgetUsage(rootDir: string): WidgetReadinessReport {
  const counts = new Map<string, number>();
  for (const file of collectSourceFiles(rootDir)) {
    const source = fs.readFileSync(file, "utf8");
    for (const modulePath of Object.keys(WIDGETS)) if (source.includes(modulePath)) counts.set(modulePath, (counts.get(modulePath) ?? 0) + 1);
  }
  const summary: Record<WidgetDisposition, number> = { automated: 0, assisted: 0, manual: 0 };
  const rows = [...counts].sort().map(([modulePath, occurrences]) => {
    const disposition = WIDGETS[modulePath]!; summary[disposition] += occurrences;
    return { modulePath, disposition, occurrences };
  });
  return { rootDir, rows, summary };
}
export function formatWidgetReadinessTable(report: WidgetReadinessReport): string {
  return ["module | disposition | occurrences", "--- | --- | ---", ...report.rows.map((row) => `${row.modulePath} | ${row.disposition} | ${row.occurrences}`)].join("\n");
}
