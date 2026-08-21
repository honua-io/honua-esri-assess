# honua-migrate

[![CI](https://github.com/honua-io/honua-migrate/actions/workflows/ci.yml/badge.svg?branch=trunk)](https://github.com/honua-io/honua-migrate/actions/workflows/ci.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/honua-io/honua-migrate/badge)](https://scorecard.dev/viewer/?uri=github.com/honua-io/honua-migrate)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

> **Command transition:** `honua-migrate assess` is now the primary assessment
> surface. The `honua-esri-assess` command, module invocation, Python imports,
> and artifact contracts remain compatible through the documented transition
> window, with removal no earlier than `honua-migrate` 1.2. See the
> [assessment transition policy](docs/assessment-transition.md).

An Apache-2.0 migration command-line suite whose **read-only assessment
surface** inventories an organization's Esri
footprint — ArcGIS Online, ArcGIS Server / Enterprise, and FileGDB workspaces —
and produces a versioned `EsriFootprint.json` artifact plus human-readable
Markdown reports: a readiness report, a per-shop-profile migratability
verdict, and a crosswalk from that footprint to Honua capability keys. It
exists so GIS teams can size a migration to
[Honua](https://honua.io) (or simply audit their own estate) before committing
to anything. The suite is Apache-2.0 by design so your security team can audit
every line before pointing it at production.

## Assessment is read-only and no-phone-home, verifiably

The assessment surface is built for skeptical review. The guarantees below
are enforced in code and by tests in this repository — not just promised:

- **Strictly read-only assessment.** Every request against an Esri system is an HTTP
  `GET`. The HTTP wrappers expose no write helpers; no `POST`/`PUT`/`DELETE`/
  `PATCH` is ever issued.
- **No network telemetry.** No usage pings, crash uploads, or update checks —
  there is not even an opt-in sink. The only hosts ever contacted are the
  `--target` you supply to `scan`, or the crosswalk URL you explicitly pass to
  `caps --crosswalk` (never fetched by default — see
  [Capability crosswalk](#capability-crosswalk-caps) below). Enforced by
  [`tests/test_no_telemetry.py`](tests/test_no_telemetry.py) and
  [`tests/smoke/test_no_network.py`](tests/smoke/test_no_network.py), which
  fail CI if outbound traffic appears.
- **It mints no credentials.** You run it anonymously or hand it a
  pre-existing token via `--token-env VAR` (an environment variable name).
  There is deliberately no `--token` flag, no username/password input, and no
  `generateToken` call.
- **Secrets never leak into outputs.** Tokens, query strings, and URL userinfo
  are redacted from logs and are never written into artifacts or diagnostics.
- **It never opens your databases.** Storage information comes from documented
  ArcGIS REST metadata only — no ArcSDE/DBMS connections, no GDB internals.
- **Everything stays on your machine.** Artifacts are written to local files
  (or stdout). Nothing is uploaded anywhere.

Before running against production, see
[Prerequisites & least-privilege access](docs/operators/prerequisites-and-least-privilege.md)
for the exact endpoints read at each access tier and the minimum privileges to
grant. An anonymous "Tier 1" scan needs no credentials at all.

## Status

Alpha, pre-1.0 (current source version 0.7.x — see the [CHANGELOG](CHANGELOG.md)).
The `EsriFootprint.json` schema is at **v0.2** and unstable until v1.0:
breaking changes are permitted between v0.x minors, per the
[versioning policy](docs/schemas/versioning.md). The package is not yet
published to PyPI; the first release is prepared under
[`#81`](https://github.com/honua-io/honua-migrate/issues/81).

## Quick start

Requires Python 3.11+.

After the first tagged release, install the application in an isolated
environment:

```bash
pipx install honua-migrate
honua-migrate assess --help
honua-esri-assess --help  # supported compatibility command
```

Until that release is published, install from the successor repository:

```bash
git clone https://github.com/honua-io/honua-migrate
cd honua-migrate
python3 -m pip install .
```

Scan an ArcGIS Online org (anonymous scans work too — just omit the token):

```bash
export AGOL_TOKEN="..."   # optional, pre-existing token
honua-migrate assess scan agol \
  --target https://yourorg.maps.arcgis.com/sharing/rest \
  --token-env AGOL_TOKEN \
  --output EsriFootprint.json \
  --validate
```

Then render the human-readable companions:

```bash
honua-migrate assess report  --input EsriFootprint.json --output readiness-report.md
honua-migrate assess verdict --input EsriFootprint.json
honua-migrate assess caps    --input EsriFootprint.json
```

Inspect or validate against the bundled schema at any time:

```bash
honua-migrate assess schema show
honua-migrate assess schema validate EsriFootprint.json
```

## Commands

Run `honua-migrate --help` for the complete migration command tree, or
`honua-migrate assess --help` for assessment options. The compatibility forms
`honua-esri-assess --help` and `python -m honua_esri_assess --help` remain
available. Every assessment `scan` subcommand is read-only against the target.

| Command | What it does |
|---------|--------------|
| `scan agol` | Inventory an ArcGIS Online / Portal org via the Portal Sharing REST API. |
| `scan server` | Walk an ArcGIS Server REST catalog (folders, services, layer detail). |
| `scan filegdb` | Read a local FileGDB inventory descriptor (`_inventory.json`); no network. |
| `scan filegdb-workspace` | Read-only `pyogrio`/GDAL metadata scan of a local `.gdb` directory (requires the `filegdb` extra). |
| `scan rbac` | Export identity/RBAC posture (users, roles, groups, per-service permissions) to the sibling `EsriAccessFootprint.json`. |
| `report` | Render a Markdown readiness report from a footprint. |
| `verdict` | Render a per-shop-profile migratability verdict (go / conditional / no-go, with explicit hard lock-in boundaries such as Utility Network, Parcel Fabric, and LRS). |
| `caps` | Crosswalk a footprint to Honua capability keys: `honua-caps.json` + a Markdown summary + a shareable catalog URL. See [Capability crosswalk](#capability-crosswalk-caps). |
| `schema show` / `schema validate <file>` | Print the bundled JSON Schema / validate an artifact against it. |
| `version` | Print package and bundled schema versions (also `--version`). |

Common `scan` options: `--output` (default `./EsriFootprint.json`; existing
files are not overwritten unless you pass `--force`), `--token-env VAR`,
`--validate`, `--timeout`, `--max-retries`, `--user-agent`, `--log-format
text|json`, `--log-level`. `report`, `verdict`, and `caps` accept `--input -` /
`--output -` for stdin/stdout and `--strict` to fail on schema-invalid input
instead of rendering warnings.

## Capability crosswalk (`caps`)

`caps` maps the same deterministic capability detection the `verdict` engine
uses (`honua_esri_assess.verdict.registry` — portal item types, server
`serviceType`s, and per-service capability tokens already in
`EsriFootprint.json`) onto **Honua capability keys**, via a versioned
crosswalk document:

```bash
honua-migrate assess caps --input EsriFootprint.json
# writes ./honua-caps.json, prints a Markdown summary + the shareable URL
```

```bash
honua-migrate assess caps \
  --input EsriFootprint.json \
  --json honua-caps.json \
  --output caps-summary.md
```

It emits:

1. **`honua-caps.json`** (`--json`, default `./honua-caps.json`): `schemaVersion`,
   `generatedAt`, the source footprint reference, per-capability entries
   (Honua capability key, contributing assess key(s), matched inventory count,
   tier), an `unmapped` list, `diagnostics`, a serving-unit estimate
   (`unitsEstimate`), and the shareable `url`.
2. A **Markdown summary** (`--output`, default stdout), styled like the
   `report`/`verdict` output.
3. The **shareable catalog URL** —
   `https://honua.io/capabilities.html?caps=<keys>&units=<estimate>` — always
   printed to stdout in addition to the JSON. `units` is derived from the
   footprint's server facet (federated server / host count) when available,
   and omitted entirely (never `units=0`) otherwise.

**Nothing in the footprint's detected inventory is dropped.** Every
assess-registry capability the footprint triggers ends up in `honua-caps.json`
one of two ways: mapped into `capabilities`, or listed in `unmapped` with a
`reason` of `"unmapped"` (known capability, no capability-key mapping yet) or
`"not-supported"` (a hard Esri lock-in such as Utility Network, Parcel
Fabric, or LRS — there is no Honua equivalent, by design).

### Draft crosswalk (temporary)

The crosswalk `caps` ships with today
(`src/honua_esri_assess/data/honua-crosswalk.fixture.json`) is a **draft
placeholder**, not the canonical mapping. The canonical
`capability-keys.v1.json` artifact — with the reconciled
`esri-assess-registry → capability` crosswalk — is produced by honua-server
(honua-io/honua-server#2893) and will replace it. Every `caps` run stamps the
crosswalk's own `source` string into `honua-caps.json`
(`"crosswalk.source"`) so output generated against the draft is never
mistaken for the reconciled mapping.

### Air-gapped usage

`caps` makes **no network call by default** — the bundled draft fixture is
read from the installed package. Use `--crosswalk <path>` to point at a local
file (e.g. a copy of the published artifact carried into an air-gapped
network) with zero network access:

```bash
honua-migrate assess caps --input EsriFootprint.json --crosswalk ./capability-keys.v1.json
```

`--crosswalk` also accepts an `http(s)://` URL once the canonical artifact is
published — this is the *one* deliberate, explicit exception to the tool's
no-network posture, and it only runs when you pass a URL yourself:

```bash
honua-migrate assess caps --input EsriFootprint.json \
  --crosswalk https://example.com/capability-keys.v1.json
```

The crosswalk document is validated at load: an `esri-assess-registry` key
that does not exist in `honua_esri_assess.verdict.registry.CAPABILITY_REGISTRY`
fails loudly (`report.crosswalk.invalid`, exit code `5`) rather than silently
mapping nothing.

## Supported sources

| Source | Target (`--target`) | Notes |
|--------|---------------------|-------|
| ArcGIS Online / Portal | Sharing REST base, e.g. `https://yourorg.maps.arcgis.com/sharing/rest` | The scanner appends `portals/self`, `search`, `community/groups`, `content/items/<id>` to this base; a higher-level portal URL yields `partial-coverage` diagnostics instead of an inventory. |
| ArcGIS Server | `https://host`, `https://host/arcgis`, `…/arcgis/rest`, or `…/arcgis/rest/services` — canonicalized internally | Deep layer probes run for `MapServer`/`FeatureServer`/`ImageServer`/`SceneServer`/`StreamServer`; other service types are recorded from the catalog walk. Add `--admin-usage` (admin token required) to also read `/admin/usagereports` and `/admin/data/items` for usage-ranked ordering and datastore binding modes — it degrades to a diagnostic if denied. |
| FileGDB (descriptor) | Directory containing `_inventory.json`, or the descriptor file itself | Local filesystem only. |
| FileGDB (workspace) | A local `.gdb` directory | Uses optional `pyogrio`/GDAL read-only metadata calls (`pip install ".[filegdb]"`). Without the extra, the command still exits 0 and records a `partial-coverage` diagnostic. Also available as the `honua_esri_assess.filegdb.scan_filegdb_workspace` library function. |
| RBAC / access | Portal Sharing REST base (`--kind portal`, default) or ArcGIS Server admin URL (`--kind server`) | Writes `EsriAccessFootprint.json` (defaults to stdout). |

Transient upstream failures (`429`, `502`, `503`, `504`) are retried with
capped exponential backoff honoring `Retry-After`; per-endpoint failures
(403, unreachable host, unsupported item type) are downgraded to typed
diagnostics inside the artifact rather than aborting the scan.

## Artifacts and schemas

`EsriFootprint.json` is the sole machine-readable handoff into the closed
Honua migration product; `EsriAccessFootprint.json` is its documented sibling
for identity/RBAC posture. Both are published JSON Schemas (draft 2020-12) in
this repository. Pass `--validate` on scan to check the artifact against the
packaged schema copy before it is written, or run `schema validate <file>` on
any artifact after the fact.

| Artifact | Schema | Reference |
|----------|--------|-----------|
| `EsriFootprint.json` v0.2 | [`schemas/esri-footprint-v0.2.json`](schemas/esri-footprint-v0.2.json) | [v0.1 reference](docs/schemas/esri-footprint.v0.1.md) + [v0.2 delta](docs/schemas/esri-footprint.v0.2.md) (additive: dependency edges, content-type classification, per-layer detail) |
| `EsriAccessFootprint.json` | [`schemas/esri-access-footprint-v0.2.json`](schemas/esri-access-footprint-v0.2.json) | [v0.1 reference](docs/schemas/esri-access-footprint.v0.1.md) |

- Canonical sample footprint: [`docs/samples/esri-footprint.sample.json`](docs/samples/esri-footprint.sample.json)
- Sample readiness report: [`docs/samples/readiness-report.sample.md`](docs/samples/readiness-report.sample.md)
- `honua-caps.json` is produced by `caps` (see [Capability crosswalk](#capability-crosswalk-caps)); it is not yet a published JSON Schema since its crosswalk input is a draft fixture pending honua-io/honua-server#2893.
- Readiness report guide (exit codes, sections, heuristics): [`docs/readiness-report.md`](docs/readiness-report.md)
- Versioning & deprecation policy: [`docs/schemas/versioning.md`](docs/schemas/versioning.md)
- Prospect-facing handoff contract: [`docs/schemas/handoff-contract.md`](docs/schemas/handoff-contract.md)

Artifact `diagnostics[].code` is a locked enum (`rate-limited`,
`partial-coverage`, `missing-permission`, `unresolved-reference`,
`unsupported-item-type`, `redacted-field`) so reviewers can audit exactly what
a diagnostic may say; see the
[diagnostic code catalog](docs/schemas/esri-footprint.v0.1.md#diagnostic-code-catalog).

## Exit codes and failure surface

The CLI never prints Python tracebacks; failures surface as typed,
prospect-safe diagnostics on stderr with deterministic exit codes:

| Exit | Meaning |
|------|---------|
| `0` | Success — including partial inventories; per-endpoint failures become `diagnostics[]` entries in the artifact. |
| `1` | Unexpected internal error (`internal-error`); raw exception details are not printed. |
| `2` | Missing/invalid arguments, or report/verdict/caps input handling failed (`report.input.*`). |
| `3` | `report --strict` / `verdict --strict` / `caps --strict` rejected an invalid footprint (`report.schema.invalid`). |
| `4` | Report rendering failed after input parsing succeeded (`report.render.internal`). |
| `5` | `caps --crosswalk` document failed structural or key validation, e.g. an unknown assess-registry key (`report.crosswalk.invalid`). |
| `10`+ | Expected scanner failure before output could be produced (`scanner-error`, `portal.*`, `server.*`). |
| `20`+ | Could not save the requested output artifact (`output-write-failed`, or output exists without `--force`). |
| `30` | Schema validation failed for `scan --validate` or `schema validate`. |

Local stderr logs can be formatted as text or JSON with `--log-format`; both
stay on the machine running the command. Crash dumps are off by default —
setting `HONUA_ESRI_ASSESS_CRASH_DUMPS=1` allows a local, redacted diagnostic
file under `~/.cache/honua-esri-assess/crashes/` after an internal error.
`--no-network-telemetry-confirm` is an audit-friendly acknowledgement flag; it
is not an opt-in and changes no behavior.

## Development

```bash
python3 -m pip install -e ".[dev]"
pytest                    # full suite
pytest tests/smoke -v     # fixture-backed end-to-end pipeline, no live Esri system
ruff check && mypy
```

The smoke suite exercises the full `scan → EsriFootprint.json → report`
pipeline against checked-in HTTP fixtures and runs as a separate CI job; the
dedicated no-network tests block outbound sockets while scans run. See
[`tests/smoke/fixtures/README.md`](tests/smoke/fixtures/README.md) for the
fixture layout and refresh protocol. Additional developer docs:
[scan handler interface](docs/handler-interface.md) and the read-only
[entitlement enumeration library](docs/entitlements.md)
(`honua_esri_assess.entitlements`).

Esri IP & licensing posture (clean-room formats via GDAL/community readers, no
rehosting of licensed data, no embedded proprietary assets) is documented in
[`docs/compliance/esri-ip-and-licensing-guardrails.md`](docs/compliance/esri-ip-and-licensing-guardrails.md).

Migration implementation ownership, retained SDK/server API boundaries,
release provenance, licensing, and legacy-entry removal gates are defined in
the [ownership and deprecation policy](docs/ownership-and-deprecation.md).
The temporary `honua-sdk` 0.x launcher collision and its fail-closed isolated
invocation path are documented in the
[`honua-migrate` console-script ownership policy](docs/console-script-collision.md).

## Related Honua projects

- [honua-server](https://github.com/honua-io/honua-server) — the flagship multi-protocol geospatial server (GeoServices REST, OGC API, WMS/WFS/WMTS/WCS, STAC, vector tiles, and more) that Esri clients such as ArcGIS Pro connect to unmodified; the migration target this tool sizes.
- [honua-console](https://github.com/honua-io/honua-console) — unified web console (Studio, Catalog, Operate, Share).
- [honua-helm](https://github.com/honua-io/honua-helm) — Helm chart, the Kubernetes deploy path.
- [geobench](https://github.com/honua-io/geobench) — open, vendor-neutral benchmark suite for geospatial servers.

Hosted platform docs: <https://honua.gitbook.io/honuaio/>

## Contributing

Issues and PRs are welcome. Commits follow
[Conventional Commits](https://www.conventionalcommits.org/) (enforced by
commitlint in CI); CI also runs the unit and smoke suites on Python 3.11–3.13
plus `ruff`, `mypy`, and a dependency license guard. Releases go through
release-please and PyPI Trusted Publishing — see [RELEASE.md](RELEASE.md).

## Security

Report vulnerabilities to <security@honua.io>. See the org
[security policy](https://github.com/honua-io/.github/blob/main/SECURITY.md).

## License

[Apache-2.0](LICENSE).
