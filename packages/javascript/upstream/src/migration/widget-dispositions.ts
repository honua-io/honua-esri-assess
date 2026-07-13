/**
 * Shared widget-disposition data for the Esri Widget Cliff workstream.
 *
 * Every classic ArcGIS JS widget (`esri/widgets/*` / `@arcgis/core/widgets/*`)
 * is deprecated as of ArcGIS JS 5.0 and is removed at 6.0 ("as early as
 * Q1 2027"). This module is the single source of truth consumed by both the
 * generated survival guide (`docs/widget-survival-guide.md`, via
 * `scripts/generate-widget-survival-guide.mjs`) and the widget-usage scanner
 * (`src/migration/widget-scanner.ts`). Drift between the guide and this data
 * fails CI (`npm run docs:widget-guide:check`).
 *
 * Dispositions are grounded in what actually ships today:
 * - `automated` / `compat-shim` entries are backed by real shims under
 *   `src/esri-compat/` and codemod rewrite specs in
 *   `src/migration/codemod.ts::SUPPORTED_ARCGIS_MODULE_KIND_BY_PATH`.
 * - Gaps follow the honest accounting in `docs/migration-punch-list.md`
 *   (scene/3D widgets have no equivalent; visual parity is not byte-identical).
 */

/** Version of this disposition dataset. Bump when rows or taxonomy change. */
export const WIDGET_DISPOSITION_DATA_VERSION = "1.0.0";

/** ArcGIS JS release that deprecated every classic widget. */
export const ARCGIS_WIDGET_DEPRECATION_RELEASE = "5.0";

/** ArcGIS JS release that removes the classic widgets. */
export const ARCGIS_WIDGET_REMOVAL_RELEASE = "6.0";

/** Esri's stated removal timeframe for the 6.0 release. */
export const ARCGIS_WIDGET_REMOVAL_TIMEFRAME = "as early as Q1 2027";

/**
 * Pinned source for the deprecated-widget inventory. The list is maintained
 * manually per ArcGIS release; update the URL/release together with the rows.
 */
export const ARCGIS_WIDGET_INVENTORY_SOURCE =
  "https://developers.arcgis.com/javascript/latest/api-reference/esri-widgets.html";

export type WidgetDispositionKind =
  | "automated"
  | "compat-shim"
  | "app-platform"
  | "maplibre-plugin"
  | "manual-workaround"
  | "no-equivalent";

export const WIDGET_DISPOSITION_KINDS: readonly WidgetDispositionKind[] = [
  "automated",
  "compat-shim",
  "app-platform",
  "maplibre-plugin",
  "manual-workaround",
  "no-equivalent",
];

/** Migration-effort bucket used by the scanner readiness report. */
export type WidgetMigrationBucket = "automated" | "assisted" | "manual";

export interface WidgetDisposition {
  /** Widget class name, e.g. `Legend`. */
  widget: string;
  /** ESM module specifiers (`@arcgis/core/widgets/*`, without `.js`). */
  esmModules: readonly string[];
  /** Classic AMD module specifiers (`esri/widgets/*`). */
  amdModules: readonly string[];
  /** Exactly one disposition from the fixed taxonomy. */
  disposition: WidgetDispositionKind;
  /** Honua API/component target, or explicit workaround text. */
  target: string;
  /** Honest caveats; never "TBD". */
  notes: string;
  /** Repo-relative path to the compat shim source, when one exists. */
  shimSource?: string;
}

function widgetEntry(
  widget: string,
  disposition: WidgetDispositionKind,
  target: string,
  notes: string,
  shimSource?: string,
): WidgetDisposition {
  return {
    widget,
    esmModules: [`@arcgis/core/widgets/${widget}`],
    amdModules: [`esri/widgets/${widget}`],
    disposition,
    target,
    notes,
    ...(shimSource ? { shimSource } : {}),
  };
}

const AUTOMATED_NOTE =
  "The honua-migrate codemod rewrites the import and safe constructor call sites deterministically; " +
  "unsafe option literals fall through to an annotated manual TODO. Rendering goes through the Honua " +
  "widget host, so CSS selectors and DOM structure are not byte-identical to ArcGIS.";

const COMPAT_SHIM_NOTE =
  "The honua-migrate codemod rewrites the import and safe constructor call sites, but the shim covers " +
  "the core workflow rather than the full ArcGIS surface ? plan hands-on verification of app-specific " +
  "behavior after migration. Rendering is not byte-identical to ArcGIS.";

const SCENE_3D_NOTE =
  "SceneView/3D analysis widget. Honua's SceneViewCompat is 2D-behavior only and no Honua or MapLibre " +
  "surface reproduces this widget today (see docs/migration-punch-list.md, parity gap 1). Apps that " +
  "depend on it need a product decision, not a code rewrite.";

export const WIDGET_DISPOSITIONS: readonly WidgetDisposition[] = [
  // --- automated: deterministic codemod rewrite onto a compat shim ---
  widgetEntry(
    "Attribution",
    "automated",
    "AttributionCompat from @honua/sdk-esri-compat (MapLibre AttributionControl underneath)",
    AUTOMATED_NOTE,
    "src/esri-compat/controls.ts",
  ),
  widgetEntry(
    "BasemapGallery",
    "automated",
    "BasemapGalleryCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/basemap-gallery.ts",
  ),
  widgetEntry(
    "BasemapLayerList",
    "automated",
    "BasemapLayerListCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/basemap-layer-list.ts",
  ),
  widgetEntry(
    "BasemapToggle",
    "automated",
    "BasemapToggleCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/controls.ts",
  ),
  widgetEntry(
    "Bookmarks",
    "automated",
    "BookmarksCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/bookmarks.ts",
  ),
  widgetEntry(
    "Compass",
    "automated",
    "CompassCompat from @honua/sdk-esri-compat (MapLibre NavigationControl covers the same gesture natively)",
    AUTOMATED_NOTE,
    "src/esri-compat/controls.ts",
  ),
  widgetEntry(
    "Expand",
    "automated",
    "ExpandCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/expand.ts",
  ),
  widgetEntry(
    "Feature",
    "automated",
    "FeatureCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/feature.ts",
  ),
  widgetEntry(
    "FeatureTemplates",
    "automated",
    "FeatureTemplatesCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/feature-templates.ts",
  ),
  widgetEntry(
    "Fullscreen",
    "automated",
    "FullscreenCompat from @honua/sdk-esri-compat (MapLibre FullscreenControl underneath)",
    AUTOMATED_NOTE,
    "src/esri-compat/controls.ts",
  ),
  widgetEntry(
    "Home",
    "automated",
    "HomeCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/controls.ts",
  ),
  widgetEntry(
    "LayerList",
    "automated",
    "LayerListCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/layer-list.ts",
  ),
  widgetEntry(
    "Legend",
    "automated",
    "LegendCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/legend.ts",
  ),
  widgetEntry(
    "Locate",
    "automated",
    "LocateCompat from @honua/sdk-esri-compat (MapLibre GeolocateControl covers the same behavior natively)",
    AUTOMATED_NOTE,
    "src/esri-compat/controls.ts",
  ),
  widgetEntry(
    "Popup",
    "automated",
    "PopupCompat from @honua/sdk-esri-compat",
    [
      AUTOMATED_NOTE,
      "Popup actions and fieldInfos format callbacks migrate for the simple case only",
      "(docs/migration-punch-list.md, parity gap 5).",
    ].join(" "),
    "src/esri-compat/popup.ts",
  ),
  widgetEntry(
    "ScaleBar",
    "automated",
    "ScaleBarCompat from @honua/sdk-esri-compat (MapLibre ScaleControl underneath)",
    AUTOMATED_NOTE,
    "src/esri-compat/controls.ts",
  ),
  widgetEntry(
    "Search",
    "automated",
    "SearchCompat from @honua/sdk-esri-compat backed by the Honua geocoding surface",
    `${AUTOMATED_NOTE} Custom Locator sources are out of scope (Locator/Geoprocessor parity gap).`,
    "src/esri-compat/search.ts",
  ),
  widgetEntry(
    "Swipe",
    "automated",
    "SwipeCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/swipe.ts",
  ),
  widgetEntry(
    "TableList",
    "automated",
    "TableListCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/table-list.ts",
  ),
  widgetEntry(
    "Track",
    "automated",
    "TrackCompat from @honua/sdk-esri-compat",
    AUTOMATED_NOTE,
    "src/esri-compat/track.ts",
  ),
  widgetEntry(
    "Zoom",
    "automated",
    "ZoomCompat from @honua/sdk-esri-compat (MapLibre NavigationControl underneath)",
    AUTOMATED_NOTE,
    "src/esri-compat/controls.ts",
  ),
  // --- compat-shim: shim exists and the codemod rewrites to it, but the
  // widget carries a large interaction surface; expect hands-on verification ---
  widgetEntry(
    "AreaMeasurement2D",
    "compat-shim",
    "AreaMeasurement2DCompat from @honua/sdk-esri-compat",
    COMPAT_SHIM_NOTE,
    "src/esri-compat/measurement-2d.ts",
  ),
  widgetEntry(
    "CoordinateConversion",
    "compat-shim",
    "CoordinateConversionCompat from @honua/sdk-esri-compat",
    `${COMPAT_SHIM_NOTE} Custom coordinate formats beyond the built-in set are not reproduced.`,
    "src/esri-compat/coordinate-conversion.ts",
  ),
  widgetEntry(
    "Directions",
    "compat-shim",
    "DirectionsCompat from @honua/sdk-esri-compat backed by HonuaRouteService (RouteTask parity)",
    [
      COMPAT_SHIM_NOTE,
      "Only RouteTask-backed routing is shimmed; service-area, closest-facility, and OD-cost-matrix flows",
      "remain unsupported (docs/migration-punch-list.md, parity gap 3).",
    ].join(" "),
    "src/esri-compat/directions.ts",
  ),
  widgetEntry(
    "DistanceMeasurement2D",
    "compat-shim",
    "DistanceMeasurement2DCompat from @honua/sdk-esri-compat",
    COMPAT_SHIM_NOTE,
    "src/esri-compat/measurement-2d.ts",
  ),
  widgetEntry(
    "Editor",
    "compat-shim",
    "EditorCompat from @honua/sdk-esri-compat",
    [
      COMPAT_SHIM_NOTE,
      "Attribute + geometry editing against feature services works; advanced form elements and",
      "utility-network editing do not.",
    ].join(" "),
    "src/esri-compat/editor.ts",
  ),
  widgetEntry(
    "FeatureForm",
    "compat-shim",
    "FeatureFormCompat from @honua/sdk-esri-compat",
    `${COMPAT_SHIM_NOTE} Arcade-driven form expressions are not evaluated.`,
    "src/esri-compat/feature-form.ts",
  ),
  widgetEntry(
    "FeatureTable",
    "compat-shim",
    "FeatureTableCompat from @honua/sdk-esri-compat",
    [
      COMPAT_SHIM_NOTE,
      "Related-records and popup interaction flows are exercised by the demo fixtures; column",
      "virtualization and attachment editing differ from ArcGIS.",
    ].join(" "),
    "src/esri-compat/feature-table.ts",
  ),
  widgetEntry(
    "Measurement",
    "compat-shim",
    "MeasurementCompat from @honua/sdk-esri-compat (2D distance/area only)",
    `${COMPAT_SHIM_NOTE} 3D measurement modes are not supported.`,
    "src/esri-compat/measurement.ts",
  ),
  widgetEntry(
    "Print",
    "compat-shim",
    "PrintCompat from @honua/sdk-esri-compat",
    [
      COMPAT_SHIM_NOTE,
      "Export goes through the Honua rendering pipeline, not an ArcGIS print service; custom print",
      "templates need re-authoring.",
    ].join(" "),
    "src/esri-compat/print.ts",
  ),
  widgetEntry(
    "Sketch",
    "compat-shim",
    "SketchCompat from @honua/sdk-esri-compat",
    `${COMPAT_SHIM_NOTE} Snapping and 3D sketch tools are not reproduced.`,
    "src/esri-compat/sketch.ts",
  ),
  widgetEntry(
    "TimeSlider",
    "compat-shim",
    "TimeSliderCompat from @honua/sdk-esri-compat",
    [
      COMPAT_SHIM_NOTE,
      "Time-aware layer filtering works; stops derived from server time-info metadata should be",
      "verified per service.",
    ].join(" "),
    "src/esri-compat/time-slider.ts",
  ),
  // --- manual-workaround ---
  widgetEntry(
    "ElevationProfile",
    "manual-workaround",
    "No drop-in widget. Sample the profile geometry yourself (e.g. @honua/sdk-js/geometry densify + an " +
      "elevation/terrain source such as maplibre-gl queryTerrainElevation) and chart with your own charting library.",
    "There is no ElevationProfile shim and no automated rewrite. The workaround is honest but real work: " +
      "profile sampling, unit handling, and chart UX are app code you own after migration.",
  ),
  // --- no-equivalent: SceneView/3D analysis widgets ---
  widgetEntry("Daylight", "no-equivalent", "None. Requires a 3D scene with sun/shadow simulation.", SCENE_3D_NOTE),
  widgetEntry("LineOfSight", "no-equivalent", "None. Requires 3D scene geometry intersection analysis.", SCENE_3D_NOTE),
  widgetEntry("ShadowCast", "no-equivalent", "None. Requires a 3D scene with shadow accumulation.", SCENE_3D_NOTE),
  widgetEntry("Slice", "no-equivalent", "None. Requires 3D scene slicing.", SCENE_3D_NOTE),
  widgetEntry("Weather", "no-equivalent", "None. Requires a 3D scene atmosphere/weather renderer.", SCENE_3D_NOTE),
];

const DISPOSITION_BUCKET: Readonly<Record<WidgetDispositionKind, WidgetMigrationBucket>> = {
  automated: "automated",
  "compat-shim": "assisted",
  "app-platform": "assisted",
  "maplibre-plugin": "assisted",
  "manual-workaround": "manual",
  "no-equivalent": "manual",
};

export function widgetMigrationBucket(disposition: WidgetDispositionKind): WidgetMigrationBucket {
  return DISPOSITION_BUCKET[disposition];
}

const DISPOSITIONS_BY_WIDGET: ReadonlyMap<string, WidgetDisposition> = new Map(
  WIDGET_DISPOSITIONS.map((entry) => [entry.widget, entry]),
);

export function getWidgetDisposition(widget: string): WidgetDisposition | undefined {
  return DISPOSITIONS_BY_WIDGET.get(widget);
}

/**
 * GitHub-style anchor for a widget's `### <Widget>` heading in the generated
 * survival guide. Shared by the guide generator and the scanner report so the
 * per-widget report rows deep-link into the guide.
 */
export function widgetSurvivalGuideAnchor(widget: string): string {
  return widget.toLowerCase();
}

/** Repo-relative path of the generated survival guide. */
export const WIDGET_SURVIVAL_GUIDE_PATH = "docs/widget-survival-guide.md";

/**
 * Extracts the widget name from a module specifier when it addresses a classic
 * widget module (`@arcgis/core/widgets/*` or `esri/widgets/*`), including
 * support modules such as `@arcgis/core/widgets/Search/SearchViewModel`.
 */
export function widgetNameFromModulePath(modulePath: string): string | undefined {
  return widgetModulePathInfo(modulePath)?.widget;
}

export interface WidgetModulePathInfo {
  widget: string;
  /**
   * True when the specifier addresses a widget *support* module (for example
   * `@arcgis/core/widgets/Search/SearchViewModel`) rather than the widget
   * module itself. The codemod only rewrites the exact widget module, so
   * support-module usage must not inherit the widget's disposition.
   */
  supportModule: boolean;
}

export function widgetModulePathInfo(modulePath: string): WidgetModulePathInfo | undefined {
  const normalized = modulePath.endsWith(".js") ? modulePath.slice(0, -3) : modulePath;
  let rest: string | undefined;
  if (normalized.startsWith("@arcgis/core/widgets/")) {
    rest = normalized.slice("@arcgis/core/widgets/".length);
  } else if (normalized.startsWith("esri/widgets/")) {
    rest = normalized.slice("esri/widgets/".length);
  }
  if (!rest) {
    return undefined;
  }
  const segments = rest.split("/").filter((segment) => segment.length > 0);
  const widget = segments[0];
  if (!widget) {
    return undefined;
  }
  return { widget, supportModule: segments.length > 1 };
}
