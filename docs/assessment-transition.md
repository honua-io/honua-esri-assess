---
type: guide
title: "Assess before you migrate"
description: "honua-migrate assess is the read-only entry point: what it inspects, what it never writes, and how its output feeds the rest of the migration."
resource: "https://pypi.org/project/honua-migrate/"
tags: [assess, read-only, workflow]
---
# Assessment command transition

`honua-migrate assess` is the primary surface for read-only Esri discovery.
It mounts the existing assessment application directly, so command options,
exit codes, `EsriFootprint.json`, `EsriAccessFootprint.json`, schema versions,
and redaction behavior do not change during the transition.

Both command/import families ship from the single `honua-migrate` PyPI
distribution. The obsolete `honua-esri-assess` distribution name is not a
dependency and is not republished from this repository.

| Compatibility surface | Replacement |
|---|---|
| `honua-esri-assess <args>` | `honua-migrate assess <args>` |
| `python -m honua_esri_assess <args>` | `python -m honua_migrate assess <args>` |
| New code importing `honua_esri_assess` | Prefer APIs under `honua_migrate` as they become available |

The `honua-esri-assess` console command, the `python -m honua_esri_assess`
module invocation, and public `honua_esri_assess` imports remain operational
for at least two consecutive `honua-migrate` minor releases and at least 90
days after the replacement reaches general availability, whichever is longer.
Legacy use emits one deprecation notice per Python process on stderr; JSON and
other stdout artifacts remain clean. The notice is not raised through Python's
warnings framework, so supported imports continue to work under `-W error`.

No legacy command or import is eligible for removal before `honua-migrate`
1.2. Removal is not automatic at 1.2: it requires a separate release decision,
release-note notice, evidence that both compatibility windows elapsed, and a
passing compatibility review. The former assessment repository is not
described as archived while these compatibility surfaces are supported.

Examples use the successor command:

```bash
honua-migrate assess scan agol --target https://example.maps.arcgis.com
honua-migrate assess report --input EsriFootprint.json --output readiness-report.md
honua-migrate assess schema validate EsriFootprint.json
```
