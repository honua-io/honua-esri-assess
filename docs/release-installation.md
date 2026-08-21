# Install and upgrade `honua-migrate`

Install an exact released version in an isolated application environment:

```bash
pipx install "honua-migrate==<version>"
```

Upgrade an existing pipx installation to the latest released version:

```bash
pipx upgrade honua-migrate
```

Verify the canonical command, the read-only assessment mount, and the legacy
compatibility console command from the pipx application environment:

```bash
honua-migrate --help
honua-migrate assess --help
honua-esri-assess --help
```

Module and import compatibility require an explicit Python environment rather
than pipx's application-only command surface:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install "honua-migrate==<version>"
.venv/bin/python -m honua_migrate assess --help
.venv/bin/python -m honua_esri_assess --help
.venv/bin/python -c "import honua_migrate, honua_esri_assess"
```

On Windows, use `.venv\\Scripts\\python.exe` in place of
`.venv/bin/python`.

Run a local assessment workflow with your own FileGDB inventory descriptor:

```bash
honua-migrate assess scan filegdb \
  --target ./sample.gdb \
  --output EsriFootprint.json \
  --validate
honua-migrate assess report \
  --input EsriFootprint.json \
  --output readiness-report.md
```

The release page contains the wheel, source distribution, and `SHA256SUMS`.
The tag name, distribution metadata version, workflow commit, provenance
attestation, and attached artifacts are validated as one release unit before
PyPI upload.

Do not co-install `honua-sdk` 0.x merely to obtain offline migration commands;
it declares a legacy launcher with the same name. See the
[`honua-sdk` console-script collision policy](console-script-collision.md) for
the isolated module-invocation path needed by live Python execution.
