"""Markdown formatting helpers for deterministic report output."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


def text(value: Any, *, empty: str = "-") -> str:
    if value is None:
        return empty
    rendered = str(value).strip()
    return rendered if rendered else empty


def count(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def md_cell(value: Any) -> str:
    rendered = text(value)
    return rendered.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def markdown_table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    rendered_rows = [tuple(md_cell(cell) for cell in row) for row in rows]
    header_line = "| " + " | ".join(md_cell(header) for header in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rendered_rows]
    return "\n".join([header_line, separator, *body])


def plural(value: int, singular: str, plural_label: str | None = None) -> str:
    label = singular if value == 1 else plural_label or f"{singular}s"
    return f"{value} {label}"


def bullet_list(values: Iterable[str]) -> str:
    return "\n".join(f"- {value}" for value in values)
