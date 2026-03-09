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
    monkeypatch.setattr(
        main,
        "run_mutations",
        lambda **kwargs: {
            **kwargs,
            "returncode": 0,
            "stderr": "",
            "summary": "ok",
        },
    )
    monkeypatch.setattr(main, "classify_transient_failure", lambda _res: (False, "non_transient"))
    out = main.pymutant_run(
        paths=["x"],
        max_children=2,
        strict_campaign=True,
        changed_only=True,
        base_ref="origin/main",
    )
    assert out["ok"] is True
    assert out["data"]["paths"] == ["x"]
    assert out["data"]["max_children"] == 2
    assert out["data"]["strict_campaign"] is True
    assert out["data"]["changed_only"] is True
    assert out["data"]["base_ref"] == "origin/main"
    assert out["data"]["project_root"] == tmp_path
    assert out["schema_version"] == "1.0"


def test_pymutant_run_failure_quarantine(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(
        main,
        "run_mutations",
        lambda **_kwargs: {"returncode": -1, "stderr": "timed out", "summary": "Timed out", "batched": True},
    )
    monkeypatch.setattr(main, "classify_transient_failure", lambda _res: (True, "transient_runtime"))
    monkeypatch.setattr(main, "record_quarantine", lambda *_args, **_kwargs: {"id": "q1"})
    out = main.pymutant_run()
    assert out["ok"] is False
    assert out["error"]["type"] == "tool_execution_error"
    assert out["data"]["quarantine"]["entry"] == {"id": "q1"}


def test_pymutant_kill_stuck_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "kill_stuck_mutmut", lambda **kwargs: {"ok": True, **kwargs})
    out = main.pymutant_kill_stuck()
    assert out["ok"] is True
    assert out["data"]["project_root"] == tmp_path


def test_pymutant_results_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_results", lambda **kwargs: kwargs)
    out = main.pymutant_results(include_killed=True, file_filter="a")
    assert out["ok"] is True
    assert out["data"]["include_killed"] is True
    assert out["data"]["file_filter"] == "a"


def test_pymutant_show_diff_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_mutant_diff", lambda name, project_root: f"{name}:{project_root}")
    out = main.pymutant_show_diff("x")
    assert out["ok"] is True
    assert "x" in out["data"]["diff"]


def test_pymutant_show_diff_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_mutant_diff", lambda _name, project_root=None: "ERROR: failed")
    out = main.pymutant_show_diff("x")
    assert out["ok"] is False
    assert out["error"]["type"] == "diff_error"


def test_pymutant_compute_score_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "compute_score", lambda **kwargs: kwargs)
    out = main.pymutant_compute_score()
    assert out["ok"] is True
    assert out["data"]["project_root"] == tmp_path


def test_pymutant_update_score_history_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "update_score_history", lambda **kwargs: kwargs)
    out = main.pymutant_update_score_history("label")
    assert out["ok"] is True
    assert out["data"]["label"] == "label"


def test_pymutant_surviving_mutants_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "get_surviving_mutants", lambda **kwargs: [kwargs])
    out = main.pymutant_surviving_mutants("src")
    assert out["ok"] is True
    assert out["data"][0]["file_filter"] == "src"


def test_pymutant_score_history_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "load_score_history", lambda root: {"root": root})
    out = main.pymutant_score_history()
    assert out["ok"] is True
    assert out["data"]["root"] == tmp_path


def test_pymutant_detect_layout_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "detect_layout", lambda **kwargs: kwargs)
    out = main.pymutant_detect_layout()
    assert out["ok"] is True
    assert out["data"]["project_root"] == tmp_path


def test_pymutant_check_setup_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "check_setup", lambda **kwargs: {"ok": True, **kwargs})
    out = main.pymutant_check_setup()
    assert out["ok"] is True
    assert out["data"]["project_root"] == tmp_path


def test_pymutant_check_setup_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "check_setup", lambda **kwargs: {"ok": False, **kwargs})
    out = main.pymutant_check_setup()
    assert out["ok"] is False
    assert out["error"]["type"] == "setup_error"


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
    assert out["ok"] is True
    assert out["data"]["project_root"] == tmp_path
    assert out["data"]["with_conftest"] is True
    assert out["data"]["dry_run"] is True


def test_pymutant_ledger_status_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "ledger_status", lambda **kwargs: {"ledger": kwargs})
    monkeypatch.setattr(main, "strict_campaign_status", lambda **kwargs: {"campaign": kwargs})
    monkeypatch.setattr(main, "load_quarantine", lambda **kwargs: {"entries": [], **kwargs})
    out = main.pymutant_ledger_status()
    assert out["ok"] is True
    assert "ledger" in out["data"]
    assert "campaign" in out["data"]
    assert "quarantine" in out["data"]


def test_pymutant_reset_campaign_delegates(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "reset_strict_campaign", lambda **kwargs: True)
    monkeypatch.setattr(main, "reset_ledger", lambda **kwargs: True)
    out = main.pymutant_reset_campaign(clear_ledger=True)
    assert out["ok"] is True
    assert out["data"]["removed_campaign"] is True
    assert out["data"]["removed_ledger"] is True


def test_new_tools_delegate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "rank_survivors", lambda **_kwargs: {"survivors": []})
    monkeypatch.setattr(main, "resolve_profile", lambda **_kwargs: {"profile": {"name": "default"}})
    monkeypatch.setattr(main, "compute_score", lambda **_kwargs: {"score": 0.5})
    monkeypatch.setattr(main, "evaluate_policy", lambda **_kwargs: {"ok": True, "failures": []})
    monkeypatch.setattr(main, "load_score_history", lambda _root: {"history": []})
    monkeypatch.setattr(main, "trend_report", lambda _history, window=5: {"window": window})
    monkeypatch.setattr(main, "suggest_pytest_patch", lambda **_kwargs: {"applied": False})
    monkeypatch.setattr(main, "get_results", lambda **_kwargs: {"mutants": []})
    monkeypatch.setattr(main, "render_html_bundle", lambda **_kwargs: {"ok": True, "path": "dist/pymutant-report.html"})

    ranked = main.pymutant_rank_survivors()
    explained = main.pymutant_explain_failure(-1, "timed out", "")
    policy = main.pymutant_policy_check()
    trend = main.pymutant_trend_report()
    patch = main.pymutant_suggest_pytest_patch("m.a__mutmut_1", "src/a.py", "diff", apply=False)
    report = main.pymutant_render_report()

    assert ranked["ok"] is True
    assert explained["data"]["category"] == "test-harness"
    assert policy["ok"] is True
    assert trend["ok"] is True
    assert patch["ok"] is True
    assert report["ok"] is True


def test_policy_check_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(main, "_root", lambda: tmp_path)
    monkeypatch.setattr(main, "compute_score", lambda **_kwargs: {"score": 0.3})
    monkeypatch.setattr(main, "evaluate_policy", lambda **_kwargs: {"ok": False, "failures": ["dropped"]})
    out = main.pymutant_policy_check()
    assert out["ok"] is False
    assert out["error"]["type"] == "policy_failure"


def test_main_runs_server(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(main.mcp, "run", lambda: calls.append("run"))
    main.main()
    assert calls == ["run"]
