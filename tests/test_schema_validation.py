# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run(data: Path, schema: Path) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            "scripts/validate_json_schema.py",
            "--data",
            str(data),
            "--schema",
            str(schema),
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(root),
    )


def test_validate_profiles_schema(tmp_path: Path) -> None:
    if os.environ.get("MUTANT_UNDER_TEST"):
        pytest.skip("schema script integration test requires repository scripts path")
    data = tmp_path / "profiles.json"
    data.write_text(json.dumps({"schema_version": "1.0", "profiles": {"default": {}}}))
    result = _run(data, Path("schemas/profiles.schema.json"))
    assert result.returncode == 0
    assert "schema validation passed" in result.stdout


def test_validate_schema_failure(tmp_path: Path) -> None:
    if os.environ.get("MUTANT_UNDER_TEST"):
        pytest.skip("schema script integration test requires repository scripts path")
    data = tmp_path / "bad.json"
    data.write_text(json.dumps({"profiles": {}}))
    result = _run(data, Path("schemas/profiles.schema.json"))
    assert result.returncode != 0


def test_validate_repo_schemas_script() -> None:
    if os.environ.get("MUTANT_UNDER_TEST"):
        pytest.skip("schema script integration test requires repository scripts path")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/validate_repo_schemas.py"],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0
    assert "repository schema validation passed" in result.stdout
