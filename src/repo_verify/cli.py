# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess  # nosec B404
import sys

VERIFY_STEPS: list[tuple[str, list[str]]] = [
    ("ruff", ["ruff", "check", "."]),
    (
        "max-loc",
        [
            "python",
            "scripts/check_max_loc.py",
            "--max-lines",
            "500",
            "--roots",
            "src",
            "tests",
            "scripts",
            "--baseline",
            ".ci/max-loc-baseline.json",
        ],
    ),
    ("spdx-header-check", ["python", "scripts/check_spdx_headers.py"]),
    ("event-literal-check", ["python", "scripts/check_event_literals.py"]),
    ("mypy", ["mypy", "src/pymutant", "src/repo_verify"]),
    ("bandit", ["bandit", "-q", "-r", "src/pymutant", "src/repo_verify", "-ll"]),
    ("ty", ["ty", "check", "src/pymutant", "src/repo_verify"]),
    (
        "xenon",
        [
            "python",
            "scripts/check_xenon.py",
            "--baseline",
            ".ci/xenon-baseline.json",
            "--max-absolute",
            "C",
            "--max-modules",
            "B",
            "--max-average",
            "A",
            "--paths",
            "src/pymutant",
            "src/repo_verify",
        ],
    ),
    ("vulture", ["vulture", "--min-confidence", "80", "src/pymutant", "src/repo_verify", "tests"]),
    ("check-licenses", ["python", "scripts/check_licenses.py"]),
    (
        "docs-lint",
        [
            "pymarkdown",
            "--config",
            ".pymarkdown.json",
            "scan",
            "README.md",
            "AGENTS.md",
            "docs",
            ".claude/commands",
            ".claude/skills",
        ],
    ),
    ("docs-links", ["python", "scripts/check_markdown_links.py", "--root", "."]),
    ("schemas", ["python", "scripts/validate_repo_schemas.py"]),
    ("pytest", ["pytest", "-q"]),
]


def main() -> None:
    for name, cmd in VERIFY_STEPS:
        print(f"==> running {name}: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, check=False)  # noqa: S603  # nosec B603
        if result.returncode != 0:
            print(f"verification failed during {name}", file=sys.stderr)
            raise SystemExit(result.returncode)

    print("verification passed", flush=True)


if __name__ == "__main__":  # pragma: no cover
    main()
