import { FeatureLayerCompat, FeatureTableCompat, LayerListCompat, MapCompat, MapViewCompat, PopupCompat } from "@honua/sdk-js/esri-compat";
// Original Honua migration-workbench scenario. This file intentionally uses
// ArcGIS JS SDK imports so the repository's honua-migrate CLI is the only
// source-to-target transformation engine exercised by the artifact generator.


const PARCELS = [
  {
    attributes: { OBJECTID: 41, PARCEL_ID: "TMK-041", ZONING: "residential" },
    geometry: { x: -157.812, y: 21.302 },
  },
  {
    attributes: { OBJECTID: 42, PARCEL_ID: "TMK-042", ZONING: "commercial" },
    geometry: { x: -157.809, y: 21.304 },
  },
  {
    attributes: { OBJECTID: 43, PARCEL_ID: "TMK-043", ZONING: "residential" },
    geometry: { x: -157.806, y: 21.307 },
  },
];

const ASSESSMENTS = {
  41: [
    { attributes: { OBJECTID: 4101, PARCEL_ID: "TMK-041", YEAR: 2024 } },
    { attributes: { OBJECTID: 4102, PARCEL_ID: "TMK-041", YEAR: 2025 } },
  ],
  42: [{ attributes: { OBJECTID: 4201, PARCEL_ID: "TMK-042", YEAR: 2025 } }],
  43: [],
};

export async function runMigrationWorkbenchScenario() {
  const parcels = new FeatureLayerCompat({
    id: "parcels",
    title: "Honua-authored parcels",
    url: "https://example.test/rest/services/parcels/FeatureServer/0",
    outFields: ["OBJECTID", "PARCEL_ID", "ZONING"],
  });

  parcels.queryFeatures = async (query = {}) => {
    const where = typeof query.where === "string" ? query.where : "1=1";
    const features = where.includes("ZONING = 'residential'")
      ? PARCELS.filter((feature) => feature.attributes.ZONING === "residential")
      : PARCELS;
    return { features };
  };

  parcels.queryRelatedFeatures = async (query = {}) => {
    const objectIds = Array.isArray(query.objectIds)
      ? query.objectIds
      : typeof query.objectIds === "string"
        ? query.objectIds.split(",").map((value) => Number.parseInt(value, 10))
        : [];
    return {
      relatedRecordGroups: objectIds.map((objectId) => ({
        objectId,
        relatedRecords: ASSESSMENTS[objectId] ?? [],
      })),
    };
  };

  const map = new MapCompat({ basemap: "streets", layers: [parcels] });
  const view = new MapViewCompat({
    map,
    container: null,
    center: [-157.81, 21.304],
    zoom: 13,
  });
  const popup = new PopupCompat({ view });
  const table = new FeatureTableCompat({
    view,
    layer: parcels,
    container: null,
    relatedRecordsEnabled: true,
    where: "1=1",
  });
  const layerList = new LayerListCompat({
    view,
    listItemCreatedFunction: ({ item }) => {
      item.actionsSections = [[{ id: "inspect-selected", title: "Inspect selected parcel" }]];
    },
  });

  let selectionPopupSynchronized = false;
  table.highlightIds.on("change", () => {
    const selectedRows = table.getSelectedRows();
    if (selectedRows.length === 0) {
      popup.close();
      return;
    }

    popup.open({
      title: "Selected parcel",
      features: selectedRows.map((row) => ({
        id: `parcel-${row.objectId}`,
        attributes: row.attributes,
        geometry: row.geometry,
      })),
      location: selectedRows[0].geometry,
    });
    selectionPopupSynchronized = popup.visible;
  });

  let layerActionTriggered = false;
  layerList.on("trigger-action", ({ action }) => {
    if (action.id === "inspect-selected") {
      layerActionTriggered = true;
    }
  });

  await table.when();
  const tableCountBeforeFilter = table.size;
  table.setWhere("ZONING = 'residential'");
  await table.refresh();
  const tableCountAfterFilter = table.size;

  table.highlightIds.add(41);
  const selectedRows = table.getSelectedRows();
  const related = await table.queryRelatedRecords({ relationshipId: 0 });

  layerList.refresh();
  layerList.setItemActions(parcels, [[{ id: "inspect-selected", title: "Inspect selected parcel" }]]);
  const layerActionDispatched = layerList.triggerAction("inspect-selected", parcels);

  return {
    constructors: {
      layer: parcels.constructor.name,
      map: map.constructor.name,
      view: view.constructor.name,
      table: table.constructor.name,
      popup: popup.constructor.name,
      layerList: layerList.constructor.name,
    },
    map: {
      layerCount: map.layers.length,
      center: view.center,
      zoom: view.zoom,
    },
    table: {
      countBeforeFilter: tableCountBeforeFilter,
      countAfterFilter: tableCountAfterFilter,
      where: table.where,
    },
    selection: {
      objectIds: table.getSelectedObjectIds(),
      selectedRowCount: selectedRows.length,
      popupVisible: popup.visible,
      popupFeatureId: popup.selectedFeature?.id,
      synchronized: selectionPopupSynchronized,
    },
    relatedRecords: {
      groupCount: related.relatedRecordGroups.length,
      recordCount: related.relatedRecordGroups.reduce(
        (count, group) => count + (Array.isArray(group.relatedRecords) ? group.relatedRecords.length : 0),
        0,
      ),
    },
    layerAction: {
      id: "inspect-selected",
      dispatched: layerActionDispatched,
      triggered: layerActionTriggered,
    },
  };
}

export default await runMigrationWorkbenchScenario();
