import Map from "@arcgis/core/Map";
import FeatureLayer from "@arcgis/core/layers/FeatureLayer";
import MapImageLayer from "@arcgis/core/layers/MapImageLayer";
import TileLayer from "@arcgis/core/layers/TileLayer";
import MapView from "@arcgis/core/views/MapView";

const incidents = new FeatureLayer({
  id: "incidents",
  title: "Incidents",
  url: "https://example.test/rest/services/incidents/FeatureServer/0",
  outFields: ["*"],
  definitionExpression: "status = 'open'",
  opacity: 0.8,
});
const districts = new MapImageLayer({
  id: "districts",
  url: "https://example.test/rest/services/districts/MapServer",
  visible: true,
});
const basemapTiles = new TileLayer({
  id: "basemap-tiles",
  url: "https://example.test/rest/services/basemap/MapServer",
});
const map = new Map({
  basemap: "streets-vector",
  layers: [basemapTiles, districts, incidents],
});
const view = new MapView({
  map,
  container: "viewDiv",
  center: [-157.8, 21.3],
  zoom: 12,
});

void view;
