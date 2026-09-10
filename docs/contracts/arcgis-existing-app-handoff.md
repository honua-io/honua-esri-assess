# ArcGIS existing-app handoff

`honua-migrate services arcgis handoff` documents the bounded incremental
import path for one ArcGIS service: discover a service, review its
dependency closure and fidelity in a plan, apply it, verify the result, and
export the target endpoint plus the source-to-target service/layer ID mapping
that a retained Esri JS application will use. It is the CLI surface for the
"existing-app handoff" acceptance criteria on honua-io/honua-migrate#92 and
the reconciliation/status acceptance criteria on honua-io/honua-migrate#95.

## Scope and dependency closure

A handoff is built from a manifest — a JSON array of layer entries, each
naming a previously reviewed plan artifact (the source scope: service URL,
layer ID, table name) and the operator-verified `targetLayerId` once the
import has actually been published. Only the layers named in the manifest are
imported; there is no whole-estate migration. A relationship-dependent layer
is included by adding another manifest entry for it — the manifest *is* the
dependency closure, not something the CLI infers from the source service:

```json
[
  {"plan": "plans/parcels.json", "apply": "runs/parcels-apply.json", "targetLayerId": 12},
  {"plan": "plans/owners.json", "jobId": "job-778", "targetLayerId": 13}
]
```

Each entry accepts either `apply` (the `arcgis apply` output artifact, from
which the job ID is read and cross-checked against the plan) or an explicit
`jobId`, but not both.

## Coexistence vs. cutover

`--mode` is required and is exactly one of:

- `read-only-coexistence` — the existing Esri JS app keeps running against
  the original source; Honua is a read replica. The command refuses to emit
  the artifact unless the operator also proves the source is still serving
  the declared baseline (`--source-still-serving`, `--baseline-evidence`) and
  names an operator-controlled way back (`--route-back-method`).
- `writable-cutover` — the target becomes authoritative for some or all
  writes. The command requires an explicit `--write-authority`
  (`source` or `target`), a `--quiescence-window`, and a `--divergence-limit`.

The artifact always records `runtime: existing-esri-js-retained` and a
pinned `--client-version` — this is a coexistence handoff for the retained
Esri client, never framed as a completed Honua SDK conversion. `--source-change`
(repeatable: `endpoint`, `ids`, `auth`, or `none`) is required and `none`
cannot be combined with an actual change, so the artifact can never claim
"zero-change" while also reporting one.

## Three separate outcomes, not one

`--import-outcome`, `--reconciliation-outcome`, and `--retained-app-outcome`
are each required and independently one of `success`, `partial`, `failed`,
`unknown`. A reconciliation match (see `reconcile compare`) does not imply
the retained application works — `--retained-app-outcome` must be declared
from having actually exercised the app. The overall `outcome` is derived
deterministically: `failed` if any is `failed`, else `partial` if any is
`partial` or `unknown`, else `success`.

## Customer-facing status and switchback safety

`--customer-message` is always required. `--recovery-action` distinguishes
`monitoring-reconnect`, `transfer-retry`, `endpoint-switchback`, and
`data-restoration` (default `none`); optional `--diagnostics-link` values are
carried through for advanced diagnostics. `endpoint-switchback` additionally
requires `--divergence-handling` (`preserved`, `reconciled`, or
`discarded-with-consent`) — there is no bare "discarded" value, so a
switchback can never silently drop target-only writes.

## Effort, with consent

`--elapsed-seconds` and `--manual-interventions` are optional and are only
recorded when `--effort-consent` is also passed. This is a local artifact
field, not a telemetry sink: nothing is transmitted anywhere by this command.

## Cross-repo scope

Licensed Esri compatibility checks (rendering/query/popup/auth fidelity
against the real ArcGIS JS SDK) are owned by `honua-esri-compat`, not this
CLI; `--exercised-*` flags record that those checks were performed, not how.
Installed-CLI receipt evidence and .NET SDK/server runtime defects are
tracked against honua-io/honua-release#317, honua-io/honua-release#325,
honua-io/honua-sdk-dotnet#340, and honua-io/honua-server#4600 rather than
duplicated here.
