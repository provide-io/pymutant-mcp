#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_SCHEMES = {"mailto", "tel", "data", "app"}
SKIP_DIRS = {".git", ".venv", "dist", "mutants", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def _iter_markdown_files(root: Path) -> list[Path]:
    markdown_files: list[Path] = []
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS for part in relative_parts):
            continue
        markdown_files.append(path)
    return sorted(markdown_files)


def _normalize_target(raw: str) -> str:
    target = raw.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return target


def _split_anchor(target: str) -> tuple[str, str | None]:
    if "#" not in target:
        return target, None
    base, anchor = target.split("#", 1)
    return base, anchor


def _check_local_link(source_file: Path, target: str, root: Path) -> str | None:
    base_target, _anchor = _split_anchor(target)
    if base_target == "":
        return None

    if base_target.startswith("/"):
        candidate = (root / base_target.lstrip("/")).resolve()
    else:
        candidate = (source_file.parent / base_target).resolve()

    root_resolved = root.resolve()
    if not str(candidate).startswith(str(root_resolved)):
        return f"escapes repo root: {target}"

    if not candidate.exists():
        return f"missing target: {target}"
    return None


def _http_ok(url: str, timeout: float, retries: int) -> bool:
    request = urllib.request.Request(url, method="HEAD")
    for _ in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
                return 200 <= response.status < 400
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                return True
            if error.code == 405:
                get_request = urllib.request.Request(url, method="GET")
                try:
                    with urllib.request.urlopen(get_request, timeout=timeout) as response:  # nosec B310
                        return 200 <= response.status < 400
                except Exception:
                    continue
            continue
        except Exception:
            continue
    return False


def check_markdown_links(root: Path, *, check_remote: bool, timeout: float, retries: int) -> list[str]:
    errors: list[str] = []
    for markdown_file in _iter_markdown_files(root):
        text = markdown_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in LINK_RE.finditer(line):
                raw_target = match.group(1)
                target = _normalize_target(raw_target)
                if target.startswith("#"):
                    continue

                parsed = urllib.parse.urlparse(target)
                scheme = parsed.scheme.lower()
                if scheme in SKIP_SCHEMES:
                    continue

                if scheme in {"http", "https"}:
                    if check_remote and not _http_ok(target, timeout=timeout, retries=retries):
                        errors.append(f"{markdown_file}:{line_no}: unreachable URL: {target}")
                    continue

                error = _check_local_link(markdown_file, target, root)
                if error:
                    errors.append(f"{markdown_file}:{line_no}: {error}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Markdown links")
    parser.add_argument("--root", default=".")
    parser.add_argument("--check-remote", action="store_true")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    errors = check_markdown_links(
        root,
        check_remote=args.check_remote,
        timeout=args.timeout,
        retries=max(0, args.retries),
    )
    if errors:
        print("Markdown link check failed:", file=sys.stderr)
        for item in errors:
            print(item, file=sys.stderr)
        raise SystemExit(1)

    print("Markdown link check passed")


if __name__ == "__main__":
    main()
