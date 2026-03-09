# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from pymutant import main


def test_root_prefers_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PYMUTANT_PROJECT_ROOT", str(tmp_path))
    assert main._root() == tmp_path


def test_root_prefers_cwd_workspace_over_project_root_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PYMUTANT_PROJECT_ROOT", raising=False)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.0.0'\n")
    fallback = tmp_path / "fallback"
    fallback.mkdir()

    monkeypatch.setattr(main.Path, "read_text", lambda self: str(fallback))
    monkeypatch.setattr(main.Path, "exists", lambda self: self.name == ".project-root" or self.name == "pyproject.toml")
    monkeypatch.chdir(workspace)
    assert main._root() == workspace


def test_root_falls_back_to_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PYMUTANT_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(main.Path, "exists", lambda self: False)
    monkeypatch.chdir(tmp_path)
    assert main._root() == tmp_path


def test_root_uses_project_root_file_when_cwd_not_workspace(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PYMUTANT_PROJECT_ROOT", raising=False)
    configured = tmp_path / "configured"
    configured.mkdir()
    no_project = tmp_path / "no_project"
    no_project.mkdir()
    monkeypatch.chdir(no_project)
    monkeypatch.setattr(main.Path, "exists", lambda self: self.name == ".project-root")
    monkeypatch.setattr(main.Path, "read_text", lambda self: str(configured))
    assert main._root() == configured


def test_root_empty_project_root_file_falls_back_to_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PYMUTANT_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(main.Path, "exists", lambda self: self.name == ".project-root")
    monkeypatch.setattr(main.Path, "read_text", lambda self: "   ")
    monkeypatch.chdir(tmp_path)
    assert main._root() == tmp_path


def test_pymutant_run_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "run_mutations", lambda **kwargs: kwargs)
    out = main.pymutant_run(
        paths=["x"],
        max_children=2,
        strict_campaign=True,
        changed_only=True,
        base_ref="origin/main",
    )
    assert out["paths"] == ["x"]
    assert out["max_children"] == 2
    assert out["strict_campaign"] is True
    assert out["changed_only"] is True
    assert out["base_ref"] == "origin/main"
    assert out["project_root"] == tmp_path


def test_pymutant_kill_stuck_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "kill_stuck_mutmut", lambda **kwargs: kwargs)
    out = main.pymutant_kill_stuck()
    assert out["project_root"] == tmp_path


def test_pymutant_results_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_results", lambda **kwargs: kwargs)
    out = main.pymutant_results(include_killed=True, file_filter="a")
    assert out["include_killed"] is True
    assert out["file_filter"] == "a"


def test_pymutant_show_diff_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_mutant_diff", lambda name, project_root: f"{name}:{project_root}")
    assert "x" in main.pymutant_show_diff("x")


def test_pymutant_compute_score_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "compute_score", lambda **kwargs: kwargs)
    out = main.pymutant_compute_score()
    assert out["project_root"] == tmp_path


def test_pymutant_update_score_history_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "update_score_history", lambda **kwargs: kwargs)
    out = main.pymutant_update_score_history("label")
    assert out["label"] == "label"


def test_pymutant_surviving_mutants_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_surviving_mutants", lambda **kwargs: [kwargs])
    out = main.pymutant_surviving_mutants("src")
    assert out[0]["file_filter"] == "src"


def test_pymutant_score_history_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "load_score_history", lambda root: {"root": root})
    out = main.pymutant_score_history()
    assert out["root"] == tmp_path


def test_pymutant_detect_layout_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "detect_layout", lambda **kwargs: kwargs)
    out = main.pymutant_detect_layout()
    assert out["project_root"] == tmp_path


def test_pymutant_check_setup_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "check_setup", lambda **kwargs: kwargs)
    out = main.pymutant_check_setup()
    assert out["project_root"] == tmp_path


def test_pymutant_init_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "init_project", lambda **kwargs: kwargs)
    out = main.pymutant_init(
        paths_to_mutate=["src/"],
        tests_dir=["tests/"],
        also_copy=["conftest.py"],
        pytest_add_cli_args=["-q"],
        with_conftest=True,
        dry_run=True,
    )
    assert out["project_root"] == tmp_path
    assert out["with_conftest"] is True
    assert out["dry_run"] is True


def test_pymutant_ledger_status_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "ledger_status", lambda **kwargs: {"ledger": kwargs})
    monkeypatch.setattr(main, "strict_campaign_status", lambda **kwargs: {"campaign": kwargs})
    out = main.pymutant_ledger_status()
    assert "ledger" in out
    assert "campaign" in out


def test_pymutant_reset_campaign_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "reset_strict_campaign", lambda **kwargs: True)
    monkeypatch.setattr(main, "reset_ledger", lambda **kwargs: True)
    out = main.pymutant_reset_campaign(clear_ledger=True)
    assert out["ok"] is True
    assert out["removed_campaign"] is True
    assert out["removed_ledger"] is True


def test_main_runs_server(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main.mcp, "run", lambda: calls.append("run"))
    main.main()
    assert calls == ["run"]
