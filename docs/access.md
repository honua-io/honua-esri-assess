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
| `--max-retries INT` | `3` | Bounded retries with exponential backoff that the access HTTP client applies on transient `429`/`502`/`503`/`504` responses (and on the HTTP-200 envelope-`429` shape some Esri proxies emit). The same flag drives the v0.1 inventory scanner; access requests reuse the operator's chosen attempt budget. |

`--include-access` raises a typed CLI diagnostic (`access-token-required`)
when no `--token-env` is supplied. The collector retains the read-only
stance — the underlying HTTP wrapper exposes only `get_json`.

Portal access enumeration is scoped to the org returned by
`portals/self`: the collector passes `q=orgid:{orgId}` on every
`community/groups` and `community/users` page so the prospect's
admin-tier token cannot widen the export to the community-shared
surface beyond the org it operates. Server access permission probes
are bounded to services that survived the v0.1 inventory walk —
services dropped by terminal `server.service.*` diagnostics are also
skipped by the access collector so the artifact never describes
permissions for rows it does not carry.

## Diagnostics surface

Soft coverage gaps surface as locked-vocabulary diagnostics inside
`diagnostics[]`:

| Code | When |
| --- | --- |
| `missing-permission` | The admin-tier token cannot read an endpoint. |
| `partial-coverage` | A group membership probe exceeded `--access-group-cap`; a paginated admin endpoint kept advertising more pages after the per-call cap (10,000 records) was hit; an item arrived with `accessLevel=shared` but no populated `sharedWithGroupIds` (the v0.1 inventory does not capture per-item group membership, so the mapper omits the facade-policy stub for those items); or a response shape was unexpected but recoverable. |
| `unresolved-reference` | An expected admin endpoint returned 404. |
| `redacted-field` | The scanner deliberately omitted a field whose payload was not prospect-safe (URL-shaped item ids, URL-shaped owners, etc.), OR truncated a free-text string to its v0.2 schema cap (`fullName`/`name`/`title` at 256, role `description` at 512, `privileges`/`capabilities` items at 128/64, `userType` at 128, server `securityMode`/`authTier` at 64). Truncation diagnostics carry the originating scope so consumers can see which surface was bounded. |

Soft access diagnostics are written into the same `diagnostics[]`
top-level array as the v0.1 inventory diagnostics, so closed-product
consumers of the sole handoff artifact see access coverage gaps on
the existing diagnostic pipeline without subscribing to a sibling
array. CLI stderr mirrors the same lines.

Hard failures raise `AccessExportError` subclasses
(`AccessAuthError`, `AccessForbiddenError`, `AccessNotFoundError`,
`AccessRateLimitedError`, `AccessConnectionError`, `AccessApiError`,
`AccessSchemaError`). The CLI maps them to a typed stderr diagnostic
(`access-export-failed`); no raw Python tracebacks are printed.
`AccessSchemaError` also covers malformed Esri error envelopes (for
example a non-integer `code` from a broken proxy), keeping the
failure inside the typed-error pipeline instead of escaping as
`internal-error`.

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

Mapper-derived identifiers (`HonuaRoleMapping.honuaRole`,
`FacadeAccessPolicy.policyId`) are deterministically bounded to the
v0.2 schema caps. When `prefix + body` exceeds the cap, the mapper
emits `prefix + truncated_body + "." + sha1(full_body)[:8]` so
closed-product consumers can still dedupe across runs without the
suffix overflowing schema validation.

Facade-policy stubs are generated only for items with `accessLevel` in
{`private`, `org`, `public`}, or `accessLevel=shared` with a non-empty
`sharedWithGroupIds`. Items with `accessLevel=shared` and unknown
(empty) group ids are excluded from `facadeAccessPolicies` so the
recommendation does not imply org-wide sharing when the source
actually had a group boundary the v0.1 inventory could not capture;
the portal collector emits a `partial-coverage` diagnostic at scope
`portal.access.itemSharing` so the data gap is visible.

## What never leaves the source

By project constraint, the following are forbidden by the v0.2 schema
and by collector behavior:

- Email addresses. The v0.2 `PrincipalName` schema carries an
  explicit `not: { pattern: <RFC822-shape> }` clause, so
  `alice@example.com`-shaped usernames, group owners, and service
  principals are rejected at validation time. The collectors mirror
  that rule via `access.diagnostics.is_safe_principal_name` and emit
  a `redacted-field` diagnostic when an Esri payload would have
  carried such a value. Subject-style ids like `alice@enterprise`
  (no TLD-shaped suffix) stay valid because they remain useful for
  SAML/OIDC mapping.
- Password hashes, MFA seeds, OAuth client secrets, session tokens.
- URL-shaped values inside identifier or username fields (the schema
  pattern rejects them).
- Credential-shaped fragments inside otherwise valid free-text
  fields. Group titles, user `fullName`, role display names, role
  descriptions, and security-policy origins are routed through the
  shared `diagnostics.redact()` pass before emission, so a hostile or
  careless admin cannot ride a `token=...`, `Bearer ...`, or
  userinfo-bearing URL into the artifact even when the surrounding
  field passes its shape check. `OrgSecurityPolicy.allowedOrigins`
  entries with userinfo are reduced to credential-free origins (e.g.
  `https://allowed.local`) and dropped with a `redacted-field`
  diagnostic when they still cannot satisfy the schema pattern.
- Credit balances, behavioral telemetry. `lastLogin` is quantized to
  the UTC date (00:00:00Z).

Regression coverage lives in
[`tests/access/test_redaction.py`](../tests/access/test_redaction.py) and
[`tests/test_no_telemetry.py`](../tests/test_no_telemetry.py).
