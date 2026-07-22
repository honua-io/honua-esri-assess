#!/usr/bin/env node
import fs from "node:fs";
import { runEsriCompatCodemod } from "./codemod.js";
import { rewriteWebMapUrls } from "./content.js";
import { JS_PARITY_MATRIX, JS_RUNTIME_PARITY_MATRIX, summarizeJsParityMatrix } from "./matrix.js";
import { createReconcilePlan } from "./reconcile.js";
import { scanArcGisUsage, summarizeArcGisScan } from "./scanner.js";
import { formatWidgetReadinessTable, scanWidgetUsage } from "./widgets.js";

export function run(argv: string[]): number {
  const [command = "help", target, ...options] = argv;
  if (command === "help" || command === "--help" || command === "-h") { usage(); return 0; }
  if (command === "scan" && target) return emit(scanArcGisUsage(target), summarizeArcGisScan(scanArcGisUsage(target)));
  if (command === "widgets" && target) return emit(scanWidgetUsage(target), formatWidgetReadinessTable(scanWidgetUsage(target)));
  if (command === "codemod" && target) return emit(runEsriCompatCodemod(target, { write: options.includes("--write"), target: targetOption(options) }));
  if (command === "matrix") return emit({ summary: summarizeJsParityMatrix(), matrix: JS_PARITY_MATRIX });
  if (command === "runtime-matrix") return emit({ summary: summarizeJsParityMatrix(JS_RUNTIME_PARITY_MATRIX), matrix: JS_RUNTIME_PARITY_MATRIX });
  if (command === "content-webmap" && target) {
    const source = option(options, "--source-url-prefix"); const destination = option(options, "--target-url-prefix");
    if (!source || !destination) return usage(2);
    return emit(rewriteWebMapUrls(JSON.parse(fs.readFileSync(target, "utf8")), source, destination));
  }
  if (command === "reconcile-plan" && target) {
    const destination = option(options, "--target"); const layerId = Number(option(options, "--layer-id"));
    if (!destination || !Number.isInteger(layerId)) return usage(2);
    return emit(createReconcilePlan(target, destination, layerId, Number(option(options, "--sample-size")) || 100));
  }
  return usage(2);
}
function option(args: string[], name: string): string | undefined { const index = args.indexOf(name); return index >= 0 ? args[index + 1] : undefined; }
function targetOption(args: string[]): "honua-compat" | "honua-maplibre" | "esri-leaflet" { const value = option(args, "--target"); return value === "honua-maplibre" || value === "esri-leaflet" ? value : "honua-compat"; }
function emit(value: unknown, summary?: string): number { if (summary) process.stdout.write(`${summary}\n`); process.stdout.write(`${JSON.stringify(value, null, 2)}\n`); return 0; }
function usage(code = 0): number { process.stdout.write("Usage: honua-migrate <scan|widgets|codemod|matrix|runtime-matrix|content-webmap|reconcile-plan> ...\n"); return code; }
if (process.argv[1]?.endsWith("cli.js")) process.exitCode = run(process.argv.slice(2));
