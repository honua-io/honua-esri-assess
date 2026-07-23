import FeatureLayer from "@arcgis/core/layers/FeatureLayer";
import WebMap from "@arcgis/core/WebMap";

const publicLayer = new FeatureLayer({
  url: "https://sampleserver.example.com/arcgis/rest/services/Public/Incidents/FeatureServer/0",
  outFields: ["OBJECTID", "status"],
  popupTemplate: { title: "{status}" },
});

const map = new WebMap({
  portalItem: {
    id: "0123456789abcdef0123456789abcdef",
  },
  layers: [publicLayer],
});

void map;
