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


def test_ensure_gitignore_entries_dry_run(tmp_path: Path) -> None:
    updated, actions, warnings = init._ensure_gitignore_entries(tmp_path, dry_run=True)
    assert updated is False
    assert actions and actions[0].startswith("[dry_run] would append to .gitignore:")
    assert warnings == []


def test_ensure_gitignore_entries_writes_and_is_idempotent(tmp_path: Path) -> None:
    updated, actions, warnings = init._ensure_gitignore_entries(tmp_path, dry_run=False)
    assert updated is True
    assert warnings == []
    assert "appended to .gitignore:" in actions[0]
    text = (tmp_path / ".gitignore").read_text()
    assert ".pymutant-state/" in text
    assert "mutants/" in text

    updated2, actions2, warnings2 = init._ensure_gitignore_entries(tmp_path, dry_run=False)
    assert updated2 is False
    assert actions2 == []
    assert warnings2 == []


def test_ensure_gitignore_entries_appends_after_non_newline_text(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules")
    updated, actions, warnings = init._ensure_gitignore_entries(tmp_path, dry_run=False)
    assert updated is True
    assert actions
    assert warnings == []
    text = gitignore.read_text()
    assert "node_modules\n.pymutant-state/" in text


def test_ensure_gitignore_entries_write_error(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("")
    monkeypatch.setattr(Path, "write_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("denied")))
    updated, actions, warnings = init._ensure_gitignore_entries(tmp_path, dry_run=False)
    assert updated is False
    assert actions == []
    assert warnings and "could not update .gitignore automatically:" in warnings[0]


def test_init_project_dry_run(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "pymutant.setup.detect_layout",
        lambda _root: {
            "layout": "flat_src",
            "notes": [],
            "suggested_config": {"paths_to_mutate": ["src/"], "tests_dir": ["tests/"]},
        },
    )
    out = init.init_project(
        dry_run=True,
        with_conftest=True,
        also_copy=["scripts/"],
        pytest_add_cli_args=["--maxfail=1"],
        project_root=tmp_path,
    )
    assert out["toml_written"] is False
    assert out["conftest_written"] is False
    assert out["gitignore_updated"] is False
    assert any("[dry_run]" in action for action in out["actions"])
    dry_action = next(a for a in out["actions"] if "would append to pyproject.toml" in a)
    assert 'paths_to_mutate = ["src/"]' in dry_action
    assert 'tests_dir = ["tests/"]' in dry_action
    assert 'also_copy = ["scripts/"]' in dry_action
    assert 'pytest_add_cli_args = [\n    "--maxfail=1",\n]' in dry_action


def test_init_project_writes_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    out = init.init_project(with_conftest=True, project_root=tmp_path)
    assert out["toml_written"] is True
    assert out["conftest_written"] is True
    assert out["gitignore_updated"] is True
    assert "MUTANT_UNDER_TEST" in (tmp_path / "conftest.py").read_text()
    pyproject_text = (tmp_path / "pyproject.toml").read_text()
    assert 'paths_to_mutate = ["src/"]' in pyproject_text
    assert 'tests_dir = ["tests/"]' in pyproject_text
    assert "also_copy =" not in pyproject_text
    assert "pytest_add_cli_args" not in pyproject_text
    assert out["actions"] == [
        "appended [tool.mutmut] to pyproject.toml",
        "wrote conftest.py with MUTANT_UNDER_TEST sys.path guard",
        "appended to .gitignore: .pymutant-state/, mutants/, .pymutant-ledger.json, .pymutant-strict-campaign.json",
    ]


def test_init_project_writes_optional_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "pymutant.setup.detect_layout",
        lambda _root: {
            "layout": "flat_src",
            "notes": [],
            "suggested_config": {"paths_to_mutate": ["src/"], "tests_dir": ["tests/"]},
        },
    )
    out = init.init_project(
        also_copy=["scripts/"],
        pytest_add_cli_args=["-q", "--maxfail=1"],
        project_root=tmp_path,
    )
    assert out["toml_written"] is True
    assert out["gitignore_updated"] is True
    text = (tmp_path / "pyproject.toml").read_text()
    assert 'also_copy = ["scripts/"]' in text
    assert 'pytest_add_cli_args = [\n    "-q",\n    "--maxfail=1",\n]' in text
    assert out["actions"] == [
        "appended [tool.mutmut] to pyproject.toml",
        "appended to .gitignore: .pymutant-state/, mutants/, .pymutant-ledger.json, .pymutant-strict-campaign.json",
    ]


def test_init_project_does_not_overwrite_existing_sections(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[tool.mutmut]\npaths_to_mutate=['src/']\n")
    (tmp_path / "conftest.py").write_text("MUTANT_UNDER_TEST")
    (tmp_path / ".gitignore").write_text(
        ".pymutant-state/\nmutants/\n.pymutant-ledger.json\n.pymutant-strict-campaign.json\n"
    )

    out = init.init_project(with_conftest=True, project_root=tmp_path)
    assert out["toml_written"] is False
    assert out["conftest_written"] is False
    assert out["gitignore_updated"] is False
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
