# EsriFootprint v0.2 reference

- Schema id: `https://schemas.honua.io/esri-footprint/v0.2.0/esri-footprint.json`
- Schema file: [`schemas/esri-footprint-v0.2.json`](../../schemas/esri-footprint-v0.2.json)
- Canonical sample: [`docs/samples/esri-footprint.access.sample.json`](../samples/esri-footprint.access.sample.json)
- JSON Schema dialect: draft-2020-12

## What v0.2 adds

`v0.2` is the first contract line to carry the optional **access** facet
on `portal` and `server`. Everything else is identical to v0.1.

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `portal.access` | no | [`PortalAccess`](#portalaccess) | Authorized identity/RBAC export. Present only when the operator opts in with `--include-access`. |
| `server.access` | no | [`ServerAccess`](#serveraccess) | Authorized identity/RBAC export. Present only when the operator opts in with `--include-access`. |

`v0.1` and `v0.2` ship side-by-side. Consumers pinned to `0.1.x` see no
change; the closed product opts in by adding `0.2.x` to its accepted
schema list. See
[`docs/schemas/versioning.md`](./versioning.md) for the policy that drove
the bump.

> **Status (pre-1.0).** `v0.2.x` carries the same unstable promise as
> `v0.1.x`: minor bumps may break, patch bumps never break. The
> diagnostic vocabulary is unchanged from v0.1.

## PortalAccess

Optional object under `PortalFacet.access`. All required arrays are
emitted even when empty; absence of `access` means the operator did not
opt in.

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `users` | yes | [`UserPrincipal[]`](#userprincipal) | Org users observed. |
| `roles` | yes | [`RoleDefinition[]`](#roledefinition) | Custom and built-in roles. |
| `groups` | yes | [`GroupDefinition[]`](#groupdefinition) | Org groups. |
| `itemSharing` | yes | [`ItemSharing[]`](#itemsharing) | Per-item sharing state. |
| `securityPolicy` | no | [`OrgSecurityPolicy`](#orgsecuritypolicy) | Org-wide auth/security config. |
| `mappingRecommendation` | no | [`MappingRecommendation`](#mappingrecommendation) | Round-trippable Honua RBAC / OIDC / facade-policy stubs. |

## ServerAccess

Optional object under `ServerFacet.access`.

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `users` | yes | [`UserPrincipal[]`](#userprincipal) | Server users observed. |
| `roles` | yes | [`RoleDefinition[]`](#roledefinition) | Server roles. |
| `servicePermissions` | yes | [`ServicePermission[]`](#servicepermission) | Per-service permission grants. |
| `securityMode` | no | string (≤ 64 chars) | e.g. `BUILTIN`, `WEBADAPTOR`, `ARCGIS_PORTAL`. |
| `authTier` | no | string (≤ 64 chars) | e.g. `GIS_SERVER`. |
| `mappingRecommendation` | no | [`MappingRecommendation`](#mappingrecommendation) | Round-trippable Honua RBAC / OIDC / facade-policy stubs. |

## UserPrincipal

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `username` | yes | `PrincipalName` | Username; schema pattern `^[A-Za-z0-9._@-]{1,128}$` plus an explicit `not: { pattern: <RFC822-shape> }` clause that rejects email-shaped values at validation time. Subject-style ids like `alice@enterprise` remain valid. |
| `fullName` | no | string ≤ 256 | Display name; **never an email**. Email-shaped values are dropped by the scanner, and credential-shaped free-text fragments (`token=`, `Bearer `, URL userinfo) are scrubbed via the shared `redact()` pass before emission. |
| `roleId` | no | `Identifier` | Esri role id; schema pattern `^[A-Za-z0-9._-]{1,128}$`. |
| `userType` | no | string ≤ 128 | License tier label (e.g. `creatorUT`). |
| `status` | yes | enum | `active`, `disabled`, `unknown`. |
| `lastLogin` | no | RFC3339 UTC | Quantized to `00:00:00Z` so the artifact carries no behavioral telemetry. |
| `groupIds` | yes | `Identifier[]` | Group membership ids. |

Email addresses, password hashes, MFA seeds, OAuth client secrets, and
session tokens are forbidden by schema (`additionalProperties: false`).

## RoleDefinition

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `id` | yes | `Identifier` | Stable Esri role id. |
| `name` | yes | string ≤ 256 | Display name. |
| `scope` | yes | enum | `admin`, `publisher`, `user`, `custom`. |
| `privileges` | yes | string[] | Verbatim Esri privilege names. |
| `description` | no | string ≤ 512 | Free text; the scanner runs the documented `redact()` pass on it before emission. |

## GroupDefinition

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `id` | yes | `Identifier` | Group id. |
| `title` | yes | string ≤ 256 | Group title. |
| `access` | yes | enum | `private`, `org`, `public`, `shared`. |
| `owner` | yes | `PrincipalName` | Owning username. |
| `capabilities` | yes | string[] | Group capability flags. |
| `isInvitationOnly` | yes | boolean | |
| `isViewOnly` | yes | boolean | |
| `memberCount` | no | integer ≥ 0 | Bounded by `--access-group-cap`. |
| `sharedItemCount` | no | integer ≥ 0 | |

## ItemSharing

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `itemId` | yes | `Identifier` | Portal item id. |
| `owner` | yes | `PrincipalName` | Owning username. |
| `accessLevel` | yes | enum | `private`, `org`, `public`, `shared`. |
| `sharedWithGroupIds` | yes | `Identifier[]` | Group ids the item is shared with. |

## ServicePermission

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `serviceUrl` | yes | URI | Credentials-stripped service URL; pattern rejects userinfo, query, fragment. |
| `principal` | yes | `PrincipalName` | Username, role id, or group id. |
| `principalKind` | yes | enum | `user`, `role`, `group`. |
| `capabilities` | yes | string[] (≥ 1) | Granted ArcGIS Server operations. |

## OrgSecurityPolicy

All fields are optional; producers default to omission when the source
endpoint does not expose the value.

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `mfaRequired` | no | boolean | |
| `signInMethods` | yes | string[] | e.g. `oidc`, `saml`, `builtin`. |
| `passwordMinLength` | no | integer 0–1024 | |
| `passwordComplexity` | no | boolean | |
| `allowedOrigins` | yes | string[] | Origin URLs allowed by the org. Pattern bounds the character class. |
| `sessionExpiryMinutes` | no | integer 0–525600 | |

## MappingRecommendation

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `honuaRoles` | yes | [`HonuaRoleMapping[]`](#honuarolemapping) | Esri-role → Honua-role suggestions. |
| `oidcRoleClaims` | yes | [`OidcRoleClaimMapping[]`](#oidcroleclaimmapping) | OIDC role-claim suggestions per Honua role. |
| `facadeAccessPolicies` | yes | [`FacadeAccessPolicy[]`](#facadeaccesspolicy) | Portal-facade access-policy stubs. |

### HonuaRoleMapping

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `esriRoleId` | yes | `Identifier` | |
| `honuaRole` | yes | string ≤ 128 | Either a builtin (`admin`, `editor`, `viewer`) or `custom:<id>`. Deterministically bounded to 128 chars: `custom:<id>` values where the prefixed body would overflow are truncated and suffixed with `.<sha1[:8]>`. |
| `builtin` | no | enum | `admin`, `editor`, `viewer`. |
| `confidence` | yes | enum | `high`, `medium`, `low`. |
| `rationale` | yes | string ≤ 512 | Reviewer-facing explanation. |

### OidcRoleClaimMapping

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `honuaRole` | yes | string ≤ 128 | Honua role name. |
| `claimName` | yes | string ≤ 128 | OIDC claim name (default `roles`). |
| `claimValue` | yes | string ≤ 128 | OIDC claim value. |
| `confidence` | yes | enum | `high`, `medium`, `low`. |

### FacadeAccessPolicy

| Field | Required | Type | Description |
| --- | --- | --- | --- |
| `policyId` | yes | string ≤ 256 | Stable id derived from access level and group set. Deterministically bounded to 256 chars: long bodies are truncated and suffixed with `.<sha1[:8]>` so consumers can still dedupe across runs. |
| `accessLevel` | yes | enum | `private`, `org`, `public`, `shared`. |
| `itemIds` | yes | `Identifier[]` | Items covered by the policy. |
| `groupIds` | yes | `Identifier[]` | Groups the policy delegates to. |
| `confidence` | yes | enum | `high`, `medium`, `low`. |

## Diagnostic vocabulary

Unchanged from v0.1 (six codes, locked). See
[`docs/schemas/esri-footprint.v0.1.md`](./esri-footprint.v0.1.md#diagnostic-code-catalog).

## Validating an artifact

```bash
honua-esri-assess schema validate path/to/EsriFootprint.json
```

The CLI reads `schemaVersion` from the input and picks the matching
schema. `v0.1.x` consumers and `v0.2.x` consumers can both validate.
