import IdentityManager from "@arcgis/core/identity/IdentityManager";
import WebMap from "@arcgis/core/WebMap";

IdentityManager.checkSignInStatus("https://portal.example.com/sharing");

const map = new WebMap({
  portalItem: {
    id: "privatePortalItem001",
  },
});

void map;
