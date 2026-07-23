# AGENTS.md

## Overview

`honua-esri-assess` is an open-source (Apache-2.0), **read-only** Esri footprint
assessment CLI used for Honua migration discovery. It scans ArcGIS Online,
ArcGIS Server, and FileGDB inventories and emits a single versioned handoff
artifact, `EsriFootprint.json` (v0.1 schema), plus an optional human-readable
Markdown readiness report.

Hard project constraints (do not violate):
- The legacy assessment modules and `honua-migrate assess` are strictly read-only
  against Esri systems — only HTTP `GET`s, never `POST`/`PUT`/`DELETE`. No write
  helpers exist in their HTTP wrappers. Write-capable target operations belong only
  under `honua_migrate`, and must be protected by reviewable plan and explicit apply
  gates.
- No network telemetry, usage pings, crash uploads, or update checks. These are
  off by default and there is no opt-in sink. Tests enforce this.
- `EsriFootprint.json` is the sole supported handoff into the closed Honua
  product. Credentials, tokens, query strings, and URL userinfo must never be
  written into the artifact, diagnostics, cache keys, or logs.

## Tech Stack

- Language: Python, `requires-python = ">=3.11"` (CI tests 3.11, 3.12, 3.13).
- Build backend: Hatchling (`hatchling>=1.24`), PEP 517.
- CLI framework: Typer / Click.
- Runtime deps: `jsonschema>=4.21,<5`, `requests>=2.31,<3`,
  `tenacity>=8.2,<10`, `typer>=0.12,<1`.
- Optional extra `filegdb`: `pyogrio>=0.12,<0.13` (GDAL/OGR read-only metadata).
- Dev tooling: `pytest`, `ruff`, `mypy`, `build`, `hatch`, `responses`,
  `packaging`.

## Setup

Install in editable mode with the dev extra (matches CI):

```bash
python3 -m pip install -e ".[dev]"
```

For the fixture-backed smoke suite only:

```bash
python -m pip install -e ".[smoke]"
```

To use the `pyogrio` FileGDB workspace scanner library, also install the
`filegdb` extra (requires GDAL): `pip install -e ".[filegdb]"`.

## Commands

Run from the repo root. These are copied from CI (`.github/workflows/ci.yml`)
and `pyproject.toml`.

- Unit tests (excludes smoke): `pytest tests --ignore=tests/smoke`
- Full test suite: `pytest`
- Smoke tests: `pytest tests/smoke -v`
- Lint: `ruff check`
- Type check: `mypy`
- Dependency license guard: `python scripts/check_dep_licenses.py`
- Build distribution: `python -m build`
- Run the CLI: `honua-esri-assess <command>` or `python -m honua_esri_assess <command>`

pytest config (`pyproject.toml`): `pythonpath = ["src"]`, `testpaths = ["tests"]`,
`addopts = ["--import-mode=importlib"]`.

### CLI surface

`scan agol`, `scan server`, `scan filegdb` (descriptor only), `scan rbac`,
`schema show`, `schema validate <file>`, `report`, `version` (and root
`--version`). Tokens are supplied only via `--token-env VAR` — there is
intentionally no `--token` flag. `scan` writes `./EsriFootprint.json` by
default; pass `--validate` to validate against the bundled schema before
writing. `scan rbac` instead writes the sibling `EsriAccessFootprint.json`
(read-only RBAC export; `--kind portal|server`, default to stdout).

## Architecture

The package lives under `src/honua_esri_assess/`. Entry point is
`honua_esri_assess.cli:main` (declared in `[project.scripts]`), which runs the
Typer app `app.py:cli_app` with `standalone_mode=False` and maps Click
exceptions to process exit codes.

Layered design:
- `app.py` / `cli.py` — Typer app assembly and exit-code mapping.
- `commands/` — CLI command implementations (`scan`, `schema`, `report`,
  `version`, `common`) plus `commands/scan_handlers/` (per-backend handlers:
  `agol`, `server`, `filegdb`). See `docs/handler-interface.md`.
- Scanners by backend:
  - `portal/` — ArcGIS Online Portal Sharing REST client/scanner.
  - `server/` — ArcGIS Server REST client/catalog/scanner.
  - `filegdb/` — descriptor scanner + `pyogrio_reader` workspace scanner
    (`scan_filegdb_workspace`, library-only, no CLI surface).
  - `scanners/` — shared HTTP and per-backend scanner glue.
- `footprint/` — builds/validates the `EsriFootprint.json` v0.1 artifact
  (`artifact.py`, `v0_1.py`, `schema.py`, `licensing.py`).
- `report/` — pure Markdown readiness-report renderer (renderer, heuristics,
  validation, formatting); performs no file/network/log I/O.
- `entitlements/` — read-only entitlement enumeration library (portal/server),
  available for future `scan` integration; the standalone CLI was retired.
- `diagnostics.py`, `redaction.py`, `logging.py`, `log_config.py`, `schema.py` —
  cross-cutting: locked diagnostic-code vocabulary, secret redaction, logging.
- `schemas/esri-footprint-v0.1.json` — the JSON Schema packaged into the wheel
  (force-included from top-level `schemas/`).

## Directory Layout

```
src/honua_esri_assess/   # package source (layered as above)
tests/                   # unit tests + subpackage suites (server/, footprint/,
                         #   entitlements/, report/, portal/) and fixtures/
tests/smoke/             # fixture-backed end-to-end pipeline (separate CI job)
schemas/                 # canonical EsriFootprint JSON Schema (source of truth)
docs/                    # schema reference, samples, readiness-report,
                         #   entitlements, handler-interface, versioning docs
scripts/                 # check_dep_licenses.py, validate_publish_tag.py
.github/workflows/       # ci.yml, release-please.yml, publish.yml
```

## Conventions & Gotchas

- Diagnostic codes in `EsriFootprint.json` (`diagnostics[].code`) are a **locked
  enum** in v0.1: `rate-limited`, `partial-coverage`, `missing-permission`,
  `unresolved-reference`, `unsupported-item-type`, `redacted-field`. Adding a
  code requires a schema bump plus parallel updates to `diagnostics.py` and
  `entitlements/diagnostics.py` and any scanner emitter mapping.
- CLI process diagnostics (stderr) are distinct from the artifact diagnostic
  enum; the CLI never prints Python tracebacks. Exit codes are meaningful
  (0 success, 2 bad args, 3/4 report errors, 10/20/30 scanner/write/schema
  failures, 1 internal). See README "Exit codes" before changing them.
- v0.x schema is unstable — breaking changes allowed between minor bumps; v1.0
  is the first stable promise (`docs/schemas/versioning.md`).
- Commits must follow Conventional Commits; `type-enum` is restricted to
  `feat, fix, chore, docs, perf, deps, test, ci, refactor` (`.commitlintrc.json`),
  enforced by commitlint on PRs.
- Default branch is `trunk`.
- Releases go through release-please + PyPI Trusted Publishing
  (`.release-please-manifest.json`, `release-please-config.json`,
  `scripts/validate_publish_tag.py`).
- ruff lint selects `["E4", "E7", "E9", "F"]`, line length 88, target py311.
  mypy targets py311 with `ignore_missing_imports = true`.
- The `report` renderer is pure — keep file/network/logging I/O in the CLI/
  command layer, not in `report/`.
- `scan filegdb` reads a local `_inventory.json` descriptor only and never
  touches the network; the `pyogrio` workspace scanner stays library-only.
- Esri IP & licensing guardrails: API reimplementation is fair use under
  *Google v. Oracle* (2021) and is not gated, but proprietary file FORMATS must
  be clean-room (published specs / community readers such as GDAL `OpenFileGDB`;
  never decompile or run licensed Esri software to learn internals),
  Esri-licensed DATA/CONTENT must not be rehosted, proprietary ASSETS
  (symbols/fonts) must not be embedded, software EULA terms must be respected,
  and any published benchmark/comparison is gated on legal counsel sign-off.
  See [`docs/compliance/esri-ip-and-licensing-guardrails.md`](docs/compliance/esri-ip-and-licensing-guardrails.md)
  for the per-ticket checklist and clean-room provenance expectations.
```

## Shared dev-environment rules (multi-agent WSL)

This machine runs many agents concurrently (**Codex + Claude**, often via agentflow with multiple tabs/agents). To prevent host lockups and lost work, every agent MUST follow these:

1. **Heavy builds/tests are throttled by a shared lock.** `dotnet` and `npm` are PATH-shimmed, so their build/test/publish/pack and ci/install/test/run-build/run-test subcommands automatically run under a global semaphore (default 1 concurrent, `HONUA_BUILD_SLOTS`). For other heavy tools, call the wrapper explicitly: `with-build-lock pytest ...`, `with-build-lock cargo build`, `with-build-lock make build`. The lock is shared across ALL of this user's processes (every Codex/Claude tab, agentflow children). Do not bypass it for compiles or test suites. Long-running servers (`dotnet run`, `npm run dev`) are intentionally NOT locked — never wrap those.

2. **Commit and push when you finish a task** so your worktree can be reclaimed. An hourly job (`honua-clean`) removes a worktree ONLY when it is clean AND fully pushed (merged, remote-gone, or idle >=2d). Dirty or unpushed worktrees are NEVER touched — but uncommitted/unpushed work blocks reclamation and is at risk if the instance is reset. Build artifacts (bin/obj and untracked node_modules) are reclaimed automatically and safely.

3. **Commit hygiene — no agent attribution.** Author every commit as the repo owner only (git identity: Mike McDougall <mike@honua.io>). Do **NOT** add any agent/tool attribution to commits: no `Co-Authored-By: Claude ...`, no `Co-Authored-By: Codex ...` (or other bot co-authors), and no "Generated with Claude Code" / "Generated with Codex" / "🤖" lines in the message or PR body. Write a plain, descriptive commit message and stop.
