#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
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


def _line_count(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def find_loc_offenders(roots: Iterable[Path], max_lines: int) -> list[tuple[Path, int]]:
    offenders: list[tuple[Path, int]] = []
    for path in sorted(_iter_python_files(roots)):
        lines = _line_count(path)
        if lines > max_lines:
            offenders.append((path, lines))
    return offenders


def _load_baseline(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    allow = data.get("allow_over_limit", {}) if isinstance(data, dict) else {}
    if not isinstance(allow, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in allow.items():
        if isinstance(key, str) and isinstance(value, int):
            out[key] = value
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail if any Python file exceeds a maximum line count.")
    parser.add_argument("--max-lines", type=int, default=500, help="Maximum allowed lines per .py file.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["server/src", "src", "tests", "scripts"],
        help="Directories to scan for Python files.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Optional JSON baseline for known legacy files above max (ratchet mode).",
    )
    args = parser.parse_args()

    roots = [Path(root) for root in args.roots]
    offenders = find_loc_offenders(roots, args.max_lines)
    if args.baseline is None:
        if not offenders:
            print(f"LOC check passed: no Python file exceeds {args.max_lines} lines.")
            return 0

        print(f"LOC check failed: {len(offenders)} file(s) exceed {args.max_lines} lines.")
        for path, lines in offenders:
            print(f"  {path}: {lines}")
        return 1

    baseline = _load_baseline(args.baseline)
    new_offenders: list[tuple[Path, int]] = []
    for path, lines in offenders:
        key = str(path)
        allowed = baseline.get(key)
        if allowed is None or lines > allowed:
            new_offenders.append((path, lines))

    if not new_offenders:
        print(f"LOC check passed: no Python file exceeds {args.max_lines} lines.")
        return 0

    print(f"LOC check failed: {len(new_offenders)} file(s) exceed {args.max_lines} lines.")
    for path, lines in new_offenders:
        print(f"  {path}: {lines}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
