"""Run the unified migration CLI with ``python -m honua_migrate``."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":  # pragma: no cover - exercised by subprocess test
    raise SystemExit(main())
