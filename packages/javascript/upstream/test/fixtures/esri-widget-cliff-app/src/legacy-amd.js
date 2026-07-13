// Legacy 4.x AMD entry point kept alive for the classic build.
require([
  "esri/Map",
  "esri/views/MapView",
  "esri/widgets/Directions",
  "esri/widgets/BasemapGallery",
], function (Map, MapView, Directions, BasemapGallery) {
  var map = new Map({ basemap: "topo-vector" });
  var view = new MapView({ container: "viewDiv", map: map });
  view.ui.add(new Directions({ view: view }), "top-right");
  view.ui.add(new BasemapGallery({ view: view }), "bottom-left");
});

define(["esri/widgets/TimeSlider"], function (TimeSlider) {
  return function attachTimeSlider(view) {
    return new TimeSlider({ view: view, mode: "time-window" });
  };
});
