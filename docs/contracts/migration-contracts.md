---
type: reference
title: "Migration artifact contracts"
description: "The packaged JSON Schemas covering diagnostics, engine reports, plans, runs, results and reconciliation, and which contract version applies."
resource: "https://github.com/honua-io/honua-migrate/tree/trunk/schemas"
tags: [contracts, json-schema, artifacts]
---
# Migration contract versioning

Honua migration artifacts use the packaged JSON Schemas in
`honua_migrate.contract_schemas`. The current contract version is `v1` and
covers diagnostics, engine reports, plans, runs, results, and reconciliation.

Within `v1`, producers may add new enum-independent evidence objects only when
older consumers can ignore them. Renaming or removing a required field,
changing its type or meaning, tightening a previously valid value, or changing
plan-digest canonicalization requires a new major contract version. Producers
must continue reading the preceding major version for a documented transition
window; writers emit only the newest version unless an explicit compatibility
mode is selected.

Plans are review artifacts. Their `plan_digest` is the SHA-256 digest of the
canonical JSON object without the digest field, using sorted keys, UTF-8, and
compact separators. Apply commands must recompute the digest before any network
or filesystem mutation and bind each run to both `plan_id` and `plan_digest`.

All artifacts are credential-free. Field names associated with passwords,
tokens, API keys, authorization, credentials, or secret references are invalid,
including inside engine-owned evidence. URL userinfo, bearer values, and URL
query strings are also invalid. Credential values and secret references are
supplied again at execution time and are never copied into plans, runs, results,
diagnostics, or reconciliation evidence.

The stable exit-code families are: success (`0`), internal (`1`), input (`2`),
validation (`3`), unavailable (`4`), partial (`10`), remote (`20`), and safety
refusal (`40`). A command may define more specific codes within a documented
family only after reserving them in the shared contract module.
