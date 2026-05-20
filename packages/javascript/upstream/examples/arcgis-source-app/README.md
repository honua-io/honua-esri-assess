# arcgis-source-app

A hand-written ArcGIS JS SDK sample app used as the input to the migration
end-to-end harness at `test/migration-e2e.test.ts`.

This app is intentionally tiny (a parcel viewer with one feature layer, a
basemap, a `MapView`, and two event handlers ? one untouched, one
event-name-remapped) and exists so the codemod has a realistic end-to-end
case to convert. It does NOT need `@arcgis/core` installed to be used by the
e2e test: the test copies the sources into a tempdir, runs the codemod,
points TypeScript at the workspace `src/esri-compat/` via `paths`, and
typechecks the migrated output.

This is not vendored from `arcgis-js-api`. All code under `src/` is original.
