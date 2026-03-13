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

SPDX_COPYRIGHT_LINE = "# " + "SPDX-FileCopyrightText: Copyright (c) provide.io llc"
SPDX_LICENSE_LINE = "# " + "SPDX-License-Identifier" + ": Apache-2.0"
SPDX_HEADER = f"{SPDX_COPYRIGHT_LINE}\n{SPDX_LICENSE_LINE}\n"


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
    return "SPDX-FileCopyrightText:" in head and "SPDX-License-Identifier" in head


def _normalize_python_text(text: str) -> str:
    if _has_spdx_header(text):
        return text

    lines = text.splitlines(keepends=True)
    if lines and lines[0].startswith("#!"):
        shebang = lines[0]
        rest = "".join(lines[1:])
        return f"{shebang}{SPDX_HEADER}\n{rest}"
    return f"{SPDX_HEADER}\n{text}"


def normalize_headers(roots: Iterable[Path]) -> list[Path]:
    changed: list[Path] = []
    for path in sorted(_iter_python_files(roots)):
        original = path.read_text(encoding="utf-8")
        normalized = _normalize_python_text(original)
        if normalized != original:
            path.write_text(normalized, encoding="utf-8")
            changed.append(path)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize SPDX headers on Python files.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["src", "tests", "scripts"],
        help="Directories to scan for Python files.",
    )
    args = parser.parse_args()

    changed = normalize_headers(Path(root) for root in args.roots)
    if changed:
        print(f"normalized SPDX headers in {len(changed)} file(s):")
        for path in changed:
            print(f"  {path}")
    else:
        print("all Python SPDX headers already normalized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
