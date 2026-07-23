// CDN map-components style dynamic loading.
async function addAnalysisWidgets(view) {
  const Daylight = await $arcgis.import("@arcgis/core/widgets/Daylight.js");
  const ElevationProfile = await $arcgis.import("esri/widgets/ElevationProfile");
  view.ui.add(new Daylight({ view }), "top-right");
  view.ui.add(new ElevationProfile({ view }), "bottom-right");
}

async function addSketch(view) {
  const [Sketch] = await $arcgis.import(["esri/widgets/Sketch", "esri/layers/GraphicsLayer"]);
  view.ui.add(new Sketch({ view }), "top-left");
}

export { addAnalysisWidgets, addSketch };
