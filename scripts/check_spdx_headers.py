#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

EXCLUDED_PARTS = {
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "mutants",
    "build",
    "dist",
}


def _iter_python_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            if path.is_file():
                yield path


def _has_spdx_header(text: str) -> bool:
    head = "\n".join(text.splitlines()[:5])
    return "SPDX-FileCopyrightText:" in head and "SPDX-License-Identifier:" in head


def find_noncompliant_files(roots: Iterable[Path]) -> list[Path]:
    bad: list[Path] = []
    for path in sorted(_iter_python_files(roots)):
        text = path.read_text(encoding="utf-8")
        if not _has_spdx_header(text):
            bad.append(path)
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description="Check SPDX headers on Python files.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["src", "tests", "scripts"],
        help="Directories to scan for Python files.",
    )
    args = parser.parse_args()

    offenders = find_noncompliant_files(Path(root) for root in args.roots)
    if not offenders:
        print("SPDX header check passed: all Python files are compliant.")
        return 0
    print(f"SPDX header check failed: {len(offenders)} file(s) are noncompliant.")
    for path in offenders:
        print(f"  {path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
