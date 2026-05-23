# Release Process

`honua-esri-assess` publishes source distributions and pure-Python wheels to
PyPI. Releases are driven by release-please so version bumps, changelog entries,
GitHub tags, and PyPI uploads are reviewable.

## Versioning

The tool version in `pyproject.toml` follows SemVer and is managed by
release-please. The schema version is independent and is carried in
`EsriFootprint.json.schemaVersion`; this epic ships schema `v0.1`.

Release tags include the package component:

```text
honua-esri-assess-v<semver>
```

The publish workflow validates that the tag suffix matches `pyproject.toml`.
A tool patch release can still carry the same schema version when the handoff
contract has not changed.

## Conventional Commits

Pull requests must use conventional commit prefixes so release-please can derive
the next version and changelog:

- `feat:` for user-facing additions.
- `fix:` for bug fixes.
- `docs:` for documentation-only changes.
- `perf:` for performance work.
- `deps:` for dependency updates.
- `chore:`, `test:`, `ci:`, and `refactor:` for non-feature maintenance.

The CI workflow enforces these prefixes with commitlint on pull requests.

## Cutting a Release

1. Merge conventional commits to `trunk`.
2. Let `.github/workflows/release-please.yml` open or update the release PR.
3. Review the generated version bump and `CHANGELOG.md`.
4. Merge the release PR.
5. release-please creates the `honua-esri-assess-v<semver>` tag and GitHub
   release.
6. `.github/workflows/publish.yml` builds the sdist and wheel, smoke-installs
   the wheel, uploads artifacts for 14 days, and publishes to PyPI.

## Release gates

Every release crosses two stacked gate sets before the wheel reaches PyPI.

`.github/workflows/ci.yml` runs on every pull request and on pushes to
`trunk`:

- **Unit tests** on Python 3.11, 3.12, and 3.13 (matrix).
- **Lint** via `ruff check`.
- **Type check** via `mypy`.
- **Dependency license check** via `scripts/check_dep_licenses.py`, which
  rejects non-Apache-2.0-compatible runtime dependencies.
- **Fixture-backed smoke tests** under `tests/smoke/` as a separate job so a
  smoke failure is distinguishable from a unit-test failure.
- **commitlint** on pull request titles/commits so release-please can derive
  the next version.

`.github/workflows/publish.yml` adds publish-time gates after the release tag
is pushed (and on manual `dry_run` dispatches):

- **Pre-publish type check** on the 3.11/3.12/3.13 matrix.
- **Tag validation** via `scripts/validate_publish_tag.py`, which fails the
  build if the `honua-esri-assess-v<semver>` tag suffix does not match
  `pyproject.toml`.
- **Reproducible build** with `SOURCE_DATE_EPOCH` derived from the release
  commit and `hatch build` (pure-Python `py3-none-any` wheel).
- **Wheel smoke install** in a clean virtualenv: the wheel is installed,
  `pytest tests/smoke` runs against the installed package, the installed
  console script runs a FileGDB scan, and `jq` asserts the output footprint
  declares `schemaVersion == "v0.1"`.
- **PyPI publish** via OIDC Trusted Publishing only after every previous gate
  passes, and only when the run is not a `dry_run` dispatch.

## Dry Runs

Run the `Publish` workflow manually with `dry_run=true` to build and
smoke-install artifacts without publishing to PyPI. The dry run intentionally
does not require a release tag. A non-dry-run publish still requires a
validated `honua-esri-assess-v<semver>` release tag.

## Release Gates

CI runs unit tests on Python 3.11, 3.12, and 3.13; `ruff check`; `mypy`; the
runtime dependency license checker; commitlint on pull requests; and the
fixture-backed smoke suite. The license checker rejects installed runtime
dependencies whose advertised metadata is incompatible with the Apache-2.0
distribution constraint.

The publish workflow repeats the pre-publish typecheck, validates release tags,
builds the sdist and pure-Python wheel, smoke-installs the wheel, runs the
fixture-backed smoke tests from the installed artifact, and verifies that the
installed CLI emits `schemaVersion: "v0.1"` for a FileGDB smoke scan before any
PyPI publish step runs. Manual dispatches from untagged refs can only complete
the build and smoke-install path.

## Trusted Publishing

PyPI publishing uses OpenID Connect through
`pypa/gh-action-pypi-publish@release/v1`; no long-lived PyPI token is stored in
the repository or GitHub secrets.

Before the first real publish, configure the PyPI project
`honua-esri-assess` with a trusted publisher for:

- owner/repository: `honua-io/honua-esri-assess`
- workflow: `publish.yml`
- environment: none

## Reproducible Builds

The publish workflow sets `SOURCE_DATE_EPOCH` from the release commit timestamp
before running `hatch build`. Hatch reproducible builds are enabled in
`pyproject.toml`, and the produced wheel is pure Python (`py3-none-any`).
