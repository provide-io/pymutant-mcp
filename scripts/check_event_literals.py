# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import ast
import re
from collections.abc import Iterable
from pathlib import Path

DEFAULT_EXCLUDE_PARTS = {
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "mutants",
    "build",
    "dist",
}
EVENT_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical", "trace"}


def iter_python_files(roots: Iterable[Path], exclude_parts: set[str]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in exclude_parts for part in path.parts):
                continue
            if path.is_file():
                yield path


def first_string_arg(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def is_log_call(node: ast.Call) -> bool:
    return isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS


def find_event_literal_violations(roots: Iterable[Path], exclude_parts: set[str]) -> list[str]:
    violations: list[str] = []
    for path in sorted(iter_python_files(roots, exclude_parts)):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not is_log_call(node):
                continue
            literal = first_string_arg(node)
            if literal is None or EVENT_RE.match(literal):
                continue
            line = getattr(node, "lineno", 1)
            col = getattr(node, "col_offset", 0) + 1
            violations.append(f"{path}:{line}:{col}: invalid event literal: {literal!r}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate log event-name string literals use domain.action.status format."
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["server/src", "src/repo_verify"],
        help="Directories to scan for Python files.",
    )
    parser.add_argument(
        "--exclude-part",
        action="append",
        default=[],
        help="Path component to exclude. Can be provided multiple times.",
    )
    args = parser.parse_args()

    roots = [Path(root) for root in args.roots]
    exclude_parts = set(DEFAULT_EXCLUDE_PARTS)
    exclude_parts.update(args.exclude_part)
    violations = find_event_literal_violations(roots, exclude_parts)
    if not violations:
        print("Event literal check passed: all scanned log event literals match domain.action.status.")
        return 0

    print(f"Event literal check failed: {len(violations)} invalid literal(s).")
    for item in violations:
        print(f"  {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
