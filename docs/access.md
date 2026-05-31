# Authorized Access Export

The `--include-access` flag on `scan agol` and `scan server` adds a
read-only authorized enumeration tier to `honua-esri-assess`. Its output
is embedded as an OPTIONAL extension block inside the existing
`EsriFootprint.json` artifact (the sole handoff to the closed Honua
migration product). The default scan continues to omit the block.

> **Schema bump.** Enabling `--include-access` bumps the emitted
> footprint to `schemaVersion v0.2`. `v0.1.x` continues to ship for
> consumers pinned to it. See
> [`docs/schemas/esri-footprint.v0.2.md`](./schemas/esri-footprint.v0.2.md).

## Read-only endpoint coverage

The access collectors only issue HTTP GET requests. Tokens, when
supplied via `--token-env`, are sent to Esri endpoints only. No access
path posts telemetry or calls a Honua-operated service.

Portal / ArcGIS Online collector:

| Purpose | Endpoint path |
| --- | --- |
| Portal identity (org id) | `/sharing/rest/portals/self` |
| Custom roles + privileges | `/sharing/rest/portals/{orgId}/roles` |
| Org security policy | `/sharing/rest/portals/{orgId}/securityPolicy` |
| Groups | `/sharing/rest/community/groups` |
| Per-group membership (capped) | `/sharing/rest/community/groups/{id}/users` |
| Users (role + license + groups) | `/sharing/rest/community/users` |

ArcGIS Server collector:

| Purpose | Endpoint path |
| --- | --- |
| Auth/security config | `/arcgis/admin/security/config` |
| Server users | `/arcgis/admin/security/users/search` |
| Server roles | `/arcgis/admin/security/roles/search` |
| Per-service permissions | `/arcgis/admin/services/{folder}/{service}.{type}/permissions` |

Per-service permission probes are bounded to services already in the
v0.1 inventory; the collector never re-walks folders or schedules a
second discovery pass.

## CLI knobs

| Flag | Default | Behavior |
| --- | --- | --- |
| `--include-access / --no-include-access` | `--no-include-access` | Enable the authorized export. Requires `--token-env`. |
| `--access-group-cap INT` | `200` | Per-group member-probe cap. Groups whose membership exceeds the cap emit a `partial-coverage` diagnostic. |
| `--token-env VAR` | _none_ | Environment variable that holds an admin-tier token. Required when `--include-access` is set. |

`--include-access` raises a typed CLI diagnostic (`access-token-required`)
when no `--token-env` is supplied. The collector retains the read-only
stance — the underlying HTTP wrapper exposes only `get_json`.

## Diagnostics surface

Soft coverage gaps surface as locked-vocabulary diagnostics inside
`diagnostics[]`:

| Code | When |
| --- | --- |
| `missing-permission` | The admin-tier token cannot read an endpoint. |
| `partial-coverage` | A group membership probe exceeded `--access-group-cap`, or a response shape was unexpected but recoverable. |
| `unresolved-reference` | An expected admin endpoint returned 404. |
| `redacted-field` | The scanner deliberately omitted a field whose payload was not prospect-safe (URL-shaped item ids, URL-shaped owners, etc.). |

Hard failures raise `AccessExportError` subclasses
(`AccessAuthError`, `AccessForbiddenError`, `AccessNotFoundError`,
`AccessRateLimitedError`, `AccessConnectionError`, `AccessApiError`,
`AccessSchemaError`). The CLI maps them to a typed stderr diagnostic
(`access-export-failed`); no raw Python tracebacks are printed.

`AccessRateLimitedError` is what surfaces when an admin endpoint
returns HTTP 429 (or an HTTP-200 envelope with `error.code == 429`)
after the HTTP client has exhausted `--max-retries` retries with
exponential backoff. Throttling is treated as a terminal failure for
the access export rather than a soft `rate-limited` diagnostic so
that operators rerun the scan once the source has recovered instead
of shipping an artifact that silently dropped admin tables. The
v0.1-locked `rate-limited` code remains reserved for the inventory
scanners that DO continue past per-request throttling.

Diagnostic scope identifiers use the following taxonomy:

- `portal.access`
- `portal.access.roles`
- `portal.access.groups`
- `portal.access.groups.{groupId}.users`
- `portal.access.securityPolicy`
- `portal.access.users`
- `portal.access.itemSharing`
- `server.access.securityConfig`
- `server.access.users`
- `server.access.roles`
- `server.access.services/{folder}/{name}.{type}`
- `mapping.recommendation`

## Output shape

The output block adds an `access` property to `portal` and/or `server`
facets. A trimmed sample:

```json
{
  "schemaVersion": "v0.2",
  "portal": {
    "orgId": "0123ABCDEF",
    "orgUrl": "https://example.maps.arcgis.com",
    "itemCounts": {"Feature Service": 1},
    "access": {
      "users": [
        {
          "username": "alice",
          "roleId": "org_admin",
          "userType": "creatorUT",
          "status": "active",
          "lastLogin": "2026-05-01T00:00:00Z",
          "groupIds": ["groupA"]
        }
      ],
      "roles": [
        {
          "id": "org_admin",
          "name": "Administrator",
          "scope": "admin",
          "privileges": ["portal:admin:*"]
        }
      ],
      "groups": [
        {
          "id": "groupA",
          "title": "Field Crew",
          "access": "private",
          "owner": "alice",
          "capabilities": ["updateitemcontrol"],
          "isInvitationOnly": true,
          "isViewOnly": false,
          "memberCount": 12
        }
      ],
      "itemSharing": [
        {
          "itemId": "abc123",
          "owner": "alice",
          "accessLevel": "org",
          "sharedWithGroupIds": []
        }
      ],
      "securityPolicy": {
        "mfaRequired": true,
        "signInMethods": ["oidc"],
        "passwordMinLength": 12,
        "allowedOrigins": []
      },
      "mappingRecommendation": {
        "honuaRoles": [
          {
            "esriRoleId": "org_admin",
            "honuaRole": "admin",
            "builtin": "admin",
            "confidence": "high",
            "rationale": "Esri scope 'admin' maps directly to Honua 'admin'."
          }
        ],
        "oidcRoleClaims": [
          {
            "honuaRole": "admin",
            "claimName": "roles",
            "claimValue": "admin",
            "confidence": "high"
          }
        ],
        "facadeAccessPolicies": [
          {
            "policyId": "facade:org:no-groups",
            "accessLevel": "org",
            "itemIds": ["abc123"],
            "groupIds": [],
            "confidence": "high"
          }
        ]
      }
    }
  }
}
```

A full canonical sample lives at
[`docs/samples/esri-footprint.access.sample.json`](./samples/esri-footprint.access.sample.json).

## Mapping recommendation

`mappingRecommendation` is a pure projection of the collected access
data. Downstream tickets in the Honua RBAC, OIDC, and Portal-facade
epics consume the recommendation; this scanner never materializes
anything on the Honua side. The mapper:

- Maps Esri admin → Honua `admin`, publisher → `editor`, user → `viewer`
  at `confidence: "high"`.
- Maps custom Esri roles to `custom:<roleId>` Honua role names; if the
  privileges match a known shape (e.g. contain "edit" or "view"), the
  builtin hint is set at `confidence: "medium"`. Otherwise the entry
  carries `confidence: "low"` and a reviewer prompt.
- Emits one OIDC role-claim suggestion per Honua role
  (`claim_name: "roles"` by default).
- Groups item sharing into facade-policy stubs, one per
  `(accessLevel, sharedWithGroupIds)` bucket.

Updates to the mapper ship as PATCH changes to the scanner; they do not
bump the schema.

## What never leaves the source

By project constraint, the following are forbidden by the v0.2 schema
and by collector behavior:

- Email addresses (the schema rejects an `email` field on
  `UserPrincipal`; full-name look-alikes are dropped when they contain
  `@`).
- Password hashes, MFA seeds, OAuth client secrets, session tokens.
- URL-shaped values inside identifier or username fields (the schema
  pattern rejects them).
- Credit balances, behavioral telemetry. `lastLogin` is quantized to
  the UTC date (00:00:00Z).

Regression coverage lives in
[`tests/access/test_redaction.py`](../tests/access/test_redaction.py) and
[`tests/test_no_telemetry.py`](../tests/test_no_telemetry.py).
