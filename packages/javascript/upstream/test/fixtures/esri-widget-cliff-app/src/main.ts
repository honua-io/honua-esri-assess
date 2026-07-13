import Map from "@arcgis/core/Map";
import MapView from "@arcgis/core/views/MapView";
import Legend from "@arcgis/core/widgets/Legend";
import LayerList from "@arcgis/core/widgets/LayerList.js";
import Expand from "@arcgis/core/widgets/Expand";
import SearchViewModel from "@arcgis/core/widgets/Search/SearchViewModel";

const map = new Map({ basemap: "streets-vector" });
const view = new MapView({ container: "viewDiv", map, zoom: 12 });

const legend = new Legend({ view });
const layerList = new LayerList({ view });
view.ui.add(new Expand({ view, content: legend }), "top-right");
view.ui.add(new Expand({ view, content: layerList }), "top-left");

const searchViewModel = new SearchViewModel({ view });
void searchViewModel;
