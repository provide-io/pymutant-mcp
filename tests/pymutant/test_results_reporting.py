# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pymutant import results


def test_load_all_meta_files_missing_dir(tmp_path: Path) -> None:
    assert results.load_all_meta_files(tmp_path) == {}


def test_load_all_meta_files_skips_invalid_json(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants" / "src"
    meta_dir.mkdir(parents=True)
    (meta_dir / "good.meta").write_text(json.dumps({"exit_code_by_key": {"src.m.f__mutmut_1": 1}}))
    (meta_dir / "bad.meta").write_text("not-json")

    loaded = results.load_all_meta_files(tmp_path)
    assert "mutants/src/good.meta" in loaded
    assert "mutants/src/bad.meta" not in loaded


def test_load_all_meta_files_retries_transient_json_decode_error(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    target = meta_dir / "x.meta"
    target.write_text('{"ok": true}')

    attempts = {"n": 0}
    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == target and attempts["n"] == 0:
            attempts["n"] += 1
            return "{"
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    monkeypatch.setattr(results.time, "sleep", lambda _s: None)

    loaded = results.load_all_meta_files(tmp_path)
    assert loaded == {"mutants/x.meta": {"ok": True}}


def test_load_all_meta_files_skips_non_object_json(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "x.meta").write_text("[]")
    assert results.load_all_meta_files(tmp_path) == {}


def test_load_all_meta_files_handles_read_oserror(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    target = meta_dir / "x.meta"
    target.write_text('{"ok": true}')

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self == target:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    assert results.load_all_meta_files(tmp_path) == {}


def test_load_meta_json_returns_none_when_retries_zero(tmp_path: Path) -> None:
    target = tmp_path / "x.meta"
    target.write_text('{"ok": true}')
    assert results._load_meta_json(target, retries=0) is None


def test_key_to_source_file_with_function_segment() -> None:
    assert results._key_to_source_file("src.pkg.mod.func__mutmut_2") == "src/pkg/mod.py"


def test_key_to_source_file_without_function_segment() -> None:
    assert results._key_to_source_file("singlemodule__mutmut_2") == "singlemodule.py"


def test_key_to_source_file_resolves_class_method_against_project_root(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text("class UserManager: ...\n")

    key = "src.auth.UserManager.verify__mutmut_1"
    assert results._key_to_source_file(key, tmp_path) == "src/auth.py"


def test_key_to_source_file_project_root_fallback_when_missing(tmp_path: Path) -> None:
    key = "src.auth.UserManager.verify__mutmut_1"
    assert results._key_to_source_file(key, tmp_path) == "src/auth/UserManager.py"


def test_get_results_counts_and_filtering(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants" / "src"
    meta_dir.mkdir(parents=True)
    (meta_dir / "mod.meta").write_text(
        json.dumps(
            {
                "exit_code_by_key": {
                    "src.pkg.mod.a__mutmut_1": 0,
                    "src.pkg.mod.b__mutmut_2": 1,
                    "src.pkg.mod.c__mutmut_3": 5,
                    "src.pkg.mod.d__mutmut_4": 33,
                    "src.pkg.mod.e__mutmut_5": 34,
                    "src.pkg.mod.f__mutmut_6": 36,
                    "src.pkg.mod.g__mutmut_7": -11,
                    "src.pkg.mod.h__mutmut_8": None,
                    "src.pkg.mod.i__mutmut_9": 999,
                },
                "durations_by_key": {"src.pkg.mod.a__mutmut_1": 0.5},
            }
        )
    )

    data = results.get_results(project_root=tmp_path)
    assert data["counts"]["survived"] == 1
    assert data["counts"]["killed"] == 1
    assert data["counts"]["no_tests"] == 2
    assert data["counts"]["skipped"] == 1
    assert data["counts"]["timeout"] == 1
    assert data["counts"]["segfault"] == 1
    assert data["counts"]["not_checked"] == 1
    assert data["counts"]["suspicious"] == 1
    assert data["total"] == 9
    assert all(m["status"] != "killed" for m in data["mutants"])
    assert data["mutants"][0]["duration"] == 0.5

    included = results.get_results(include_killed=True, file_filter="src/pkg/mod.py", project_root=tmp_path)
    assert len(included["mutants"]) == 9


def test_get_results_filter_excludes_all(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "mod.meta").write_text(
        json.dumps({"exit_code_by_key": {"src.pkg.mod.a__mutmut_1": 0}, "durations_by_key": {}})
    )
    data = results.get_results(include_killed=True, file_filter="not-found", project_root=tmp_path)
    assert data["mutants"] == []
    assert data["total"] == 1


def test_get_results_ledger_overrides_meta_statuses(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "mod.meta").write_text(
        json.dumps({"exit_code_by_key": {"src.pkg.mod.a__mutmut_1": None}, "durations_by_key": {}})
    )
    monkeypatch.setattr(results, "resolve_latest_statuses", lambda _root: {"src.pkg.mod.a__mutmut_1": "killed"})
    data = results.get_results(include_killed=True, project_root=tmp_path)
    assert data["counts"]["killed"] == 1
    assert data["counts"]["not_checked"] == 0


def test_get_results_can_disable_ledger(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "mod.meta").write_text(
        json.dumps({"exit_code_by_key": {"src.pkg.mod.a__mutmut_1": None}, "durations_by_key": {}})
    )
    monkeypatch.setattr(results, "resolve_latest_statuses", lambda _root: {"src.pkg.mod.a__mutmut_1": "killed"})
    data = results.get_results(include_killed=True, use_ledger=False, project_root=tmp_path)
    assert data["counts"]["killed"] == 0
    assert data["counts"]["not_checked"] == 1


def test_get_results_progress_uses_strict_campaign(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "mod.meta").write_text(
        json.dumps({"exit_code_by_key": {"src.pkg.mod.a__mutmut_1": None}, "durations_by_key": {}})
    )
    (tmp_path / ".pymutant-strict-campaign.json").write_text(
        json.dumps({"names": ["a", "b", "c"], "attempted": ["a"], "stale": ["b"]})
    )
    data = results.get_results(include_killed=True, project_root=tmp_path)
    assert data["progress"]["source"] == "strict_campaign"
    assert data["progress"]["not_checked_effective"] == 1
    strict = data["progress"]["strict_campaign"]
    assert strict["exists"] is True
    assert strict["valid"] is True
    assert strict["remaining_not_checked"] == 1


def test_get_results_progress_falls_back_for_invalid_campaign(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "mod.meta").write_text(
        json.dumps({"exit_code_by_key": {"src.pkg.mod.a__mutmut_1": None}, "durations_by_key": {}})
    )
    (tmp_path / ".pymutant-strict-campaign.json").write_text("{bad")
    data = results.get_results(include_killed=True, project_root=tmp_path)
    assert data["progress"]["source"] == "meta"
    assert data["progress"]["not_checked_effective"] == 1
    strict = data["progress"]["strict_campaign"]
    assert strict["exists"] is True
    assert strict["valid"] is False


def test_get_results_progress_handles_malformed_campaign_shape(tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "mod.meta").write_text(
        json.dumps({"exit_code_by_key": {"src.pkg.mod.a__mutmut_1": None}, "durations_by_key": {}})
    )
    (tmp_path / ".pymutant-strict-campaign.json").write_text(
        json.dumps({"names": "not-a-list", "attempted": ["a"], "stale": []})
    )
    data = results.get_results(include_killed=True, project_root=tmp_path)
    strict = data["progress"]["strict_campaign"]
    assert strict["exists"] is True
    assert strict["valid"] is True
    assert strict["campaign_total"] == 0
    assert data["progress"]["not_checked_effective"] == 0


def test_get_results_returns_empty_when_runtime_baseline_invalid(monkeypatch, tmp_path: Path) -> None:
    meta_dir = tmp_path / "mutants"
    meta_dir.mkdir(parents=True)
    (meta_dir / "mod.meta").write_text(
        json.dumps({"exit_code_by_key": {"src.pkg.mod.a__mutmut_1": None}, "durations_by_key": {}})
    )
    monkeypatch.setattr(
        results,
        "baseline_status",
        lambda **_kwargs: {"valid": False, "reasons": ["git_head_changed"], "fingerprint_id": "x"},
    )
    data = results.get_results(include_killed=True, project_root=tmp_path)
    assert data["mutants"] == []
    assert data["total"] == 0
    assert data["progress"]["source"] == "baseline_invalid"
    assert data["baseline"]["valid"] is False


def test_get_mutant_diff_success(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    class Dummy:
        returncode = 0
        stdout = "diff text"
        stderr = ""

    def _run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return Dummy()

    monkeypatch.setattr(results.subprocess, "run", _run)
    out = results.get_mutant_diff("src.pkg.mod.a__mutmut_1", tmp_path)
    assert out == "diff text"
    assert seen["cmd"] == ["mutmut", "show", "src.pkg.mod.a__mutmut_1"]


def test_get_mutant_diff_prefers_project_venv_python(monkeypatch, tmp_path: Path) -> None:
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")
    seen: dict[str, object] = {}

    class Dummy:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return Dummy()

    monkeypatch.setattr(results.subprocess, "run", _run)
    out = results.get_mutant_diff("m.a__mutmut_1", tmp_path)
    assert out == "ok"
    assert seen["cmd"] == [str(py), "-m", "mutmut", "show", "m.a__mutmut_1"]


def test_get_mutant_diff_nonzero(monkeypatch, tmp_path: Path) -> None:
    class Dummy:
        returncode = 2
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(results.subprocess, "run", lambda *a, **k: Dummy())
    out = results.get_mutant_diff("name", tmp_path)
    assert out == "ERROR: mutmut show failed for name: boom"


def test_get_mutant_diff_timeout(monkeypatch, tmp_path: Path) -> None:
    def _raise(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["mutmut"], timeout=30)

    monkeypatch.setattr(results.subprocess, "run", _raise)
    assert results.get_mutant_diff("name", tmp_path).startswith("ERROR: mutmut show timed out")


def test_get_mutant_diff_missing_binary(monkeypatch, tmp_path: Path) -> None:
    def _raise(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(results.subprocess, "run", _raise)
    assert "mutmut not found" in results.get_mutant_diff("name", tmp_path)


def test_get_surviving_mutants_groups_and_marks_errors(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        results,
        "get_results",
        lambda **_: {
            "mutants": [
                {"name": "m1", "status": "survived", "source_file": "a.py"},
                {"name": "m2", "status": "killed", "source_file": "a.py"},
                {"name": "m3", "status": "survived", "source_file": "b.py"},
            ]
        },
    )

    def fake_diff(name: str, _root: Path) -> str:
        return "ERROR: nope" if name == "m3" else "ok"

    monkeypatch.setattr(results, "get_mutant_diff", fake_diff)
    grouped = results.get_surviving_mutants(project_root=tmp_path)

    assert len(grouped) == 2
    a_entry = next(g for g in grouped if g["source_file"] == "a.py")
    b_entry = next(g for g in grouped if g["source_file"] == "b.py")
    assert a_entry["mutants"][0]["diff"] == "ok"
    assert a_entry["mutants"][0]["diff_error"] is False
    assert b_entry["mutants"][0]["diff_error"] is True
