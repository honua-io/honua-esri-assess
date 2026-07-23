export interface ParcelViewerOptions {
  containerId: string;
  parcelsUrl?: string;
  center?: [number, number];
  zoom?: number;
}

export interface ResolvedViewerConfig {
  containerId: string;
  parcelsUrl: string;
  center: [number, number];
  zoom: number;
}

const DEFAULT_PARCELS_URL = "https://example.test/rest/services/parcels/FeatureServer/0";
const DEFAULT_CENTER: [number, number] = [-157.8, 21.3];
const DEFAULT_ZOOM = 12;

export function configureViewer(options: ParcelViewerOptions): ResolvedViewerConfig {
  return {
    containerId: options.containerId,
    parcelsUrl: options.parcelsUrl ?? DEFAULT_PARCELS_URL,
    center: options.center ?? DEFAULT_CENTER,
    zoom: options.zoom ?? DEFAULT_ZOOM,
  };
}
