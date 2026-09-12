---
type: index
title: "Honua migration documentation"
description: "Where to start depending on what you are doing: evaluating whether to migrate, getting approval to run an assessment, or consuming the artifacts one produces."
resource: "https://pypi.org/project/honua-migrate/"
tags: [migration, esri, navigation]
---
# Honua migration documentation

`honua-migrate` assesses an existing Esri estate and plans a migration off it.
The assessment is **read-only**: it inspects, records and reports, and never
writes to the system it is pointed at.

Pick the path that matches where you are.

## Evaluating whether to migrate

Start with [what this repository owns](ownership-and-deprecation.md) for the
scope, then [assess before you migrate](assessment-transition.md) for what the
read-only pass actually does. If licensing is the question, the
[Esri IP and licensing guardrails](compliance/esri-ip-and-licensing-guardrails.md)
set out the rules the tooling is built to observe.

## Getting approval to run it

[What access the assessment needs](operators/prerequisites-and-least-privilege.md)
lists every permission and why each is required — written so a security reviewer
can approve it without having to infer intent. Pair it with
[Esri license entitlement enumeration](entitlements.md), which says exactly what
is read and what is deliberately left alone.

## Running it

[Install a released version](release-installation.md) pins an exact version in
an isolated environment. If you also have `honua-sdk` installed, read
[when honua-migrate and honua-sdk collide](console-script-collision.md) first —
both declare a console script with the same name.

## Consuming what it produces

[The readiness report](readiness-report.md) explains the human-readable output,
and there is a [filled-in sample](samples/readiness-report.sample.md) if you
would rather see the shape than read about it. For machine consumers, the
[assessment handoff contract](schemas/handoff-contract.md) summarises what is
handed over, [migration artifact contracts](contracts/migration-contracts.md)
covers the packaged JSON Schemas, and the footprint schemas are documented per
version: [v0.1](schemas/esri-footprint.v0.1.md),
[v0.2](schemas/esri-footprint.v0.2.md), and
[access footprint v0.1](schemas/esri-access-footprint.v0.1.md).
[Schema versioning policy](schemas/versioning.md) says what may change under you
while the line is pre-1.0.
