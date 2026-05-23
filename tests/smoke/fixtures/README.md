# Smoke test fixtures

These corpora drive the fixture-backed CI smoke tests under `tests/smoke/`. Each
fixture is **hand-authored synthetic JSON** modeled on the public Esri Portal
Sharing and ArcGIS Server REST shapes. No customer data was used or recorded.

## Layout

```
fixtures/
  agol/
    happy/         # all-200 walk of portal + search + per-item probes
    diagnostics/   # 429 on a paginated search page + 403 on an item probe
  arcgis-server/
    happy/         # /services?f=json + one folder traversal + service probes
    diagnostics/   # 200 error-envelope probes for rate-limit/permission paths
  filegdb/
    happy/sample.gdb/                  # synthetic local .gdb-shaped fixture
```

Each HTTP corpus directory contains a `_routes.json` enumerating URL →
fixture-file mappings. The smoke `conftest.py` loads it into the `responses`
registry and asserts there were **no unmatched requests** at teardown — any
drift in scanner URL construction will surface as a hard test failure rather
than a silent skip. The FileGDB corpus is filesystem-only. Real FileGDB scans
should call the `honua_esri_assess.filegdb.scan_filegdb_workspace` library
function with the optional `pyogrio`/GDAL metadata backend against a real
`.gdb` directory; the synthetic fixture files here are only test scaffolding
and are not part of the `EsriFootprint.json` handoff contract. The smoke suite
exercises the `scan filegdb --target ...` descriptor CLI path so fixture tests
stay dependency-light.

## Refreshing against a real org (out of CI)

`responses`-based smoke tests never touch the network. If you need to refresh a
fixture against a real ArcGIS Online org or ArcGIS Server:

1. Use a read-only Honua-owned demo org.
2. Run the scanner with a local recording harness that preserves the scanner's
   GET-only request shape.
3. Sanitize the resulting JSON (strip `clientId`, `token`, `serviceItemId`s
   tied to customer data, etc.) before committing.

Do not commit fixtures captured against a customer org. The smoke tests are
fixture-only by design so we never ship anything network-shaped in CI.

## Expected counts (`tests/smoke/expected/`)

Each backend has an `expected/<backend>-...-counts.json` golden. The golden
must agree with the emitted footprint aggregates and backend facets; for
example, ArcGIS Server `serviceCounts` records advertised services even when a
probe later downgrades the service to a diagnostic instead of an inventory
record. The smoke tests print a diff-friendly mismatch if the fixture is edited
without updating the golden.
