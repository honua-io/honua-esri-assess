"""Command-line entry point for the bootstrap package."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="honua-esri-assess")
    parser.add_argument("--version", action="store_true", help="Print package version and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    from . import __version__

    args = build_parser().parse_args(argv)
    if args.version:
        print(__version__)
    else:
        build_parser().print_help()
    return 0
