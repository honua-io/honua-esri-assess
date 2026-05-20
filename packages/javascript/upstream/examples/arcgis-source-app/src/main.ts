// Parcel viewer sample app written against the ArcGIS JS SDK 4.x.
// The migration e2e harness (test/migration-e2e.test.ts) copies this
// directory into a tempdir and runs runEsriCompatCodemod against it.
//
// Expected codemod outcomes:
// - "@arcgis/core/..." default imports rewritten to named compat imports
// - new FeatureLayer({...}) / new Map({...}) / new MapView({...}) rewritten
//   to FeatureLayerCompat / MapCompat / MapViewCompat
// - layer.on("layerview-create", ...) remapped to "layer-view-created"
// - view.on("click", ...) left untouched

import FeatureLayer from "@arcgis/core/layers/FeatureLayer";
import Map from "@arcgis/core/Map";
import MapView from "@arcgis/core/views/MapView";

import { configureViewer, type ParcelViewerOptions } from "./viewer-config.js";

export interface ParcelViewerHandle {
  parcels: unknown;
  map: unknown;
  view: unknown;
}

export function bootstrapParcelViewer(options: ParcelViewerOptions): ParcelViewerHandle {
  const config = configureViewer(options);

  const parcels = new FeatureLayer({
    url: config.parcelsUrl,
    outFields: ["OBJECTID", "PARCEL_ID", "OWNER", "USE_CODE"],
    popupTemplate: {
      title: "Parcel {PARCEL_ID}",
      content: "Owner: {OWNER}<br>Use code: {USE_CODE}",
    },
  });

  const map = new Map({ basemap: "streets" });
  map.add(parcels);

  const view = new MapView({
    container: config.containerId,
    map,
    center: config.center,
    zoom: config.zoom,
  });

  // Untouched DOM-style event ? codemod leaves "click" alone.
  view.on("click", (event) => {
    void event;
  });

  // Event-name remap target ? codemod rewrites "layerview-create" to
  // "layer-view-created" because compat emits the kebab-past-tense form.
  parcels.on("layerview-create", (event) => {
    void event;
  });

  return { parcels, map, view };
}
