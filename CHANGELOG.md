# Changelog

## [0.3.0](https://github.com/honua-io/honua-esri-assess/compare/honua-esri-assess-v0.2.0...honua-esri-assess-v0.3.0) (2026-06-01)


### Features

* **cli:** wire pyogrio FileGDB workspace scanner to a scan filegdb-workspace command ([#26](https://github.com/honua-io/honua-esri-assess/issues/26)) ([9497864](https://github.com/honua-io/honua-esri-assess/commit/94978644d52f88f400321ac31d7e761b2862f2dd))


### Bug Fixes

* **build:** drop redundant schema force-include that breaks wheel build ([#34](https://github.com/honua-io/honua-esri-assess/issues/34)) ([87c4690](https://github.com/honua-io/honua-esri-assess/commit/87c469044fa7b957479c3ede6b950d98c427f205))
* declare click as an explicit runtime dependency ([0db51ec](https://github.com/honua-io/honua-esri-assess/commit/0db51ec36873cc33f17950f88c46052ce4812dfe))
* map Typer-vendored Click exceptions to exit codes ([b969985](https://github.com/honua-io/honua-esri-assess/commit/b9699858d2c99ccb61b100ef5c053dd82fb67ab9))

## [0.2.0](https://github.com/honua-io/honua-esri-assess/compare/honua-esri-assess-v0.1.0...honua-esri-assess-v0.2.0) (2026-05-23)


### Features

* E10: Add fixture-backed CI smoke test (#honua-esri-assess-10) ([d71ef0a](https://github.com/honua-io/honua-esri-assess/commit/d71ef0a9518e1888eb6ec39a76352a8d71eecbdf))
* E2: Publish EsriFootprint.json v0.1 schema and reference doc (#honua-esri-assess-2) ([f87920a](https://github.com/honua-io/honua-esri-assess/commit/f87920a8a8a13bbc2f1653d51ad78a76a7c07f48))
* E3: Document schema versioning and closed-product handoff contract (#honua-esri-assess-3) ([f6cba57](https://github.com/honua-io/honua-esri-assess/commit/f6cba574211f75bae501b9cba9086cb51b1b2ecf))
* E4: Implement read-only ArcGIS Online Portal scanner (#honua-esri-assess-4) ([c248705](https://github.com/honua-io/honua-esri-assess/commit/c2487053ce5f1568be27e6ca27a3511f294dd910))
* E5: Implement read-only ArcGIS Server REST scanner (#honua-esri-assess-5) ([acd49a1](https://github.com/honua-io/honua-esri-assess/commit/acd49a1df915517192ed2489334bb60be826a332))
* E6: Add license entitlement enumeration (#honua-esri-assess-6) ([74bfcdd](https://github.com/honua-io/honua-esri-assess/commit/74bfcdd11da5b036fd6dc893032871522fff1412))
* E7: Add FileGDB inventory path using license-compatible dependencies (#honua-esri-assess-7) ([12d339a](https://github.com/honua-io/honua-esri-assess/commit/12d339ace57e4fb80b7e80a8257c958c4e7876ab))
* E8: Generate Markdown readiness report and sample output (#honua-esri-assess-8) ([f1de24d](https://github.com/honua-io/honua-esri-assess/commit/f1de24d7ec6c11a41a58ba488872c3f07f506fd8))
* E9: Build scan CLI and package release path (#honua-esri-assess-9) ([4d9ead1](https://github.com/honua-io/honua-esri-assess/commit/4d9ead11f3201f14c0c9bf58da490919dccce325))

## 0.1.0 (Unreleased)

- Initial Typer command framework for `scan`, `schema`, `report`, and `version`.
- Package release path through release-please and PyPI Trusted Publishing.
- Bundled EsriFootprint v0.1 schema access for CLI validation.
