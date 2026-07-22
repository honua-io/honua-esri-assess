export interface ParityEntry { surface: string; honuaCompat: string; honuaMapLibre: string; esriLeaflet: string }
export const JS_PARITY_MATRIX: readonly ParityEntry[] = Object.freeze([
  { surface: "FeatureLayer", honuaCompat: "compat", honuaMapLibre: "native", esriLeaflet: "compat" },
  { surface: "MapView", honuaCompat: "compat", honuaMapLibre: "assisted", esriLeaflet: "compat" },
  { surface: "Widgets", honuaCompat: "compat", honuaMapLibre: "assisted", esriLeaflet: "assisted" }
]);
export const JS_RUNTIME_PARITY_MATRIX = JS_PARITY_MATRIX;
export function summarizeJsParityMatrix(matrix = JS_PARITY_MATRIX): Record<string, number> { return { entries: matrix.length, compat: matrix.filter((x) => x.honuaCompat === "compat").length, native: matrix.filter((x) => x.honuaMapLibre === "native").length, assisted: matrix.filter((x) => x.honuaMapLibre === "assisted").length }; }
