#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
from pathlib import Path


def _load_baseline(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("allow_violations", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        return set()
    out: set[str] = set()
    for item in items:
        if isinstance(item, str):
            out.add(item)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Run xenon strict gate with baseline ratchet support.")
    parser.add_argument("--baseline", type=Path, default=Path(".ci/xenon-baseline.json"))
    parser.add_argument(
        "--paths",
        nargs="+",
        default=["src/pymutant", "src/repo_verify"],
        help="Paths to check.",
    )
    parser.add_argument("--max-absolute", default="C")
    parser.add_argument("--max-modules", default="B")
    parser.add_argument("--max-average", default="A")
    args = parser.parse_args()

    cmd = [
        "xenon",
        "--max-absolute",
        args.max_absolute,
        "--max-modules",
        args.max_modules,
        "--max-average",
        args.max_average,
        *args.paths,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # nosec B603
    stderr = proc.stderr.strip()
    if proc.returncode == 0:
        print("xenon check passed: no violations.")
        return 0

    baseline = _load_baseline(args.baseline)
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    violations = [line.removeprefix("ERROR:xenon:") for line in lines if line.startswith("ERROR:xenon:")]
    new_violations = [line for line in violations if line not in baseline]
    if new_violations:
        print("xenon check failed: new complexity violations detected.")
        for line in new_violations:
            print(f"  {line}")
        return 1

    print("xenon check passed (baseline only): no new complexity violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
