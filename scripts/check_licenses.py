# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

ALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        "MIT",
        "MIT License",
        "MIT OR Apache-2.0",
        "Apache-2.0",
        "Apache Software License",
        "Apache Software License; MIT License",
        "Apache-2.0 OR BSD-2-Clause",
        "Apache-2.0 OR BSD-3-Clause",
        "BSD",
        "BSD License",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "3-Clause BSD License",
        "ISC",
        "ISC License",
        "ISC License (ISCL)",
        "PSF-2.0",
        "Python Software Foundation License",
        "MPL-2.0",
        "Mozilla Public License 2.0 (MPL 2.0)",
        "CC0 1.0 Universal (CC0 1.0) Public Domain Dedication",
        "Public Domain",
    }
)

DEV_ONLY_SKIP: frozenset[str] = frozenset(
    {
        "codespell",
        "python-debian",
        "reuse",
        "docutils",
    }
)


def _get_installed_licenses() -> list[dict[str, str]]:
    pip_licenses = Path(sys.executable).parent / "pip-licenses"
    result = subprocess.run(
        [str(pip_licenses), "--format=json"],  # nosec B603
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(1)
    payload: Any = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise SystemExit("pip-licenses returned non-list JSON")
    rows: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("Name")
        version = item.get("Version")
        license_name = item.get("License")
        if all(isinstance(v, str) for v in (name, version, license_name)):
            rows.append({"Name": name, "Version": version, "License": license_name})
    return rows


def main() -> int:
    packages = _get_installed_licenses()
    violations: list[str] = []
    skipped: list[str] = []

    for pkg in packages:
        name = pkg["Name"]
        license_name = pkg["License"]
        if name in DEV_ONLY_SKIP:
            skipped.append(name)
            continue
        if license_name not in ALLOWED_LICENSES:
            violations.append(f"  {name} {pkg['Version']}: {license_name!r}")

    if violations:
        print("Disallowed licenses found:")
        for violation in violations:
            print(violation)
        print("\nIf this is a dev-only tool, add it to DEV_ONLY_SKIP in scripts/check_licenses.py.")
        return 1

    checked = len(packages) - len(skipped)
    print(f"License check passed: {checked} packages checked, {len(skipped)} dev-only skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
