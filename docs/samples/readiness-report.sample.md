---
type: reference
title: "Sample readiness report"
description: "A filled-in readiness report, so you can see the shape of the output before running anything."
tags: [reports, sample]
---
# Honua Esri Readiness Report

| Field | Value |
| --- | --- |
| Schema version | v0.1 |
| Generated at | 2026-05-22T14:08:33Z |
| Source | ArcGIS Online |
| Source locator | example.maps.arcgis.com/0123ABCDEF456789 |
| Source captured at | 2026-05-22T14:02:11Z |
| Scanner | honua-esri-assess 0.1.0 |

## Service Inventory

### ArcGIS Online / portal-item

| Item | Type | Owner | Sharing | Modified |
| --- | --- | --- | --- | --- |
| Hydrants (`b2c3d4e5`) | Feature Service | field.crew | private | 2026-05-01T16:40:22Z |
| Parcels (`a1b2c3d4`) | Feature Service | gis.admin | org | 2026-04-18T09:12:00Z |
| Field Damage Survey (`d4e5f607`) | Survey123 Form | field.crew | private | 2026-05-12T18:30:00Z |
| Public Asset Viewer (`c3d4e5f6`) | Web Map | gis.admin | public | 2026-05-10T11:00:00Z |

## Layer Count

- Inventory records: **4**.
- Server service layers: **0**.
- FileGDB feature classes: **0**.

| Source | Type | Records | Layers |
| --- | --- | --- | --- |
| ArcGIS Online | Feature Service | 2 | - |
| ArcGIS Online | Survey123 Form | 1 | - |
| ArcGIS Online | Web Map | 1 | - |

## Complexity Estimate

**Bucket:** Small

- 4 inventory records fall in the Small item-count band.
- 0 server layers fall in the Small layer-count band.
- 0 FileGDB feature classes are represented in the inventory roll-up.
- Complex portal item types present: Survey123 Form.
- 3 diagnostics captured (2 warn, 1 info).

## Manual Review Items

| Reason code | Item | Details |
| --- | --- | --- |
| complex-item-type | Field Damage Survey (`d4e5f607`) | `Survey123 Form` usually needs migration planning beyond bulk copy. |
| flagged-by-diagnostic | Public Asset Viewer (`c3d4e5f6`) | Diagnostic `unresolved-reference` (warn) applies to this item. |

## Migration Ordering
1. **AGOL hosted feature services** - Move cloud-side authoritative feature services next.
   - Hydrants (`b2c3d4e5`)
   - Parcels (`a1b2c3d4`)
2. **AGOL web maps** - Web maps should follow the services they reference.
   - Public Asset Viewer (`c3d4e5f6`)
3. **AGOL notebooks, solutions, workforce, survey, and insights** - Specialized portal content should be handled late with human review.
   - Field Damage Survey (`d4e5f607`)

## Diagnostics Summary

| Severity | Code | Count | Scopes |
| --- | --- | --- | --- |
| warn | missing-permission | 1 | arcgis-online |
| warn | unresolved-reference | 1 | c3d4e5f60718293a4b5c6d7e8f901122 |
| info | rate-limited | 1 | arcgis-online |

Details:
- warn / missing-permission (arcgis-online): Skipped 2 items the scanner credential cannot read. Hint: Re-run with a credential that has read access to the GIS Admin group.
- warn / unresolved-reference (c3d4e5f60718293a4b5c6d7e8f901122): Web map references one item that was not included in the scan result. Hint: Confirm the referenced item exists and is readable before migration.
- info / rate-limited (arcgis-online): Sharing API throttled the scan for 3.2s.
