import { describe, expect, it } from "vitest";

import { getJsRuntimeParityMatrix, summarizeJsRuntimeParity } from "../src/migration/runtime-matrix.js";

describe("JS runtime parity matrix", () => {
  it("includes migration-critical runtime capabilities", () => {
    const matrix = getJsRuntimeParityMatrix();

    const featureLayerQuery = matrix.find(
      (entry) => entry.surface === "feature-layer" && entry.capability === "query-features",
    );
    const mapImageFind = matrix.find((entry) => entry.surface === "map-image-layer" && entry.capability === "find");
    const mapImageQuery = matrix.find(
      (entry) => entry.surface === "map-image-layer" && entry.capability === "query-features",
    );
    const mapImageQueryExtent = matrix.find(
      (entry) => entry.surface === "map-image-layer" && entry.capability === "query-extent",
    );
    const mapImageQueryRelated = matrix.find(
      (entry) => entry.surface === "map-image-layer" && entry.capability === "query-related-features",
    );
    const mapImageSublayerWrapper = matrix.find(
      (entry) => entry.surface === "map-image-layer" && entry.capability === "sublayer-query-wrapper",
    );
    const mapImageSublayerVisibility = matrix.find(
      (entry) => entry.surface === "map-image-layer" && entry.capability === "sublayer-visibility-and-filters",
    );
    const mapViewGoTo = matrix.find((entry) => entry.surface === "map-view" && entry.capability === "navigation-go-to");
    const navigationWidgets = matrix.find(
      (entry) => entry.surface === "widget" && entry.capability === "navigation-widgets",
    );
    const commonControls = matrix.find(
      (entry) => entry.surface === "control" && entry.capability === "common-map-controls",
    );

    expect(featureLayerQuery).toMatchObject({
      arcGisJsApi: "FeatureLayer.queryFeatures",
      honuaCompat: "compat",
      honuaMapLibre: "native",
    });
    expect(mapImageFind).toMatchObject({
      arcGisJsApi: "MapImageLayer.find",
      honuaCompat: "compat",
    });
    expect(mapImageQuery).toMatchObject({
      arcGisJsApi: "MapImageLayer/Sublayer.queryFeatures",
      honuaCompat: "compat",
      esriLeaflet: "compat",
    });
    expect(mapImageQueryExtent).toMatchObject({
      arcGisJsApi: "MapImageLayer/Sublayer.queryExtent",
      honuaCompat: "compat",
      esriLeaflet: "compat",
    });
    expect(mapImageQueryRelated).toMatchObject({
      arcGisJsApi: "MapImageLayer/Sublayer.queryRelatedFeatures",
      honuaCompat: "compat",
      esriLeaflet: "compat",
    });
    expect(mapImageSublayerWrapper).toMatchObject({
      arcGisJsApi:
        "MapImageLayer.sublayer(id).queryFeatures/queryFeatureCount/queryObjectIds/queryExtent/queryRelatedFeatures",
      honuaCompat: "compat",
      esriLeaflet: "compat",
    });
    expect(mapImageSublayerVisibility).toMatchObject({
      arcGisJsApi: "MapImageLayer.sublayer(id).visible/definitionExpression",
      honuaCompat: "compat",
      esriLeaflet: "compat",
    });
    expect(mapViewGoTo).toMatchObject({
      arcGisJsApi: "MapView.goTo",
      honuaCompat: "compat",
      honuaMapLibre: "native",
      esriLeaflet: "compat",
    });
    expect(navigationWidgets).toMatchObject({
      arcGisJsApi: "BasemapGallery/Bookmarks/Expand",
      honuaCompat: "compat",
      honuaMapLibre: "assisted",
      esriLeaflet: "compat",
    });
    expect(commonControls).toMatchObject({
      arcGisJsApi: "Home/BasemapToggle/Locate/ScaleBar/Compass/Fullscreen/Zoom/Attribution",
      honuaCompat: "compat",
      esriLeaflet: "compat",
    });
  });

  it("classifies MapLibre widget capabilities (LayerList/Legend/Popup/Search/FeatureTable)", () => {
    const matrix = getJsRuntimeParityMatrix();
    const layerListLegend = matrix.find(
      (entry) => entry.surface === "widget" && entry.capability === "layer-list-and-legend",
    );
    const popup = matrix.find((entry) => entry.surface === "widget" && entry.capability === "popup-widget");
    const search = matrix.find((entry) => entry.surface === "widget" && entry.capability === "search-widget");
    const searchOptions = matrix.find(
      (entry) => entry.surface === "widget" && entry.capability === "search-expanded-options",
    );
    const featureTableOptions = matrix.find(
      (entry) => entry.surface === "widget" && entry.capability === "feature-table-expanded-options",
    );

    expect(layerListLegend).toMatchObject({
      honuaCompat: "compat",
      honuaMapLibre: "assisted",
      esriLeaflet: "compat",
    });
    expect(popup).toMatchObject({
      arcGisJsApi: "Popup",
      honuaCompat: "compat",
      honuaMapLibre: "assisted",
      esriLeaflet: "compat",
    });
    expect(search).toMatchObject({
      arcGisJsApi: "Search",
      honuaCompat: "compat",
      honuaMapLibre: "unsupported",
      esriLeaflet: "compat",
    });
    expect(searchOptions).toMatchObject({
      honuaCompat: "compat",
      honuaMapLibre: "unsupported",
      esriLeaflet: "compat",
    });
    expect(featureTableOptions).toMatchObject({
      honuaCompat: "compat",
      honuaMapLibre: "assisted",
      esriLeaflet: "compat",
    });
  });

  it("keeps MapLibre data-layer/view runtime verdicts as native (no regression)", () => {
    const matrix = getJsRuntimeParityMatrix();
    const featureLayerQuery = matrix.find(
      (entry) => entry.surface === "feature-layer" && entry.capability === "query-features",
    );
    const mapImageQuery = matrix.find(
      (entry) => entry.surface === "map-image-layer" && entry.capability === "query-features",
    );
    const mapViewGoTo = matrix.find((entry) => entry.surface === "map-view" && entry.capability === "navigation-go-to");

    expect(featureLayerQuery).toMatchObject({ honuaMapLibre: "native" });
    expect(mapImageQuery).toMatchObject({ honuaMapLibre: "native" });
    expect(mapViewGoTo).toMatchObject({ honuaMapLibre: "native" });
  });

  it("summarizes runtime parity counts for both targets", () => {
    const matrix = getJsRuntimeParityMatrix();
    const summary = summarizeJsRuntimeParity(matrix);

    const totalHonua = Object.values(summary.honuaCompat).reduce((acc, value) => acc + value, 0);
    const totalHonuaMapLibre = Object.values(summary.honuaMapLibre).reduce((acc, value) => acc + value, 0);
    const totalEsriLeaflet = Object.values(summary.esriLeaflet).reduce((acc, value) => acc + value, 0);

    expect(totalHonua).toBe(matrix.length);
    expect(totalHonuaMapLibre).toBe(matrix.length);
    expect(totalEsriLeaflet).toBe(matrix.length);
    expect(summary.honuaCompat.compat).toBeGreaterThan(0);
    expect(summary.honuaMapLibre.native).toBeGreaterThan(0);
    expect(summary.honuaMapLibre.assisted).toBeGreaterThan(0);
    expect(summary.honuaMapLibre.unsupported).toBeGreaterThanOrEqual(1);
    expect(summary.esriLeaflet.assisted).toBe(0);
  });
});
