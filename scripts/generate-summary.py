#!/usr/bin/env python3
"""Generate GitBook's SUMMARY.md from the OKF bundle.

GitBook needs a table of contents. The OKF bundle already knows exactly which
pages are published documentation and what each one is called - `okf-bundle.v1.json`
declares the boundary and every page inside it carries `title` in its frontmatter.
Deriving one from the other means the human table of contents and the agent-
traversable bundle cannot disagree: a page added to the bundle appears in the TOC,
and a page excluded from the bundle cannot be listed.

That is the same "derive the mechanical join, hand-maintain only the judgement"
rule ADR-0058 sets for the capability artifacts. The judgement here is the
boundary and the titles; the ordering and the markdown are mechanical.

Run with --check in CI to fail when SUMMARY.md drifts from the bundle.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "docs" / "okf-bundle.v1.json"
SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")

# Sections are ordered for a reader arriving cold, not alphabetically: what this
# is, then the fastest proof it works, then the things you reach for once it
# does, then lookup material. A page whose directory matches nothing lands in
# "Guides", which is the honest default for prose.
SECTION_ORDER = [
    ("Start here", lambda rel, kind: rel in {"index.md", "README.md"} or kind == "index"),
    ("Quickstart", lambda rel, kind: "quickstart" in rel),
    ("Guides", lambda rel, kind: kind == "guide"),
    ("Concepts", lambda rel, kind: kind == "concept"),
    ("Reference", lambda rel, kind: kind == "reference"),
]


def read_frontmatter(path: pathlib.Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[3:end].splitlines():
        match = SCALAR_RE.match(line.strip())
        if match:
            fields[match.group(1)] = match.group(2).strip().strip('"')
    return fields


def collect(manifest: dict) -> list[tuple[str, str, str]]:
    root = REPO_ROOT / manifest["root"]
    excluded_dirs = {(REPO_ROOT / e["path"]).resolve() for e in manifest["excludedDirs"]}
    excluded_files = {(REPO_ROOT / e["path"]).resolve() for e in manifest["excludedFiles"]}

    pages: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*.md")):
        resolved = path.resolve()
        if resolved in excluded_files:
            continue
        if any(parent in excluded_dirs for parent in resolved.parents):
            continue
        fields = read_frontmatter(path)
        if not fields.get("type"):
            continue
        rel = path.relative_to(root).as_posix()
        title = fields.get("title") or rel
        pages.append((rel, title, fields["type"]))
    return pages


def render(pages: list[tuple[str, str, str]]) -> str:
    lines = ["# Table of contents", ""]
    placed: set[str] = set()
    for section, matches in SECTION_ORDER:
        entries = [p for p in pages if p[0] not in placed and matches(p[0], p[2])]
        if not entries:
            continue
        # The landing page and the docs map lead their section; a reader
        # arriving cold should not have to scan an alphabetical list to find
        # the front door. Everything else keeps path order.
        # Front doors lead their section, ordered by how specific a door they
        # are: the product landing page, then the docs map, then the feature
        # map, then everything else in path order. A repo with no index.md
        # (honua-sdk-js) therefore leads with its feature map rather than an
        # alphabetically-first example; a repo with one (honua-sdk-python)
        # leads with it. quickstart.md leads its own section so it precedes
        # its troubleshooting companion.
        lead = {'index.md': 0, 'README.md': 1, 'features/README.md': 2,
                'quickstart.md': 0}
        entries.sort(key=lambda e: (lead.get(e[0], 3), e[0]))
        for rel, _, _ in entries:
            placed.add(rel)
        lines.append(f"## {section}")
        lines.append("")
        for rel, title, _ in entries:
            lines.append(f"* [{title}]({rel})")
        lines.append("")
    leftover = [p for p in pages if p[0] not in placed]
    if leftover:
        lines.append("## Other")
        lines.append("")
        for rel, title, _ in leftover:
            lines.append(f"* [{title}]({rel})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if SUMMARY.md is stale")
    args = parser.parse_args(argv)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pages = collect(manifest)
    rendered = render(pages)
    summary = REPO_ROOT / manifest["root"] / "SUMMARY.md"

    if args.check:
        current = summary.read_text(encoding="utf-8") if summary.is_file() else ""
        if current != rendered:
            print(
                f"::error::{summary.relative_to(REPO_ROOT).as_posix()} is stale. "
                "Run 'python3 scripts/generate-summary.py' and commit the result.",
                file=sys.stderr,
            )
            return 1
        print(f"SUMMARY.md is current: {len(pages)} page(s).")
        return 0

    summary.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Wrote {summary.relative_to(REPO_ROOT).as_posix()} ({len(pages)} pages).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
