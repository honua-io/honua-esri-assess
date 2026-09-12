---
type: guide
title: "What access the assessment needs"
description: "Exactly which Esri permissions an assessment requires and why each one is needed, written so a security reviewer can approve it without guessing."
tags: [permissions, least-privilege, security]
---
# Prerequisites & least-privilege access

This page tells a prospective customer exactly **what access `honua-esri-assess`
needs to run, and the minimum privileges to grant**. It is written for the
security/IT reviewer who has to approve pointing a tool at a production ArcGIS
deployment.

## TL;DR

- **The scanner is strictly read-only.** Every request is an HTTP `GET`. It
  issues no `POST`/`PUT`/`DELETE`/`PATCH`, and never writes to the source Esri
  system.
- **It brings no credentials of its own and mints none.** You either run it
  anonymously or hand it a **pre-existing token** you generated out of band. It
  does **not** take a username/password and does **not** call `generateToken`.
- **It never opens your databases.** Storage type is read only from documented
  ArcGIS data-store *registrations* — it never connects to ArcSDE/the DBMS or
  parses GDB internals.
- **Secrets stay secret.** Tokens are passed via an environment variable, are
  redacted from logs, and are **never written into any output artifact**.
- **No phone-home.** The only host it talks to is the ArcGIS target *you*
  specify. There is no telemetry/analytics egress (enforced by a repo test).

## Two access tiers

The tool is designed around two deliberately separate tiers so you can start
with zero credentials and only escalate if you want deeper ground truth.

| Tier | Purpose | Credentials | Privilege |
|------|---------|-------------|-----------|
| **Tier 1 — prospect-safe public scan** | Inventory the publicly reachable footprint (services, layers, portal items/groups). | **None** (anonymous), or any read-only/viewer token if anonymous access is disabled. | Whatever an anonymous/viewer user can already see. |
| **Tier 2 — authorized deep scan** | Ground truth: RBAC, real usage, data-store registrations, licensing. | A **pre-existing token** for an account authorized to the ArcGIS **Admin API**. | Administrative read access (see the honest caveat below). |

You can deliver value at Tier 1 with **no credentials at all**. Tier 2 is opt-in.

## What you provide

### 1. Target URLs

| Input | Example | Used by |
|-------|---------|---------|
| ArcGIS **Server** base URL | `https://gis.example.com/arcgis` | `scan server --target …` — appends `/rest/info`, `/rest/services` (Tier 1) and, for the authorized tier, `/admin/...` |
| **Portal / ArcGIS Online** Sharing REST URL | AGOL: `https://yourorg.maps.arcgis.com/sharing/rest` · Enterprise: `https://gis.example.com/portal/sharing/rest` | `scan agol --target …` — the scanner appends `portals/self`, `search`, `content/items/<id>` directly |
| FileGDB / workspace path | `/data/parcels.gdb` | `scan filegdb` / `scan filegdb-workspace` (local filesystem, no network) |

You pass the target with `--target`; you do not hand it admin consoles or DB
connection strings.

### 2. Credentials (optional)

- **Anonymous (default):** pass nothing. Tier-1 scans run against the public
  surface; anything that requires auth degrades to a typed diagnostic (e.g.
  "user count skipped") rather than failing the scan.
- **Token:** supply the **name of an environment variable** holding a token via
  `--token-env` (e.g. `--token-env ESRI_TOKEN`). The token is sent as the
  standard Esri `?token=` parameter. **The token is never accepted directly on
  the command line** (so it can't land in shell history) and never appears in
  logs or artifacts.

You generate the token yourself using your normal Esri flow
(Portal `generateToken` / OAuth2). The tool intentionally stays out of
username/password handling.

## Endpoints the scanner reads

All read-only `GET`, `f=json`.

### Tier 1 — public REST surface (no credentials required)

| Endpoint | What it reads |
|----------|---------------|
| `…/arcgis/rest/info`, `…/rest/info` | Server/owning-system metadata |
| `…/arcgis/rest/services` (recursive) | Service + layer catalog |
| `…/sharing/rest/portals/self` | Portal/org metadata |
| `…/sharing/rest/portals/self/users`, `…/community/users` | User **counts** only (auth-gated; skipped if not permitted) |
| `…/sharing/rest/community/groups` | Group listing |
| `…/sharing/rest/search` | Paginated item listing |
| `…/sharing/rest/content/items/<id>` | Per-item probe |

### Tier 2 — authorized Admin API (token required)

| Endpoint | What it reads |
|----------|---------------|
| `…/arcgis/admin/info`, `…/arcgis/admin/system/licenses` | Entitlements / licensing |
| `…/arcgis/admin/security/users/getUsers`, `…/security/roles/getRoles` | Identity & roles/privileges (RBAC export) |
| `…/arcgis/admin/services/<service>/permissions` | Per-service access-control entries |
| `…/arcgis/admin/usagereports` | Real service usage (prioritization) |
| `…/arcgis/admin/data/items` | Data-store **registrations** (storage type → binding-mode hint) |
| Portal `…/sharing/rest/community/groups`, `security/users`, `security/roles` | Portal-side identity/roles |

> The authorized RBAC/usage scanners ship as library modules today; the
> dedicated `scan rbac` / usage CLI surface is on the roadmap. The endpoints and
> privilege requirements above are what that tier reads.

## Least privilege — what to actually grant

### Tier 1
**Grant nothing.** Run anonymously. If your org has disabled anonymous browsing,
issue a token for a plain **Viewer** account — no admin, no publisher, no
sharing privileges needed. It only ever sees what that viewer can already see.

### Tier 2 (the honest caveat)
The ArcGIS **Server Admin API** (`/arcgis/admin/*`: `usagereports`,
`data/items`, `system/licenses`, `security/*`, `services/<>/permissions`) does
**not** expose a granular read-only role — access is gated behind an
**administrative** connection to the server (the primary site administrator or
an account in the **Administrator** role). So even though the tool only issues
`GET`s, the *token it carries* must belong to an admin-authorized identity.

On the **Portal/Enterprise** side you have more control: you can define a
**custom role with view-only privileges** (e.g. view members, view groups, view
org settings) and the portal-facing reads will work under it.

**Recommended posture for Tier 2:**

1. Create a **dedicated, named service account** used only for the assessment —
   not a shared admin login.
2. On Portal, scope it to a **custom view-only admin role**; on ArcGIS Server,
   accept that Admin-API reads require admin authorization and document that the
   account is used **read-only** (the tool issues only `GET`s — verifiable in
   your gateway/proxy logs).
3. Mint a **short-lived token** for that account (short TTL / referer-scoped),
   provide it via the `--token-env` environment variable, and **revoke it
   immediately after the scan**.
4. Optionally run behind a forward proxy that **allow-lists `GET`** to your
   ArcGIS host, giving you an independent audit that nothing was written.

## Network & data handling

- **Egress:** only to the ArcGIS host you target. No Honua/telemetry/analytics
  endpoints exist in the source (enforced by `tests/test_no_telemetry.py`).
- **Artifacts:** the emitted `EsriFootprint.json` (and the access/usage
  artifacts) carry inventory and coarse classifications only. Connection
  strings, hosts, and credentials are **not** retained — URLs are sanitized and
  a redaction test guards this.
- **Databases:** never contacted. Storage type comes from ArcGIS data-store
  registration metadata, never from ArcSDE/DBMS internals.

## Pre-run checklist

- [ ] Decide tier: Tier 1 (no creds) is enough for a footprint + migratability
      verdict.
- [ ] Have the target URL(s): ArcGIS Server base and/or Portal/AGOL URL.
- [ ] (Tier 2 only) Provision a dedicated read-only-intent service account,
      mint a short-lived token, export it to an env var, pass `--token-env`.
- [ ] Confirm network reachability from the run host to the ArcGIS target.
- [ ] (Optional) Front the run with a `GET`-only allow-list proxy for an
      independent read-only audit trail.
- [ ] Revoke the token after the run.

---

*This is operational guidance, not a security or legal determination; validate
against your own org's policies. See also the
[Esri IP & licensing clean-room guardrails](../compliance/esri-ip-and-licensing-guardrails.md).*
