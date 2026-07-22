import fs from "node:fs";
import path from "node:path";
import { collectSourceFiles } from "./scanner.js";

export type CodemodTarget = "honua-compat" | "honua-maplibre" | "esri-leaflet";
export interface CodemodFileResult { file: string; changed: boolean; manualTodos: string[] }
export interface CodemodResult { target: CodemodTarget; files: CodemodFileResult[]; changedFiles: number; manualTodos: number }

export function runEsriCompatCodemod(rootDir: string, options: { target?: CodemodTarget; write?: boolean } = {}): CodemodResult {
  const target = options.target ?? "honua-compat"; const files: CodemodFileResult[] = [];
  for (const file of collectSourceFiles(rootDir)) {
    const original = fs.readFileSync(file, "utf8"); const todos: string[] = [];
    let transformed = original.replace(/(["'])@arcgis\/core\/([^"']+)\1/g, (_match, quote: string, suffix: string) => {
      if (target === "honua-maplibre") { todos.push(`manual MapLibre mapping required for ${suffix}`); return `${quote}@honua/sdk-js/map${quote}`; }
      if (target === "esri-leaflet") { todos.push(`verify esri-leaflet compatibility for ${suffix}`); return `${quote}@honua/sdk-js/esri-compat${quote}`; }
      return `${quote}@honua/sdk-js/esri-compat${quote}`;
    });
    if (/geometryEngine|applyEdits|FeatureTable/.test(original)) todos.push("review API behavior after codemod");
    if (todos.length) transformed = `/* honua-migrate TODO: ${todos.join("; ")} */\n${transformed}`;
    const changed = transformed !== original;
    if (changed && options.write) fs.writeFileSync(file, transformed, "utf8");
    files.push({ file: path.resolve(file), changed, manualTodos: todos });
  }
  return { target, files, changedFiles: files.filter((file) => file.changed).length, manualTodos: files.reduce((n, file) => n + file.manualTodos.length, 0) };
}
