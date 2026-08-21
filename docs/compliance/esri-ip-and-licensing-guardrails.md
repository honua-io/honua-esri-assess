# Esri IP & Licensing Clean-Room Guardrails

> **Not legal advice.** This document is engineering policy guidance for
> contributors. It records the project's standing posture so that routine
> changes stay defensible by default. It is **not** a legal opinion and does not
> substitute for counsel. Legal determinations — including any close call on
> fair use, licensing, trademark, or comparative-claims publishing — are owned
> by legal counsel, not by this repository or its maintainers. When in doubt,
> stop and escalate rather than guess.

This is the documentation deliverable of the coordination epic
[#33 "Esri IP & licensing compliance guardrails"](https://github.com/honua-io/honua-migrate/issues/33).
The epic itself stays open as a living coordination surface for per-ticket
constraint review and counsel sign-offs; this doc captures the durable policy
those activities apply.

## TL;DR

- **API reimplementation is not constrained here.** Reimplementing Esri's
  documented web APIs (GeoServices REST, Portal/Sharing REST, `generateToken`,
  the ArcGIS JS API compatibility shim) is fair use of functional interfaces
  under *Google LLC v. Oracle America, Inc.*, 593 U.S. 1 (2021). We do not gate
  this work.
- **The real exposure is elsewhere.** Guard proprietary **file formats**,
  Esri-licensed **data/content**, proprietary creative **assets** (symbols,
  fonts), software **EULA** terms, and **benchmark/comparison** publishing.
- **Clean-room provenance is mandatory** for format and protocol work: build
  from published specs or independent community readers only. Never decompile,
  disassemble, or run licensed Esri software to learn internals.
- **Per-ticket checklist** (below) applies whenever a change touches formats,
  data, assets, or benchmarks. Benchmark/comparison publishing is gated on
  counsel sign-off.

## Scope

This repo (`honua-esri-assess`) is a read-only assessment scanner, so most of
its surface is low-risk. The guardrails below are written for the broader Honua
Esri-migration backlog (the tickets listed under "Applies to") and apply to any
contribution in this repo that touches the exposure areas. Use them as the
default posture; counsel decisions override them.

## 1. API reimplementation is fair use — not constrained

Reimplementing the **functional interface** of Esri's documented web APIs is
treated as fair use of an API, consistent with *Google v. Oracle* (2021), where
the Supreme Court held that reuse of a software interface's declaring
code/structure to build new, interoperable functionality was fair use.

Concretely, the following are **not** gated by this policy:

- **GeoServices REST API** request/response shapes, query/edit operations, and
  endpoint paths.
- **Portal / Sharing REST API** endpoints and item/group/user models needed for
  interoperability.
- **`generateToken`** and equivalent auth-flow endpoints.
- An **ArcGIS JS API compatibility shim** that exposes a compatible
  client-facing surface.

What this permits: independently implementing those interfaces so existing Esri
clients and content interoperate with Honua. What it does **not** permit: copying
Esri's *implementation* source, copying non-functional creative material, or
ignoring the format/data/asset/EULA guardrails below just because an API is
involved. "It's an API" is not a blanket waiver — it scopes only the
interface-reimplementation question.

## 2. Real exposure areas to guard

### 2.1 Proprietary file formats (clean-room)

Some Esri formats are proprietary and/or read through licensed Esri SDKs. Build
support **clean-room**:

- **Allowed sources:** publicly published format specifications, open standards
  (e.g. OGC), and independent open-source community readers/writers with
  compatible licenses (e.g. GDAL/OGR `OpenFileGDB`).
- **Forbidden sources:** decompiling, disassembling, or reverse-engineering
  licensed Esri binaries; running licensed Esri software (ArcGIS Pro, the Esri
  FileGDB SDK, ArcObjects, etc.) for the purpose of learning a format's internal
  structure; copying layout details from Esri SDK headers or sample code whose
  license forbids it.
- **File GDB specifically:** read via **GDAL `OpenFileGDB`**, not the closed Esri
  FileGDB SDK. This repo already follows that rule (see
  [README "Decisions"](../../README.md#decisions): "no ELv2 closed-product code
  is vendored").
- **Other formats in the backlog:** I3S/SLPK, tile cache packages (`.tpk`/
  `.tpkx`), web map / web scene JSON, mobile map packages, and similar — same
  rule: published spec or community reader; never decompile/run-to-learn.

### 2.2 Esri-licensed data and content (no rehosting)

- Do **not** rehost, redistribute, or bundle Esri-licensed datasets, basemaps,
  imagery, geocoding/routing reference data, or other content delivered under an
  Esri subscription/EULA.
- Scanning or referencing a customer's *own* content in place (read-only, as this
  tool does) is fine; copying that content into Honua-operated storage or
  fixtures is not.
- Test fixtures must use synthetic or clearly-licensed sample data — never a
  copy of Esri-provided content.

### 2.3 Proprietary creative assets (no embedding)

- Do **not** embed or redistribute Esri's proprietary **symbol sets**, **icon/
  marker libraries**, **fonts/glyphs**, **color ramps as creative works**, or
  **cartographic styles** that are protected creative material.
- Symbology *translation* (mapping an Esri symbol definition to a Honua
  equivalent at runtime, server-side) is an interface/data-shape activity and is
  generally fine — but the **artwork** itself (the actual glyph/font/marker bytes)
  must come from an appropriately licensed or original source, not from Esri's
  proprietary asset libraries.

### 2.4 Software EULA terms

- Respect the terms of any Esri software a contributor has licensed. In
  particular, do not use licensed Esri software in ways its EULA prohibits
  (notably reverse engineering / benchmark-publishing clauses) as an input to
  this project.
- Do not vendor code from licensed Esri SDKs into this repo.

### 2.5 Benchmark / comparison publishing (counsel-gated)

- Any **published** Esri-vs-Honua benchmark, performance-parity claim, or
  feature/accuracy comparison must be **gated behind legal counsel sign-off**
  before publication. Esri software EULAs commonly restrict benchmark
  publication, and comparative claims carry trademark/advertising-law exposure.
- Internal measurements used only to guide engineering are fine; the gate is on
  *external publication* of comparative claims.

### 2.6 Trademark / nominative use

- Where Esri marks (Esri®, ArcGIS®, etc.) appear in user-facing material, use
  them only **nominatively** (to refer to the actual Esri product) and include a
  non-affiliation disclaimer: Honua is not affiliated with, endorsed by, or
  sponsored by Esri, and all third-party marks belong to their owners.

## 3. Per-ticket compliance checklist

Apply this when a change touches **formats, data, assets, or benchmarks**. For
backlog tickets, mirror the relevant items into the ticket's
**Compliance Constraints** section so the constraint travels with the work.

- [ ] **Does this touch a proprietary file format?** If yes, confirm the
      implementation is built from a published spec or an independent community
      reader (e.g. GDAL `OpenFileGDB`) — and that no licensed Esri binary was
      decompiled or run to learn the format. Record the provenance (see §4).
- [ ] **Does this read/move Esri-licensed data or content?** If yes, confirm it
      is read-only/in-place and that no licensed data/content is rehosted,
      bundled, or copied into fixtures.
- [ ] **Does this embed creative assets?** If yes, confirm no proprietary Esri
      symbols, fonts/glyphs, markers, or styles are embedded; assets are
      original or appropriately licensed.
- [ ] **Is licensed Esri software involved as an input?** If yes, confirm the use
      does not violate that software's EULA (especially reverse-engineering and
      benchmark clauses).
- [ ] **Does this publish a benchmark or comparative claim?** If yes, **stop and
      route to legal counsel for sign-off before publication.** Do not merge the
      publishing artifact until sign-off is recorded.
- [ ] **Do Esri trademarks appear in user-facing output?** If yes, confirm
      nominative use plus a non-affiliation disclaimer.
- [ ] **Unsure on any item?** Escalate to maintainers/counsel rather than
      guessing. Default to the more conservative interpretation.

## 4. Clean-room provenance expectations

For format and protocol work, capture provenance so the clean-room posture is
auditable:

- **Cite the source** of every format/protocol detail: link the published spec,
  standard, or the upstream community reader/writer used. Prefer durable links
  and pin versions where practical.
- **State what was NOT used:** the implementation did not rely on decompiling,
  disassembling, or running licensed Esri software to learn internals.
- **Keep a paper trail:** a short provenance note in the PR description (or the
  ticket's Compliance Constraints section) is sufficient — e.g. "File GDB reads
  use GDAL `OpenFileGDB`; format understanding from the GDAL driver docs and the
  published OGC/Esri specification; no Esri FileGDB SDK or ArcGIS Pro used."
- **Separation of concerns:** where feasible, keep interface/spec study separate
  from implementation so the lineage is clear.

## 5. Relationship to epic #33

Epic #33 coordinates these guardrails across the migration backlog. Per its
scope:

- **In scope for the epic:** per-ticket constraint coordination, maintaining the
  clean-room provenance posture, and the counsel-review gate for
  benchmark/comparison publishing.
- **Out of scope for the epic:** legal advice / final legal determinations
  (counsel owns those) and direct implementation in the parent epic.

This document is the epic's durable policy artifact. The epic remains open for
ongoing per-ticket coordination and counsel sign-offs.
