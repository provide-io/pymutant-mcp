# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pymutant import setup


def test_project_root_or_cwd_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert setup._project_root_or_cwd(None) == tmp_path


def test_read_pyproject_missing(tmp_path: Path) -> None:
    assert setup._read_pyproject(tmp_path) == {}


def test_read_pyproject_invalid(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[")
    assert setup._read_pyproject(tmp_path) == {}


def test_read_pyproject_valid(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.mutmut]\npaths_to_mutate=['src/']\n")
    data = setup._read_pyproject(tmp_path)
    assert "tool" in data


def test_mutmut_version_from_venv(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / ".venv" / "bin" / "mutmut"
    exe.parent.mkdir(parents=True)
    exe.write_text("x")

    class Dummy:
        stdout = "mutmut 3.5"
        stderr = ""

    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: Dummy())
    assert setup._mutmut_version(tmp_path) == "mutmut 3.5"


def test_mutmut_version_from_path(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "mutmut"
    exe.write_text("x")
    monkeypatch.setattr(setup.shutil, "which", lambda _name: str(exe))

    class Dummy:
        stdout = ""
        stderr = "v"

    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: Dummy())
    assert setup._mutmut_version(tmp_path) == "v"


def test_mutmut_version_handles_errors(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "mutmut"
    exe.write_text("x")
    monkeypatch.setattr(setup.shutil, "which", lambda _name: str(exe))

    def _raise(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["mutmut"], timeout=1)

    monkeypatch.setattr(setup.subprocess, "run", _raise)
    assert setup._mutmut_version(tmp_path) is None


def test_find_test_dirs(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "test").mkdir()
    assert setup._find_test_dirs(tmp_path) == ["tests/", "test/"]


@pytest.mark.parametrize(
    ("value", "expected_list", "expected_note_fragment"),
    [
        (["a"], ["a"], None),
        ("a", ["a"], "legacy string"),
        (5, None, "int"),
    ],
)
def test_normalize_to_list(value: object, expected_list: list[str] | None, expected_note_fragment: str | None) -> None:
    converted, note = setup._normalize_to_list(value)
    assert converted == expected_list
    if expected_note_fragment is None:
        assert note is None
    else:
        assert expected_note_fragment in (note or "")


def test_detect_monorepo_src_paths(tmp_path: Path) -> None:
    (tmp_path / "packages" / "foo" / "src").mkdir(parents=True)
    assert setup._detect_monorepo_src_paths(tmp_path) == ["packages/foo/src/"]


def test_detect_layout_monorepo(tmp_path: Path) -> None:
    (tmp_path / "packages" / "foo" / "src").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    out = setup.detect_layout(tmp_path)
    assert out["layout"] == "monorepo"
    assert out["suggested_config"]["paths_to_mutate"] == ["packages/foo/src/"]
    assert out["notes"]


def test_detect_layout_flat_src_and_also_copy(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "conftest.py").write_text("x")
    out = setup.detect_layout(tmp_path)
    assert out["layout"] == "flat_src"
    assert out["suggested_config"]["also_copy"] == ["scripts/", "conftest.py"]


def test_detect_layout_flat(tmp_path: Path) -> None:
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    out = setup.detect_layout(tmp_path)
    assert out["layout"] == "flat"
    assert out["suggested_config"]["paths_to_mutate"] == ["mypkg/"]


def test_check_setup_without_config(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.0'\n")
    monkeypatch.setattr(setup, "_mutmut_version", lambda _root: "mutmut 3.5")

    out = setup.check_setup(tmp_path)
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["mutmut_config_exists"]["ok"] is False
    assert checks["conftest_mutant_guard"]["ok"] is True


def test_check_setup_with_legacy_string_and_missing_paths(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.mutmut]
paths_to_mutate = "src/"
tests_dir = "tests/"
""".strip()
    )
    monkeypatch.setattr(setup, "_mutmut_version", lambda _root: "mutmut 3.5")
    out = setup.check_setup(tmp_path)

    checks = {c["name"]: c for c in out["checks"]}
    assert checks["paths_to_mutate_valid_type"]["ok"] is True
    assert "legacy string" in checks["paths_to_mutate_valid_type"]["detail"]
    assert checks["paths_to_mutate_exist"]["ok"] is False


def test_check_setup_detects_monorepo_guard_requirement(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "packages" / "foo" / "src").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.mutmut]
paths_to_mutate = ["packages/foo/src/"]
tests_dir = ["tests/"]
""".strip()
    )
    monkeypatch.setattr(setup, "_mutmut_version", lambda _root: "mutmut 3.5")

    out = setup.check_setup(tmp_path)
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["no_monorepo_key_mismatch"]["ok"] is False
    assert checks["conftest_mutant_guard"]["ok"] is False


def test_check_setup_invalid_field_types(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.mutmut]
paths_to_mutate = 123
tests_dir = 456
""".strip()
    )
    monkeypatch.setattr(setup, "_mutmut_version", lambda _root: "mutmut 3.5")
    out = setup.check_setup(tmp_path)
    checks = {c["name"]: c for c in out["checks"]}
    assert checks["paths_to_mutate_valid_type"]["ok"] is False
    assert checks["tests_dir_valid_type"]["ok"] is False
