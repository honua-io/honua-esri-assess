import esriConfig from "@arcgis/core/config";
import RouteLayer from "@arcgis/core/layers/RouteLayer";

esriConfig.apiKey = "fixture-api-key-placeholder";

const routeLayer = new RouteLayer({
  url: "https://route.example.com/arcgis/rest/services/World/Route/NAServer/Route_World",
  routeServiceUrl: "https://route.example.com/arcgis/rest/services/World/RouteServer",
});

void routeLayer;
