import { useEffect, useRef } from "react";

import Map from "@arcgis/core/Map";
import MapView from "@arcgis/core/views/MapView";
import FeatureLayer from "@arcgis/core/layers/FeatureLayer";
import LayerList from "@arcgis/core/widgets/LayerList";
import Legend from "@arcgis/core/widgets/Legend";
import Search from "@arcgis/core/widgets/Search";
import Popup from "@arcgis/core/widgets/Popup";

/**
 * Representative framework (React function component + hooks) usage of the
 * ArcGIS JS SDK: the map/view/layer/widgets are constructed inside a mount
 * effect and torn down on unmount, which is the common pattern in
 * component-based ArcGIS apps rather than a plain script entry point.
 */
export function ParcelMap(): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }

    const parcels = new FeatureLayer({
      url: "https://example.test/rest/services/parcels/FeatureServer/0",
      outFields: ["OBJECTID", "NAME"],
    });

    const map = new Map({
      basemap: "streets",
      layers: [parcels],
    });

    const view = new MapView({
      map,
      container: containerRef.current,
      center: [-157.86, 21.31],
      zoom: 11,
    });

    const layerList = new LayerList({ view });
    const legend = new Legend({ view });
    const search = new Search({ view, includeDefaultSources: false });
    const popup = new Popup({ view, dockEnabled: true });

    view.ui.add(layerList, "top-right");
    view.ui.add(legend, "bottom-left");
    view.ui.add(search, "top-left");

    return () => {
      view.destroy();
      void popup;
    };
  }, []);

  return <div className="parcel-map" ref={containerRef} />;
}
