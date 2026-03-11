# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pymutant import ledger, runner


def _patch_runner_symbol(
    monkeypatch: pytest.MonkeyPatch, name: str, value: object, *, raising: bool = True
) -> None:
    patched = False
    for target in (runner, runner.helpers, runner.api):
        if hasattr(target, name):
            monkeypatch.setattr(target, name, value, raising=raising)
            patched = True
    if raising and not patched:
        msg = f"runner symbol not found: {name}"
        raise AttributeError(msg)


def test_project_root_or_cwd_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner._project_root_or_cwd(None) == tmp_path

def test_extract_summary_prefers_mutation_line() -> None:
    output = "\nline one\nmutants: 3 survived\n"
    assert runner._extract_summary(output) == "mutants: 3 survived"

def test_extract_summary_falls_back_to_last_line() -> None:
    assert runner._extract_summary("\na\nb\n") == "b"

def test_extract_summary_empty() -> None:
    assert runner._extract_summary("\n\n") == ""

def test_preferred_python(tmp_path: Path) -> None:
    assert runner._preferred_python(tmp_path) is None
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    assert runner._preferred_python(tmp_path) == str(py)

def test_mutmut_cmd_prefix(tmp_path: Path) -> None:
    assert runner._mutmut_cmd_prefix(tmp_path) == ["mutmut"]
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    assert runner._mutmut_cmd_prefix(tmp_path) == [str(py), "-m", "mutmut"]

def test_batch_size_default(monkeypatch) -> None:
    monkeypatch.delenv("PYMUTANT_BATCH_SIZE", raising=False)
    assert runner._batch_size() == runner.DEFAULT_MUTANT_BATCH_SIZE

def test_batch_size_invalid_or_small(monkeypatch) -> None:
    monkeypatch.setenv("PYMUTANT_BATCH_SIZE", "nope")
    assert runner._batch_size() == runner.DEFAULT_MUTANT_BATCH_SIZE
    monkeypatch.setenv("PYMUTANT_BATCH_SIZE", "0")
    assert runner._batch_size() == 1

def test_configured_mutation_roots_variants(tmp_path: Path) -> None:
    assert runner._configured_mutation_roots(tmp_path) == []
    (tmp_path / "pyproject.toml").write_text("[")
    assert runner._configured_mutation_roots(tmp_path) == []
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate="src/pkg/"\n')
    assert runner._configured_mutation_roots(tmp_path) == ["src/pkg"]
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/a/", " src/b "]\n')
    assert runner._configured_mutation_roots(tmp_path) == ["src/a", "src/b"]
    (tmp_path / "pyproject.toml").write_text("[tool.mutmut]\npaths_to_mutate=1\n")
    assert runner._configured_mutation_roots(tmp_path) == []

def test_filter_changed_python_paths(tmp_path: Path) -> None:
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "a.py").write_text("x=1\n")
    (src / "b.txt").write_text("x\n")
    outside = tmp_path / "other.py"
    outside.write_text("x=1\n")
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/pkg/"]\n')

    out = runner._filter_changed_python_paths(
        tmp_path,
        [
            "src/pkg/a.py",
            "src/pkg/a.py",
            "src/pkg/b.txt",
            "other.py",
            "/abs.py",
            "missing.py",
        ],
    )
    assert out == ["src/pkg/a.py"]

def test_filter_changed_python_paths_without_config(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("x=1\n")
    out = runner._filter_changed_python_paths(tmp_path, ["mod.py"])
    assert out == ["mod.py"]

def test_filter_changed_python_paths_accepts_absolute_paths(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    mod = src / "a.py"
    mod.write_text("x=1\n")
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/"]\n')
    out = runner._filter_changed_python_paths(tmp_path, [str(mod.resolve())])
    assert out == ["src/a.py"]

def test_filter_changed_python_paths_ignores_absolute_paths_outside_root(tmp_path: Path) -> None:
    external = tmp_path.parent / "external-outside.py"
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text("x=1\n")
    out = runner._filter_changed_python_paths(tmp_path, [str(external.resolve())])
    assert out == []

def test_filter_changed_python_paths_resolved_symlink_root(tmp_path: Path) -> None:
    server_mod = tmp_path / "server" / "src" / "pymutant"
    server_mod.mkdir(parents=True)
    target = server_mod / "runner.py"
    target.write_text("x=1\n")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "pymutant").symlink_to(server_mod)
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/pymutant/"]\n')

    out = runner._filter_changed_python_paths(tmp_path, ["server/src/pymutant/runner.py"])
    assert out == ["src/pymutant/runner.py"]


def test_filter_changed_python_paths_file_root_keeps_exact_file_selector(tmp_path: Path) -> None:
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    target = src / "a.py"
    target.write_text("x=1\n")
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/pkg/a.py"]\n')

    out = runner._filter_changed_python_paths(tmp_path, ["src/pkg/a.py"])
    assert out == ["src/pkg/a.py"]

def test_normalize_path_selectors_rewrites_to_configured_root(tmp_path: Path) -> None:
    real = tmp_path / "server" / "src" / "pkg"
    real.mkdir(parents=True)
    target = real / "mod.py"
    target.write_text("x=1\n")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "pkg").symlink_to(real)
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/pkg/"]\n')
    normalized, ignored = runner._normalize_path_selectors(tmp_path, [str(target)])
    assert normalized == ["src/pkg/mod.py"]
    assert ignored == []

def test_normalize_path_selectors_preserves_mutant_names_and_missing_paths(tmp_path: Path) -> None:
    selector = "a.b__mutmut_1"
    normalized, ignored = runner._normalize_path_selectors(tmp_path, [selector, "missing.py"])
    assert normalized == [selector, "missing.py"]
    assert ignored == []

def test_normalize_path_selectors_handles_empty_and_non_python_selectors(tmp_path: Path) -> None:
    normalized, ignored = runner._normalize_path_selectors(tmp_path, ["", "pkg.module"])
    assert normalized == ["pkg.module"]
    assert ignored == [""]

def test_normalize_path_selectors_outside_root_without_config_keeps_selector(tmp_path: Path) -> None:
    external = tmp_path.parent / "external-outside-selectors.py"
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_text("x=1\n")
    normalized, ignored = runner._normalize_path_selectors(tmp_path, [str(external.resolve())])
    assert normalized == [str(external.resolve())]
    assert ignored == []

def test_normalize_path_selectors_configured_file_root_keeps_exact_selector(tmp_path: Path) -> None:
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    target = src / "a.py"
    target.write_text("x=1\n")
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/pkg/a.py"]\n')
    normalized, ignored = runner._normalize_path_selectors(tmp_path, ["src/pkg/a.py"])
    assert normalized == ["src/pkg/a.py"]
    assert ignored == []

def test_normalize_path_selectors_configured_roots_without_match_keep_original(tmp_path: Path) -> None:
    src = tmp_path / "src" / "other"
    src.mkdir(parents=True)
    target = src / "a.py"
    target.write_text("x=1\n")
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/included/"]\n')
    normalized, ignored = runner._normalize_path_selectors(tmp_path, ["src/other/a.py"])
    assert normalized == ["src/other/a.py"]
    assert ignored == []

def test_resolve_changed_paths_for_mutation_no_git(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)
    paths, err = runner._resolve_changed_paths_for_mutation(tmp_path)
    assert paths == []
    assert err == "git is not available on this system"

def test_resolve_changed_paths_for_mutation_git_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/git")

    class Done:
        def __init__(self) -> None:
            self.returncode = 1
            self.stdout = ""

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: Done())
    paths, err = runner._resolve_changed_paths_for_mutation(tmp_path)
    assert paths == []
    assert err is not None

def test_resolve_changed_paths_for_mutation_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/git")
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x=1\n")
    (tmp_path / "new.py").write_text("x=1\n")
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/"]\n')

    class Done:
        def __init__(self, stdout: str) -> None:
            self.returncode = 0
            self.stdout = stdout

    calls = {"n": 0}

    def fake_run(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return Done("src/a.py\n")
        return Done("new.py\n")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    paths, err = runner._resolve_changed_paths_for_mutation(tmp_path, base_ref="origin/main")
    assert err is None
    assert paths == ["src/a.py"]

def test_resolve_changed_paths_for_mutation_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/git")

    def fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=1)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    paths, err = runner._resolve_changed_paths_for_mutation(tmp_path)
    assert paths == []
    assert err is not None

def test_load_not_checked_mutants(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants" / "src"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text('{"exit_code_by_key":{"a":null,"b":1}}')
    assert runner._load_not_checked_mutants(tmp_path) == ["a"]

def test_load_not_checked_mutants_ignores_bad_json(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text("{")
    assert runner._load_not_checked_mutants(tmp_path) == []


def test_load_not_checked_mutants_ignores_non_mapping_exit_codes(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text('{"exit_code_by_key":[["a", null]]}')
    assert runner._load_not_checked_mutants(tmp_path) == []


def test_load_not_checked_mutants_retries_transient_json_decode(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    target = meta_dir / "x.meta"
    target.write_text('{"exit_code_by_key":{"a":null}}')

    attempts = {"n": 0}
    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == target and attempts["n"] == 0:
            attempts["n"] += 1
            return "{"
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    monkeypatch.setattr(runner.helpers.time, "sleep", lambda _s: None)
    assert runner._load_not_checked_mutants(tmp_path) == ["a"]

def test_sanitize_mutant_meta_files(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    good = meta_dir / "good.meta"
    bad = meta_dir / "bad.meta"
    good.write_text('{"exit_code_by_key":{"a":1}}')
    bad.write_text("{")

    summary = runner._sanitize_mutant_meta_files(tmp_path)

    assert summary["scanned"] == 2
    assert summary["invalid_removed"] == 1
    assert str(bad) in summary["removed_paths"]
    assert good.exists()
    assert not bad.exists()


def test_sanitize_mutant_meta_files_retries_before_deleting(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    target = meta_dir / "x.meta"
    target.write_text('{"exit_code_by_key":{"a":1}}')

    attempts = {"n": 0}
    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == target and attempts["n"] == 0:
            attempts["n"] += 1
            return "{"
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    monkeypatch.setattr(runner.helpers.time, "sleep", lambda _s: None)
    summary = runner._sanitize_mutant_meta_files(tmp_path)
    assert summary["scanned"] == 1
    assert summary["invalid_removed"] == 0
    assert target.exists()

def test_sanitize_mutant_meta_files_removes_multiple_invalid(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    bad1 = meta_dir / "bad1.meta"
    bad2 = meta_dir / "bad2.meta"
    bad1.write_text("{")
    bad2.write_text("{")

    summary = runner._sanitize_mutant_meta_files(tmp_path)
    assert summary["scanned"] == 2
    assert summary["invalid_removed"] == 2
    assert sorted(summary["removed_paths"]) == sorted([str(bad1), str(bad2)])
    assert not bad1.exists()
    assert not bad2.exists()

def test_sanitize_mutant_meta_files_unlink_error(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    bad = meta_dir / "bad.meta"
    bad.write_text("{")

    original_unlink = Path.unlink

    def fake_unlink(self: Path, missing_ok: bool = False) -> None:
        if self == bad:
            raise OSError("nope")
        original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    summary = runner._sanitize_mutant_meta_files(tmp_path)

    assert summary["scanned"] == 1
    assert summary["invalid_removed"] == 0
    assert summary["removed_paths"] == []
    assert bad.exists()

def test_select_batch_names_empty(tmp_path: Path) -> None:
    assert runner._select_batch_names([], tmp_path, 2) == []

def test_select_batch_names_takes_first_batch(tmp_path: Path) -> None:
    names = ["a", "b", "c"]
    assert runner._select_batch_names(names, tmp_path, 2) == ["a", "b"]
    assert runner._select_batch_names(names, tmp_path, 2) == ["a", "b"]


def test_select_batch_names_enforces_min_batch_size(tmp_path: Path) -> None:
    names = ["a", "b", "c"]
    assert runner._select_batch_names(names, tmp_path, 0) == ["a"]

def test_load_exit_codes_by_key(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants" / "src"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text('{"exit_code_by_key":{"a":null,"b":1}}')
    assert runner._load_exit_codes_by_key(tmp_path) == {"a": None, "b": 1}

def test_load_exit_codes_by_key_missing_or_bad_json(tmp_path: Path) -> None:
    assert runner._load_exit_codes_by_key(tmp_path) == {}
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text("{")
    assert runner._load_exit_codes_by_key(tmp_path) == {}


def test_load_exit_codes_by_key_skips_non_object_json(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text("[]")
    assert runner._load_exit_codes_by_key(tmp_path) == {}


def test_load_exit_codes_by_key_ignores_non_mapping_exit_codes(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text('{"exit_code_by_key":[["a", 1]]}')
    assert runner._load_exit_codes_by_key(tmp_path) == {}


def test_load_exit_codes_by_key_handles_read_oserror(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    target = meta_dir / "x.meta"
    target.write_text('{"exit_code_by_key":{"a":1}}')

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == target:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    assert runner._load_exit_codes_by_key(tmp_path) == {}


def test_runner_load_meta_json_returns_none_when_retries_zero(tmp_path: Path) -> None:
    target = tmp_path / "x.meta"
    target.write_text('{"exit_code_by_key":{"a":1}}')
    assert runner.helpers._load_meta_json(target, retries=0) is None

def test_record_ledger_outcomes_records_stale_and_mapped(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", lambda _root: {"m1": 1, "m2": None})
    runner._record_ledger_outcomes(tmp_path, ["m1", "m2"], stale_names={"m2"}, context="ctx")
    event = ledger.load_ledger(tmp_path)["events"][-1]
    assert event["mutants"] == {"m1": "killed", "m2": "stale"}
    assert event["context"] == "ctx"

def test_record_ledger_outcomes_empty_names_noop(monkeypatch, tmp_path: Path) -> None:
    called = {"append": False}
    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", lambda _root: (_ for _ in ()).throw(AssertionError("unused")))
    _patch_runner_symbol(
        monkeypatch,
        "append_ledger_event",
        lambda *_a, **_k: called.__setitem__("append", True),
    )
    runner._record_ledger_outcomes(tmp_path, [], context="ctx")
    assert called["append"] is False

def test_parse_mutmut_result_lines() -> None:
    out = runner._parse_mutmut_result_lines(
        "\n".join(
            [
                "",
                "🎉 a.b.c__mutmut_1",
                "🙁 a.b.c__mutmut_2",
                "noise",
                "🫥 a.b.c__mutmut_3",
                "🔇 not-a-mutant",
            ]
        )
    )
    assert out == {
        "a.b.c__mutmut_1": "killed",
        "a.b.c__mutmut_2": "survived",
        "a.b.c__mutmut_3": "no_tests",
    }

def test_record_ledger_outcomes_prefers_parsed_output(monkeypatch, tmp_path: Path) -> None:
    name = "m.a__mutmut_1"
    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", lambda _root: {name: None})
    seen: dict[str, object] = {}
    _patch_runner_symbol(
        monkeypatch,
        "append_ledger_event",
        lambda outcomes, context, project_root: seen.update(
            {"outcomes": outcomes, "context": context, "project_root": project_root}
        ),
    )
    runner._record_ledger_outcomes(
        tmp_path,
        [name],
        run_output=f"🎉 {name}",
        context="ctx",
    )
    assert seen["outcomes"] == {name: "killed"}

def test_init_or_load_strict_campaign_creates_file(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: ["m1", "m2"])
    campaign = runner._init_or_load_strict_campaign(tmp_path)
    assert campaign == {"names": ["m1", "m2"], "stale": [], "attempted": []}
    assert (tmp_path / runner.STRICT_CAMPAIGN_FILE).exists()

def test_init_or_load_strict_campaign_handles_invalid_file(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / runner.STRICT_CAMPAIGN_FILE).write_text("{")
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: ["x"])
    campaign = runner._init_or_load_strict_campaign(tmp_path)
    assert campaign["names"] == ["x"]

def test_init_or_load_strict_campaign_handles_nondict_and_invalid_stale(tmp_path: Path) -> None:
    (tmp_path / runner.STRICT_CAMPAIGN_FILE).write_text("[1,2,3]")
    campaign = runner._init_or_load_strict_campaign(tmp_path)
    assert campaign == {"names": [], "stale": [], "attempted": []}
    (tmp_path / runner.STRICT_CAMPAIGN_FILE).write_text('{"names":["m1"],"stale":[1]}')
    campaign2 = runner._init_or_load_strict_campaign(tmp_path)
    assert campaign2 == {"names": ["m1"], "stale": [], "attempted": []}

def test_init_or_load_strict_campaign_accepts_valid_stale(tmp_path: Path) -> None:
    (tmp_path / runner.STRICT_CAMPAIGN_FILE).write_text('{"names":["m1"],"stale":["m0"]}')
    campaign = runner._init_or_load_strict_campaign(tmp_path)
    assert campaign == {"names": ["m1"], "stale": ["m0"], "attempted": []}

def test_init_or_load_strict_campaign_invalid_attempted(tmp_path: Path) -> None:
    (tmp_path / runner.STRICT_CAMPAIGN_FILE).write_text('{"names":["m1"],"attempted":[1]}')
    campaign = runner._init_or_load_strict_campaign(tmp_path)
    assert campaign == {"names": ["m1"], "stale": [], "attempted": []}

def test_strict_remaining_names_filters_completed_and_stale(monkeypatch, tmp_path: Path) -> None:
    campaign = {"names": ["m1", "m2", "m3"], "stale": ["m3"], "attempted": ["m2", "m3"]}
    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", lambda _root: {"m1": None, "m2": 1, "m3": None})
    assert runner._strict_remaining_names(tmp_path, campaign) == ["m1"]


def test_strict_remaining_names_filters_stale_even_if_not_attempted(monkeypatch, tmp_path: Path) -> None:
    campaign = {"names": ["m1", "m2"], "stale": ["m2"], "attempted": []}
    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", lambda _root: {"m1": None, "m2": None})
    assert runner._strict_remaining_names(tmp_path, campaign) == ["m1"]

def test_requires_mcp_dependency_from_paths(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["server/src/"]\n')
    assert runner._requires_mcp_dependency(tmp_path) is True

def test_requires_mcp_dependency_from_string_path(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate="server/src/"\n')
    assert runner._requires_mcp_dependency(tmp_path) is True

def test_requires_mcp_dependency_from_tests(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("from pymutant import main")
    assert runner._requires_mcp_dependency(tmp_path) is True

def test_requires_mcp_dependency_false_paths_and_tests(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool.mutmut]\npaths_to_mutate=["src/"]\n')
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("assert True")
    assert runner._requires_mcp_dependency(tmp_path) is False

def test_requires_mcp_dependency_invalid_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[")
    assert runner._requires_mcp_dependency(tmp_path) is False

def test_requires_mcp_dependency_test_read_error(monkeypatch, tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    broken = tests / "test_x.py"
    broken.write_text("x")
    monkeypatch.setattr(Path, "read_text", lambda _self: (_ for _ in ()).throw(OSError("x")))
    assert runner._requires_mcp_dependency(tmp_path) is False

def test_dependency_preflight_pass(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    class Dummy:
        returncode = 0

    def _run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return Dummy()

    monkeypatch.setattr(runner.subprocess, "run", _run)
    err = runner._dependency_preflight(tmp_path, ["/venv/python", "-m", "mutmut"])
    assert err is None
    assert calls == [["/venv/python", "-c", "import mutmut"]]

def test_dependency_preflight_fail(monkeypatch, tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("from pymutant import main")

    class Dummy:
        returncode = 1

    calls: list[list[str]] = []

    def _run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return Dummy()

    monkeypatch.setattr(runner.subprocess, "run", _run)
    err = runner._dependency_preflight(tmp_path, ["/venv/python", "-m", "mutmut"])
    assert err is not None
    assert "uv sync" in err
    assert calls and calls[0] == ["/venv/python", "-c", "import mutmut"]

def test_dependency_preflight_includes_mcp_when_required(monkeypatch, tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("from pymutant import main")
    seen: list[list[str]] = []

    class Dummy:
        def __init__(self, returncode: int):
            self.returncode = returncode

    def _run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen.append(cmd)
        return Dummy(0)

    monkeypatch.setattr(runner.subprocess, "run", _run)
    assert runner._dependency_preflight(tmp_path, ["/venv/python", "-m", "mutmut"]) is None
    assert seen == [
        ["/venv/python", "-c", "import mutmut"],
        ["/venv/python", "-c", "import mcp"],
    ]

def test_dependency_preflight_non_module_cmd(tmp_path: Path) -> None:
    assert runner._dependency_preflight(tmp_path, ["mutmut"]) is None

def test_sanitize_cmd_output_removes_ansi_spinner_and_truncates(monkeypatch) -> None:
    monkeypatch.setattr(runner.helpers, "MAX_CMD_OUTPUT_CHARS", 20)
    raw = "\x1b[31merror\x1b[0m\r\n⠋ 1/10 working\r\nnormal line with many characters here\r\n"
    sanitized = runner._sanitize_cmd_output(raw)
    assert "error" in sanitized
    assert "⠋ 1/10" not in sanitized
    assert "output truncated" in sanitized
