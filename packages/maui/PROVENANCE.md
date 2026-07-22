# MAUI codemod provenance

This package was ported as a self-contained source migration from
[`honua-io/honua-mobile`](https://github.com/honua-io/honua-mobile), commit
`2b30ae86f87fa73e80adc55c3ff3b4dd3e271ad1` (`origin/trunk`, 2026-06-29).

The imported paths were:

- `tools/Honua.Migrate.Maui`
- `tools/Honua.Migrate.Maui.Cli`
- `tests/Honua.Migrate.Maui.Tests`

The source is Apache-2.0. This port preserves its Roslyn-only dependency
boundary: it does not reference MAUI workloads, Honua SDK packages, or private
Honua package feeds.
