# Python release process

The `honua-migrate` Python distribution publishes a source distribution and a
pure-Python wheel. Release Please owns version changes, changelog entries, and
the component tag family:

```text
honua-migrate-v<semver>
```

The `honua-esri-assess` command and `honua_esri_assess` import package remain
inside the same distribution as compatibility surfaces. They are not a second
PyPI project or release component.

## Release sequence

1. Merge conventional commits to `trunk`.
2. Let `.github/workflows/release-please.yml` open or refresh the release PR.
3. Review the generated `pyproject.toml`, both Python `__version__` fallbacks,
   `.release-please-manifest.json`, and `CHANGELOG.md` changes.
4. Merge the release PR. Release Please creates the matching
   `honua-migrate-v<semver>` tag and GitHub release, then dispatches
   `.github/workflows/publish.yml` at that exact tag and commit. This explicit
   dispatch is required because events created by the default GitHub Actions
   token do not recursively trigger tag workflows.
5. The publish workflow validates the tag/commit identity, repeats
   the release gates, builds and validates deterministic artifacts, runs
   isolated wheel and sdist smoke installs, attaches the artifacts,
   `SHA256SUMS`, and version-specific install notes to that GitHub release,
   creates build-provenance attestations, and then uploads to PyPI through
   Trusted Publishing.

Manual `workflow_dispatch` runs with blank release inputs are build-only. A
publish-capable dispatch must be launched at an existing `honua-migrate-v*`
tag and supply that exact tag and commit; mismatches fail before building.
Release Please supplies those values without a PAT or long-lived secret. A
direct protected-tag push remains supported. Either path requires approval
through the `pypi-honua-migrate` GitHub environment.

## Fail-closed release gates

Before the environment-protected upload job can start, the workflow requires:

- unit tests, Ruff, and mypy on Python 3.11, 3.12, and 3.13;
- runtime dependency audit and Apache-2.0-compatible dependency license check;
- read-only assessment transport, credential-redaction, and no-telemetry
  invariants;
- an exact tag prefix and version match across `pyproject.toml`, the canonical
  and compatibility `__version__` fallbacks, `GITHUB_REF`, `GITHUB_SHA`, the
  checked-out commit, and the repository tag;
- two clean builds with a commit-derived `SOURCE_DATE_EPOCH`, followed by a
  byte-for-byte wheel and sdist hash comparison;
- wheel `RECORD` verification plus distribution name/version, repository URL,
  Python version, license expression, console entry point, required content,
  unsafe path, private-key, and assessment no-telemetry validation;
- isolated wheel and sdist installs with `pip check`, both console commands,
  both module invocations, the complete fixture-backed smoke suite, and an
  installed `scan -> EsriFootprint.json -> report` workflow; and
- a matching GitHub release that accepts the wheel, sdist, checksum manifest,
  and rendered install/upgrade notes before the PyPI action is invoked.

Third-party actions in the publish and Release Please workflows are pinned to
full commit SHAs. Release Please receives `actions: write` only so its default
short-lived GitHub token can dispatch the exact release ref without a PAT.
The PyPI job receives only `contents: write` for its release
asset attachment, `attestations: write` for provenance, and `id-token: write`
for short-lived OIDC credentials. No PyPI username, password, API token, or
long-lived publishing secret is used. Duplicate filenames or versions fail;
the workflow does not use `skip-existing` or overwrite release assets.

## One-time owner configuration

These repository and registry actions are intentionally not performed by a
code change:

1. Create the GitHub environment named exactly `pypi-honua-migrate`. Add
   trusted required reviewers and restrict deployment to the protected
   `honua-migrate-v*` release-tag family. Do not add a PyPI secret.
2. On PyPI, register a pending Trusted Publisher for project
   `honua-migrate` with:

   - owner: `honua-io`
   - repository: `honua-migrate`
   - workflow: `publish.yml`
   - environment: `pypi-honua-migrate`

   A pending publisher does not reserve the project name until the first
   successful upload, so complete this immediately before the approved first
   release.
3. Add a repository tag ruleset for `honua-migrate-v*` that blocks tag update
   and deletion after creation. Permit the Release Please identity to create
   tags, but do not give it an update/delete bypass. This makes the validated
   source tag immutable while still allowing the publish workflow to attach
   artifacts to the already-created GitHub release.
4. Require the Python release CI and security checks on the release PR and
   review the `pypi-honua-migrate` deployment before approval.

After the first publish, verify that
`https://pypi.org/pypi/honua-migrate/json` reports the expected version,
repository URLs, Apache-2.0 license expression, and both console scripts.
Install the exact version with `pipx` using the notes attached to the matching
GitHub release and verify its file hashes against `SHA256SUMS`.

## Console-script collision with `honua-sdk`

Published `honua-sdk` 0.x releases also own a legacy `honua-migrate` launcher.
This distribution does not auto-install that SDK because pip cannot safely
arbitrate two owners for one console-script path. Offline Python migration
commands need no SDK. Until a released SDK removes its entry point, live
execution that imports `honua_sdk` must use a dedicated environment and the
collision-free `python -m honua_migrate` invocation documented in
[`docs/console-script-collision.md`](docs/console-script-collision.md).

## Versioning

The distribution version follows SemVer and is managed by Release Please. The
assessment artifact schema version remains independent and is carried in each
artifact's `schemaVersion`; a tool patch release can retain the same schema
version when the handoff contract is unchanged.

Pull requests use the repository's Conventional Commit types (`feat`, `fix`,
`docs`, `perf`, `deps`, `chore`, `test`, `ci`, and `refactor`) so Release
Please can derive the next version and changelog.
