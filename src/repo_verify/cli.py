# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess  # nosec B404
import sys


VERIFY_STEPS: list[tuple[str, list[str]]] = [
    ("ruff", ["ruff", "check", "."]),
    ("mypy", ["mypy", "server/src", "src/repo_verify"]),
    ("bandit", ["bandit", "-q", "-r", "server/src/pymutant", "src/repo_verify", "-ll"]),
    (
        "docs-lint",
        [
            "pymarkdown",
            "--config",
            ".pymarkdown.json",
            "scan",
            "README.md",
            "AGENTS.md",
            "commands",
            "skills",
            "server/README.md",
            "docs",
        ],
    ),
    ("docs-links", ["python", "scripts/check_markdown_links.py", "--root", "."]),
    ("schemas", ["python", "scripts/validate_repo_schemas.py"]),
    ("pytest", ["pytest", "-q"]),
]


def main() -> None:
    for name, cmd in VERIFY_STEPS:
        print(f"==> running {name}: {' '.join(cmd)}", flush=True)
        result = subprocess.run(cmd, check=False)  # nosec B603
        if result.returncode != 0:
            print(f"verification failed during {name}", file=sys.stderr)
            raise SystemExit(result.returncode)

    print("verification passed", flush=True)


if __name__ == "__main__":  # pragma: no cover
    main()
