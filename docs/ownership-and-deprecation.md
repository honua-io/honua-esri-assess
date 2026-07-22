# Migration ownership and deprecation policy

This repository is the public home for Honua migration assessment, planning,
code transformation, service and content orchestration, resumable run state,
and reconciliation. It supersedes the `honua-esri-assess` repository identity
and consolidates migration engines that previously lived beside the SDKs.

The consolidation moves user-facing migration implementations, not the public
runtime APIs they call. Honua SDKs continue to own reusable client, renderer,
parser, compatibility, geoprocessing, and mobile runtime APIs. Honua Server
continues to own and implement its administration, import, job, and evidence
APIs. `honua-migrate` consumes those public contracts; it does not copy their
implementations.

## Ownership matrix

| Surface | Owned here | Provenance and former owner | Retained outside this repository | Release and license boundary |
| --- | --- | --- | --- | --- |
| Assessment | The read-only scanners, reports, verdicts, capability crosswalk, schemas, and the `honua-migrate assess` mount. | Continued from the superseded `honua-esri-assess` identity; compatibility work is tracked in [#89](https://github.com/honua-io/honua-migrate/issues/89). | Source-system APIs and FileGDB readers remain external dependencies. Assessment transport remains read-only and isolated from migration writers. | Python release lane; Apache-2.0. Assessment artifacts retain their independent [schema lifecycle](schemas/versioning.md). |
| JavaScript | Scanner, widget analysis, codemod, parity matrices, fixtures, workbench, and JavaScript migration CLI under `packages/javascript`. | History-filtered move from `honua-sdk-js/src/migration`, tracked in [#97](https://github.com/honua-io/honua-migrate/issues/97). | `@honua/sdk-js`, `@honua/sdk-esri-compat`, renderers, request/auth support, and public web-map/style parsing remain SDK-owned dependencies. | `@honua/honua-migrate` and `honua-js-migrate` npm release lane; Apache-2.0. |
| Python / ArcPy | ArcPy scan, translate, run, `.pyt`, `.atbx`, and GPServer classification under `honua_migrate.code.python`. | History-preserving move from `honua-sdk-python/packages/honua-sdk/honua_sdk/migration`, tracked in [#98](https://github.com/honua-io/honua-migrate/issues/98). | `honua-sdk` clients and the `honua-gp` runtime remain Python SDK-owned public dependencies. Proprietary Esri packages are never bundled or required for offline classification. | Python optional runtime lane; Apache-2.0. |
| MAUI | The self-contained Roslyn codemod, fixtures, tests, and `honua-migrate-maui` tool under `packages/maui`. | History-preserving move from `honua-mobile/tools/Honua.Migrate.Maui*`, tracked in [#99](https://github.com/honua-io/honua-migrate/issues/99). | The experimental `honua-mobile` SDK keeps mobile controls, adapters, offline storage, and application runtime behavior. Portable .NET SDK contracts remain in their SDK repositories. | NuGet/dotnet-tool release lane; Apache-2.0. The tool does not require a MAUI workload or private SDK package access. |
| ArcGIS services | Discover, plan, apply, and job control in `honua-migrate services arcgis`. | Migration-owned client/orchestration code added in [#92](https://github.com/honua-io/honua-migrate/issues/92); no server implementation is moved. | Honua Server retains the GeoServices import, job, publication, and evidence APIs and their server-side behavior. Reconciliation is the separate shared surface below. | CLI code and artifacts are Apache-2.0. The called `honua-server` implementation remains ELv2 and server-released. |
| GeoServer | Scan, plan, apply, job control, and style disposition in `honua-migrate services geoserver`. | Migration-owned client/orchestration code added in [#93](https://github.com/honua-io/honua-migrate/issues/93); no server implementation is moved. | Honua Server retains GeoServer discovery/import/job APIs, secret resolution, and server-side execution. Reconciliation is the separate shared surface below. | CLI code and artifacts are Apache-2.0. The called `honua-server` implementation remains ELv2 and server-released. |
| Portal content | Portal scan/export/import, dependency preservation, URL rewrites, and web-map translation under the JavaScript package, currently exposed by `honua-js-migrate content`. The unified Python content group is reserved but remains a placeholder. | Moved with the JavaScript migration engine from `honua-sdk-js`, tracked in [#94](https://github.com/honua-io/honua-migrate/issues/94) and [#97](https://github.com/honua-io/honua-migrate/issues/97). | Public SDK parsers, renderers, request/auth support, and Honua Server content/import APIs remain with their owning SDK or server. | JavaScript migration lane; Apache-2.0. Network calls to the ELv2 server do not move or relicense server code. |
| Reconciliation | Versioned evidence contracts, source-target comparators, redacted reports, run checkpoints, resume decisions, and the unified `reconcile` command group. | JavaScript comparators move with [#97](https://github.com/honua-io/honua-migrate/issues/97); runtime-neutral run and evidence orchestration is migration-owned under [#95](https://github.com/honua-io/honua-migrate/issues/95). | SDK query clients and Honua Server job/evidence APIs remain public dependencies owned by those repositories. | Python and JavaScript migration lanes; Apache-2.0. Server persistence and evidence endpoints remain ELv2. |

## Provenance and release ownership

Migration engine moves preserve the relevant source history and record the
former repository and source commit. A moved file is maintained and released
from this repository after cutover; the former repository may contain only a
compatibility shim, transition documentation, and a cross-repository
validation lane. Runtime code that is merely called through a public SDK or
server API does not change owners.

The Honua migration maintainers are the release owners. Current path ownership
is recorded in [`.github/CODEOWNERS`](../.github/CODEOWNERS). Release-please and
the package-specific workflows own versioning, provenance, build, smoke
install, and publication for the Python, npm, and NuGet/dotnet-tool lanes; see
the [release process](../RELEASE.md). A runtime package is not considered moved
until its published metadata and provenance point to
`honua-io/honua-migrate`.

The repository and all migration engines are Apache-2.0. The experimental
`honua-mobile` SDK/control library is also Apache-2.0. The separate
experimental `honua-collect` end-user application and `honua-server` are ELv2.
Collect is not a migration source or runtime dependency, and no Collect code
moves into this repository. This repository may call documented server APIs,
but must not copy server implementation into the Apache-2.0 distribution.
Third-party and proprietary boundaries remain subject to the
[Esri IP and licensing guardrails](compliance/esri-ip-and-licensing-guardrails.md).

## Compatibility window

The compatibility clock for an old entry point starts only when its replacement
is installable from the intended registry, carries provenance for this
repository, passes the applicable parity and safety gates, and has supported
operator documentation. Preview builds do not start the clock.

Unless a longer ecosystem policy applies, a legacy entry point remains
supported for **two consecutive `honua-migrate` minor releases and at least 90
days** after the replacement reaches general availability, whichever is
longer. Removal is no earlier than `honua-migrate` 1.2 for replacements first
released in 1.0. A stable public SDK import or package subpath is removed only
in that SDK's next major release after the common window has elapsed. A
replacement that becomes unavailable pauses the clock.

During the window, shims must:

- preserve stdout artifacts, schemas, exit semantics, and non-interactive
  behavior;
- send a deprecation notice to stderr that names the replacement and earliest
  removal version, at most once per process;
- preserve assessment read-only and credential-redaction guarantees; and
- run in the former owning repository's compatibility lane.

Repository URLs are not deleted as part of this window. A superseded source
repository is archived or redirected with a permanent transition README after
the implementation move is complete.

## Legacy entry-point matrix

| Surface | Legacy entry point | Supported replacement | Earliest removal rule |
| --- | --- | --- | --- |
| Assessment | `honua-esri-assess`, `python -m honua_esri_assess`, and public `honua_esri_assess` imports. | `honua-migrate assess`; compatibility command and module shims are delivered by [#89](https://github.com/honua-io/honua-migrate/issues/89). | Command/module shims: common window, no earlier than 1.2. Artifact fields and schemas follow the separate schema policy and are not removed merely because a command shim expires. |
| JavaScript | Migration implementation and invocation from `honua-sdk-js`, plus `@honua/sdk-js/migration`. | The independent `@honua/honua-migrate` package published from this repository and its collision-free `honua-js-migrate` binary. | The SDK subpath remains a forwarding shim to the independent package through the common window and until the next `honua-sdk-js` major. |
| Python / ArcPy | `honua_sdk.migration`, `python -m honua_sdk.migration`, and the `honua-migrate` console entry installed by `honua-sdk`. | `honua-migrate code python` from this repository; the SDK entry delegates without changing artifacts. | Common window and the next `honua-sdk` major. The SDK-owned `honua-gp` runtime is retained, not deprecated by this move. |
| MAUI | Source invocation through `honua-mobile/tools/Honua.Migrate.Maui.Cli`. | Installed `honua-migrate-maui` tool published from this repository. | Duplicate implementation may be removed after the common window and former-repository validation passes. Transition documentation and its validation lane remain. |
| ArcGIS services | Hand-written operator sequences that directly drive Honua Server import and job endpoints. | `honua-migrate services arcgis` discover/plan/apply/job commands. | Operator sequences are retired by the documentation cutover once the CLI is usable. The versioned server APIs are retained and have no removal date under this policy. |
| GeoServer | Hand-written operator sequences that directly drive Honua Server GeoServer scan/import/job endpoints. | `honua-migrate services geoserver` scan/plan/apply/job commands. | Operator sequences are retired by the documentation cutover once the CLI is usable. The versioned server APIs are retained and have no removal date under this policy. |
| Portal content | Content and web-map commands sourced and released from `honua-sdk-js`. | The JavaScript package released here and currently exposed through `honua-js-migrate content`; the unified Python content group remains reserved. | Existing package commands keep compatible artifacts through the common window; former-repository implementation is then replaced by the tested shim. |
| Reconciliation | JavaScript SDK migration `reconcile` commands and direct operator use of server evidence endpoints. | `honua-js-migrate reconcile` for JavaScript comparison plus the unified `honua-migrate reconcile` run/evidence surface. | CLI aliases follow the common window. Versioned SDK/server query and evidence APIs remain owned and versioned by their repositories. |

## Removal evidence

Removal never depends on usage telemetry. Every removal pull request must link
all of the following telemetry-independent evidence:

1. a generally available replacement release and registry metadata that point
   to this repository;
2. passing parity, artifact-compatibility, source-read-only, mutation-boundary,
   and secret-redaction gates;
3. completed documentation cutover under
   [#101](https://github.com/honua-io/honua-migrate/issues/101);
4. a passing compatibility lane in each former owning repository, as required
   by [#100](https://github.com/honua-io/honua-migrate/issues/100);
5. release dates proving both the minor-release and 90-day windows elapsed;
6. a changelog notice that named the replacement and removal version; and
7. confirmation that no supported artifact schema or retained SDK/server API is
   being removed accidentally.

If any evidence is absent, the shim remains. The consolidated 1.0 cutover gate
is tracked in [#103](https://github.com/honua-io/honua-migrate/issues/103).
