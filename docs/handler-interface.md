# Scanner Handler Interface

E9 owns the CLI dispatch slots. Scanner tickets register backend handlers
without changing the top-level command tree.

Handlers live under `honua_esri_assess.commands.scan_handlers` and register a
`ScanHandler`:

```python
from honua_esri_assess.commands.common import ScanOptions, ScanResult
from honua_esri_assess.commands.scan_handlers import ScanHandler, register


def run(options: ScanOptions) -> ScanResult:
    ...


register(ScanHandler(name="agol", run=run))
```

Supported names are `agol`, `server`, and `filegdb`.

## `ScanOptions`

The CLI builds a frozen `ScanOptions` block before dispatching. Handlers must
treat every field as read-only.

| Field | Type | Notes |
| --- | --- | --- |
| `target` | `str` | URL, portal locator, or local FileGDB path supplied to `--target`. |
| `output` | `Path` | Destination passed to `--output`; defaults to `./EsriFootprint.json`. The CLI owns persistence. |
| `token_env` | `str \| None` | Environment variable name from `--token-env`. Logged by name only. |
| `token` | `str \| None` | Resolved token value read from `token_env`. Never log this. |
| `log_format` | `str` | `"text"` or `"json"`. Logging is configured by the CLI before the handler runs. |
| `log_level` | `str` | Standard log level name. |
| `no_network_telemetry_confirm` | `bool` | Audit acknowledgement; not a telemetry opt-in. |
| `user_agent` | `str` | User-Agent header to use on Esri GET requests. |
| `max_retries` | `int` | Maximum retries for read-only network calls. |
| `timeout` | `float` | HTTP timeout in seconds. |
| `validate` | `bool` | Whether `--validate` was set; the CLI handles validation. |

`--token-env` is the only credential entry point. The CLI resolves the named
environment variable into `ScanOptions.token` and never exposes a plaintext
`--token` flag. Handlers must not log token values. The
`no_network_telemetry_confirm` option is only an acknowledgement that the
invocation did not enable network telemetry; it does not grant permission for a
handler to send telemetry.

The built-in AGOL and ArcGIS Server handlers pass `token`, `user_agent`,
`timeout`, and `max_retries` into their read-only HTTP probes. Token values are
sent only as Esri request parameters and are not copied into
`EsriFootprint.json`; FileGDB is local-only and ignores network-only options.

## `ScanResult`

Handlers return a `ScanResult`:

```python
ScanResult(footprint={"schemaVersion": "v0.1", ...}, diagnostics=(...,))
```

- `footprint` — a dictionary that conforms to `EsriFootprint.json` v0.1.
- `diagnostics` — an immutable tuple of `Diagnostic` records the CLI mirrors
  to stderr as typed, prospect-safe lines after the artifact is written.
  Diagnostics in this tuple are in addition to those the handler may have
  already embedded into `footprint["diagnostics"]`; both surfaces are
  expected to stay in sync.

The CLI owns:

- **Schema validation.** When `options.validate` is `True`, the CLI validates
  the returned footprint against the bundled schema before writing it and
  raises `SchemaValidationError` (exit `30`) on failure. Handlers do not need
  to call `validate_footprint` themselves.
- **Persistence.** The CLI writes the footprint to `options.output`,
  sort-keyed and indented. Handlers should not write files; doing so risks
  emitting a second artifact, which violates the
  `EsriFootprint.json`-only handoff contract.
- **Diagnostic mirroring.** Each entry in `result.diagnostics` is rendered
  on stderr with `print_diagnostic`. Handlers must produce
  `Diagnostic` instances with codes from the locked v0.1 enum
  (`rate-limited`, `partial-coverage`, `missing-permission`,
  `unresolved-reference`, `unsupported-item-type`, `redacted-field`).

## Failure surface

Expected scanner failures must raise a `DiagnosticError` subclass so the CLI
can return a typed prospect-safe stderr line with a stable exit code:

| Failure kind | Class | Exit |
| --- | --- | --- |
| Scanner could not produce an inventory | `DiagnosticError(code="scanner-error")` | `10` |
| CLI could not save the requested artifact | `OutputWriteError` (raised by the CLI on `OSError`) | `20` |
| Schema validation failed when requested | `SchemaValidationError` | `30` |
| Unexpected internal failure | unhandled exception → `internal-error` | `1` |

These CLI process-diagnostic codes are deliberately separate from the locked
`diagnostics[].code` enum inside `EsriFootprint.json`.

Raw tracebacks must never be printed in default mode. Token values, raw
URLs with credentials, and on-prem paths must not appear in diagnostic
messages or log lines. The `redact` helper in `honua_esri_assess.diagnostics`
strips common secret patterns from strings before they reach a crash dump.

## Telemetry and read-only stance

- Handlers must remain read-only against the customer's Esri system. No
  write or admin APIs should be reachable from a handler entry point.
- No network telemetry. Handlers must not POST to Honua-operated services
  or any third-party telemetry sink. Local stderr logs (text or JSON) are
  the only allowed reporting channel.
- Crash dumps are off by default and only enabled when
  `HONUA_ESRI_ASSESS_CRASH_DUMPS=1` is set; the CLI writes them locally
  under `~/.cache/honua-esri-assess/crashes/` with redaction applied.
