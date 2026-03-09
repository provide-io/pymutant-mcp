# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from pymutant import init


def test_project_root_or_cwd_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert init._project_root_or_cwd(None) == tmp_path


def test_has_mutmut_section() -> None:
    assert init._has_mutmut_section("[tool.mutmut]") is True
    assert init._has_mutmut_section("[tool.other]") is False


def test_fmt_toml_list() -> None:
    assert init._fmt_toml_list([]) == "[]"
    assert init._fmt_toml_list(["a", "b"]) == '["a", "b"]'


def test_build_toml_block() -> None:
    block = init._build_toml_block(["src/"], ["tests/"], ["scripts/"], ["--maxfail=1"])
    assert block.startswith("\n[tool.mutmut]\n")
    assert 'paths_to_mutate = ["src/"]' in block
    assert 'tests_dir = ["tests/"]' in block
    assert 'also_copy = ["scripts/"]' in block
    assert 'pytest_add_cli_args = [\n    "--maxfail=1",\n]' in block
    assert block.endswith("\n")


def test_build_toml_block_without_optional_sections() -> None:
    block = init._build_toml_block(["pkg/"], ["specs/"], None, None)
    assert 'paths_to_mutate = ["pkg/"]' in block
    assert 'tests_dir = ["specs/"]' in block
    assert "also_copy =" not in block
    assert "pytest_add_cli_args" not in block


def test_init_project_dry_run(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "pymutant.setup.detect_layout",
        lambda _root: {
            "layout": "flat_src",
            "notes": [],
            "suggested_config": {"paths_to_mutate": ["src/"], "tests_dir": ["tests/"]},
        },
    )
    out = init.init_project(dry_run=True, with_conftest=True, project_root=tmp_path)
    assert out["toml_written"] is False
    assert out["conftest_written"] is False
    assert any("[dry_run]" in action for action in out["actions"])


def test_init_project_writes_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    out = init.init_project(with_conftest=True, project_root=tmp_path)
    assert out["toml_written"] is True
    assert out["conftest_written"] is True
    assert "MUTANT_UNDER_TEST" in (tmp_path / "conftest.py").read_text()


def test_init_project_does_not_overwrite_existing_sections(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[tool.mutmut]\npaths_to_mutate=['src/']\n")
    (tmp_path / "conftest.py").write_text("MUTANT_UNDER_TEST")

    out = init.init_project(with_conftest=True, project_root=tmp_path)
    assert out["toml_written"] is False
    assert out["conftest_written"] is False
    assert out["warnings"]


def test_init_project_uses_explicit_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "pymutant.setup.detect_layout",
        lambda _root: {
            "layout": "flat_src",
            "notes": [],
            "suggested_config": {"paths_to_mutate": ["src/"], "tests_dir": ["tests/"]},
        },
    )
    out = init.init_project(
        paths_to_mutate=["pkg/"],
        tests_dir=["specs/"],
        also_copy=["scripts/"],
        dry_run=True,
        project_root=tmp_path,
    )
    assert out["config_used"]["paths_to_mutate"] == ["pkg/"]
    assert out["config_used"]["tests_dir"] == ["specs/"]
