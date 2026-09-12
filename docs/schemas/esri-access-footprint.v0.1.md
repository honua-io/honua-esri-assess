---
type: reference
title: "esri-access-footprint v0.1 schema"
description: "The access-footprint schema: what the assessment records about permissions and reachability, separate from the estate itself."
resource: "https://github.com/honua-io/honua-migrate/tree/trunk/schemas"
tags: [schema, access, permissions]
---
# EsriAccessFootprint v0.1 reference

- Schema id: `https://schemas.honua.io/esri-access-footprint/v0.1.0/esri-access-footprint.json`
- Schema file: [`schemas/esri-access-footprint-v0.1.json`](../../schemas/esri-access-footprint-v0.1.json)
- JSON Schema dialect: draft-2020-12

## Purpose

`EsriAccessFootprint.json` is a documented **sibling** of
[`EsriFootprint.json`](./esri-footprint.v0.1.md). Where `EsriFootprint.json`
inventories *content*, the access footprint captures the estate's
**identity / RBAC posture**: users, roles + privileges, groups, per-service
permissions, item sharing, and org security configuration.

Auth is the hardest, most-manual migration step. This artifact is read-only,
prospect-safe, and drives the **Honua RBAC** model and the **Portal facade**
access policies (see the mapping transform below).

## Promises (same constraints as EsriFootprint.json)

- **Read-only.** The scanner only issues HTTP `GET`s against documented
  endpoints and never writes to the source Esri system. ArcSDE/GDB internals
  are never parsed.
- **No credentials in the artifact.** `source.locator` and every
  `servicePermissions[].serviceUrl` are sanitized; the schema patterns reject
  any residual userinfo (`@`), query string (`?`), fragment (`#`), or
  whitespace. Passwords and tokens are never modeled into any field.
- **Prospect-safe diagnostics.** `diagnostics[].code` is the same locked v0.1
  enum used by `EsriFootprint.json`.

## Source endpoints (all read-only)

| Target          | Endpoints |
|-----------------|-----------|
| ArcGIS Online / Enterprise Portal | `/sharing/rest/portals/self`, `/sharing/rest/portals/self/users`, `/sharing/rest/portals/self/roles`, `/sharing/rest/portals/self/roles/<id>/privileges`, `/sharing/rest/community/groups` |
| ArcGIS Server admin | `/arcgis/admin/security/roles/getRoles`, `/arcgis/admin/security/users/getUsers`, `/arcgis/admin/services/<svc>/permissions` |

## Top-level shape

`additionalProperties: false`. A single artifact describes one source.

| Field                | Required | Type                          | Description |
|----------------------|----------|-------------------------------|-------------|
| `schemaVersion`      | yes      | const `"v0.1"`                | Contract major.minor carried in-band. |
| `generatedAt`        | yes      | RFC3339 UTC                   | When the scan finished. |
| `tool`               | yes      | `{ name, version }`           | Scanner provenance (`name` const `honua-esri-assess`). |
| `source`             | yes      | `{ kind, locator, capturedAt }` | `kind` is `arcgis-online` or `arcgis-server`. |
| `users`              | yes      | `User[]`                      | Identity principals. |
| `roles`              | yes      | `Role[]`                      | Roles + granted privileges. |
| `groups`             | yes      | `Group[]`                     | Groups + membership linkage. |
| `servicePermissions` | yes      | `ServicePermission[]`         | Per-service allow/deny ACEs. |
| `itemSharing`        | yes      | `ItemSharing[]`               | Item sharing posture. |
| `orgSecurity`        | yes      | `OrgSecurity`                 | Allowed providers, MFA, anonymous access, default role. |
| `diagnostics`        | yes      | `Diagnostic[]`                | Typed, prospect-safe diagnostics. |

All array fields may be empty (e.g. when the calling token lacks admin scope,
the scanner emits a `missing-permission` diagnostic and an empty list rather
than failing the export).

See the JSON Schema for per-object field tables (`User`, `Role`, `Group`,
`ServicePermission`, `ItemSharing`, `OrgSecurity`).

## Auth-mapping transform

`honua_esri_assess.footprint.access_mapping.map_to_honua_rbac` is a pure
function over an access footprint that emits the typed mapping target the
closed migration product consumes:

- `honuaRoles` — one Honua role per Esri role, with the Honua permission
  verbs the role's privileges imply. Unmapped Esri privileges are surfaced in
  `unmappedPrivileges` rather than dropped.
- `oidcRoleClaims` — OIDC `roles` claim value → Honua role id, so the IdP can
  drive role assignment after migration.
- `accessPolicies` — Portal-facade allow/deny policies, one per observed
  service permission and per item-sharing record, with role principals
  resolved to their Honua role ids.

This v0.1 mapping is a documented *first* table covering common Esri built-in
privileges; it is intentionally conservative.

## Stability policy

Same as `EsriFootprint.json`: v0.x is unstable (breaking changes permitted
between minor bumps); v1.0 is the first stable promise. Pin on
`schemaVersion`.

## Deferred at v0.1 (out of scope of the foundational slice)

- A `scan rbac` CLI surface and `EsriAccessFootprint.json` write path.
- Per-service ACE enumeration from `/arcgis/admin/services/<svc>/permissions`
  (the `ServicePermission`/`ItemSharing` shapes are defined and validated; the
  scanner skeleton models them via helpers but does not yet crawl every
  service/item).
- Effective-permission resolution across role + group + item inheritance.
- SAML/OIDC attribute-mapping detail beyond provider enumeration.
