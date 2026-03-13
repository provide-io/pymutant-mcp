# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pymutant import runner


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


class _FakePopen:
    def __init__(self, outputs: list[tuple[str, str]], returncode: int = 0, timeout_always: bool = False) -> None:
        self._outputs = outputs
        self._index = 0
        self.returncode = returncode
        self.timeout_always = timeout_always
        self.pid = 1234

    def communicate(self, timeout: int = 1) -> tuple[str, str]:
        if self.timeout_always:
            raise subprocess.TimeoutExpired(cmd=["mutmut"], timeout=timeout, output="", stderr="")
        if self._index < len(self._outputs):
            out, err = self._outputs[self._index]
            self._index += 1
            if self._index == len(self._outputs):
                return out, err
            raise subprocess.TimeoutExpired(cmd=["mutmut"], timeout=timeout, output=out, stderr=err)
        return "", ""

    def poll(self) -> int | None:
        return None

    def wait(self, timeout: int = 3) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9

    def __enter__(self) -> _FakePopen:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


@pytest.fixture(autouse=True)
def _stub_runtime_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_runner_symbol(
        monkeypatch,
        "ensure_runtime_baseline",
        lambda **_kwargs: {
            "valid": True,
            "was_invalid": False,
            "reasons": [],
            "fingerprint_id": "test-fingerprint",
            "auto_reset_applied": False,
        },
    )


def test_run_mutations_success(monkeypatch, tmp_path: Path) -> None:
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")

    class RunOK:
        returncode = 0

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: RunOK())
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([("killed 2", "")], returncode=0))
    _patch_runner_symbol(
        monkeypatch,
        "ensure_runtime_baseline",
        lambda **_kwargs: {"valid": True, "reasons": [], "fingerprint_id": "fp", "auto_reset_applied": False},
    )
    out = runner.run_mutations(paths=["src/mod.py"], max_children=2, project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["summary"] == "killed 2"
    assert out["batched"] is False
    assert out["meta_sanitize"]["scanned"] == 0
    assert out["baseline"]["fingerprint_id"] == "fp"

def test_run_mutations_dependency_preflight_failure(monkeypatch, tmp_path: Path) -> None:
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")

    class RunBad:
        returncode = 1

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: RunBad())
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == -1
    assert "preflight" in out["summary"]

def test_run_mutations_timeout(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([], timeout_always=True))
    _patch_runner_symbol(monkeypatch, "MUTMUT_TIMEOUT", 0)
    called = {"k": False}
    _patch_runner_symbol(monkeypatch, "_terminate_process_tree", lambda _proc: called.__setitem__("k", True))
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == -1
    assert "timed out" in out["stderr"]
    assert called["k"] is True

def test_run_mutations_no_progress_timeout(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([], timeout_always=True))
    _patch_runner_symbol(monkeypatch, "MUTMUT_TIMEOUT", 1000)
    _patch_runner_symbol(monkeypatch, "MUTMUT_NO_PROGRESS_TIMEOUT", 0)
    _patch_runner_symbol(monkeypatch, "_terminate_process_tree", lambda _proc: None)
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == -1
    assert "stalled" in out["stderr"]

def test_run_mutations_loop_continues_until_output(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen([("progress", ""), ("done killed", "")], returncode=0),
    )
    _patch_runner_symbol(monkeypatch, "MUTMUT_TIMEOUT", 1000)
    _patch_runner_symbol(monkeypatch, "MUTMUT_NO_PROGRESS_TIMEOUT", 1000)
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == 0
    assert "killed" in out["summary"]


def test_run_mutations_can_request_raw_output(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    seen: dict[str, object] = {}

    def _run_cmd(cmd: list[str], root: Path, *, compact_progress: bool = True) -> dict[str, object]:
        seen["cmd"] = cmd
        seen["root"] = root
        seen["compact_progress"] = compact_progress
        return {"returncode": 0, "stdout": "ok", "stderr": "", "summary": "ok"}

    _patch_runner_symbol(monkeypatch, "_run_cmd", _run_cmd)
    out = runner.run_mutations(project_root=tmp_path, include_raw_output=True)
    assert out["returncode"] == 0
    assert seen["compact_progress"] is False

def test_run_mutations_batches_pending_not_checked(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 2)
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: ["m1", "m2", "m3"])

    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return _FakePopen([("killed 1", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "m1", "m2", "--max-children", "2"]
    assert out["batched"] is True
    assert out["batch_size"] == 2
    assert out["remaining_not_checked"] == 1

def test_run_mutations_strict_campaign_uses_snapshot(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 2)
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: ["m1", "m2", "m3"])

    calls = {"n": 0}

    def fake_exit_codes(_root: Path) -> dict[str, int | None]:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"m1": None, "m2": None, "m3": None}
        return {"m1": 1, "m2": 0, "m3": None}

    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):
        seen["cmd"] = cmd
        return _FakePopen([("done", "")], returncode=0)

    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", fake_exit_codes)
    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "m1", "m2", "--max-children", "2"]
    assert out["strict_campaign"] is True
    assert out["campaign_total"] == 3
    assert out["campaign_attempted"] == 2
    assert out["remaining_not_checked"] == 1

def test_run_mutations_strict_campaign_marks_stale_and_continues(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 1)
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: ["m1"])
    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", lambda _root: {"m1": None})
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen(
            [("", "AssertionError: Filtered for specific mutants, but nothing matches")],
            returncode=1,
        ),
    )
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["campaign_stale"] == 1
    assert out["remaining_not_checked"] == 0
    assert out["summary"] == "strict campaign refreshed stale selectors"

def test_run_mutations_strict_campaign_marks_stale_with_empty_stderr(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 1)
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: ["m1"])
    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", lambda _root: {"m1": None})
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen([("", "Filtered for specific mutants, but nothing matches")], returncode=1),
    )
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert (
        out["stderr"]
        == "Filtered for specific mutants, but nothing matches\nRefreshed strict-campaign selectors and continuing."
    )

def test_run_mutations_strict_campaign_refreshes_snapshot_after_stale(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 1)

    calls = {"n": 0}

    def _load_not_checked(_root: Path) -> list[str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return ["old1"]
        return ["new1", "new2"]

    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", _load_not_checked)
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen([("", "Filtered for specific mutants, but nothing matches")], returncode=1),
    )
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["campaign_total"] == 2
    assert out["campaign_attempted"] == 0
    assert out["campaign_stale"] == 1
    assert out["remaining_not_checked"] == 2
    campaign = runner._init_or_load_strict_campaign(tmp_path)
    assert campaign["names"] == ["new1", "new2"]
    assert campaign["attempted"] == []
    assert campaign["stale"] == ["old1"]

def test_run_mutations_strict_campaign_no_pending_is_noop(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: [])
    _patch_runner_symbol(monkeypatch, "_run_cmd", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run cmd")))
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["summary"] == "strict campaign complete; nothing to run"
    assert out["strict_campaign"] is True
    assert out["campaign_total"] == 0
    assert out["campaign_attempted"] == 0
    assert out["remaining_not_checked"] == 0

def test_run_mutations_strict_campaign_ignored_with_paths(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)

    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return _FakePopen([("done", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(paths=["src/x.py"], strict_campaign=True, changed_only=True, project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "src/x.py"]
    assert out["strict_campaign"] is False
    assert out["changed_only"] is False

def test_run_mutations_changed_only_detection_error(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_resolve_changed_paths_for_mutation", lambda *_a, **_k: ([], "boom"))
    _patch_runner_symbol(monkeypatch, "ensure_runtime_baseline", lambda **_kwargs: {"valid": True, "reasons": []})
    out = runner.run_mutations(changed_only=True, project_root=tmp_path)
    assert out["returncode"] == -1
    assert out["baseline"]["valid"] is True
    assert out["summary"] == "changed file detection failed"
    assert out["changed_only"] is True

def test_run_mutations_changed_only_no_paths(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_resolve_changed_paths_for_mutation", lambda *_a, **_k: ([], None))
    out = runner.run_mutations(changed_only=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["summary"] == "no changed python files under mutation roots"
    assert out["changed_only"] is True
    assert out["changed_paths"] == []

def test_run_mutations_changed_only_runs_paths(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_resolve_changed_paths_for_mutation", lambda *_a, **_k: (["src/a.py"], None))
    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return _FakePopen([("done", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(changed_only=True, base_ref="origin/main", project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "src/a.py"]
    assert out["changed_only"] is True
    assert out["changed_paths"] == ["src/a.py"]


def test_run_mutations_changed_only_no_matching_selectors_is_noop(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_resolve_changed_paths_for_mutation", lambda *_a, **_k: (["src/a.py"], None))
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen([("", "Filtered for specific mutants, but nothing matches")], returncode=1),
    )
    out = runner.run_mutations(changed_only=True, base_ref="origin/main", project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["summary"] == "no matching mutants for changed selectors"
    assert out["changed_only"] is True
    assert out["changed_paths"] == ["src/a.py"]


def test_run_mutations_changed_only_non_int_returncode_passthrough(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_resolve_changed_paths_for_mutation", lambda *_a, **_k: (["src/a.py"], None))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([("done", "")], returncode=None))  # type: ignore[arg-type]
    out = runner.run_mutations(changed_only=True, base_ref="origin/main", project_root=tmp_path)
    assert out["returncode"] is None
    assert out["changed_only"] is True
    assert out["changed_paths"] == ["src/a.py"]


def test_run_mutations_changed_only_non_stale_error_passthrough(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_resolve_changed_paths_for_mutation", lambda *_a, **_k: (["src/a.py"], None))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([("", "boom")], returncode=1))
    out = runner.run_mutations(changed_only=True, base_ref="origin/main", project_root=tmp_path)
    assert out["returncode"] == 1
    assert out["summary"] == "boom"
    assert out["changed_only"] is True
    assert out["changed_paths"] == ["src/a.py"]


def test_run_mutations_paths_mutant_selectors_record_ledger(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([("done", "")], returncode=0))

    seen: dict[str, object] = {}

    def _record(
        root: Path,
        names: list[str],
        *,
        stale_names: set[str] | None = None,
        context: str,
        run_output: str = "",
    ) -> None:
        seen["root"] = root
        seen["names"] = names
        seen["context"] = context
        seen["stale_names"] = stale_names
        seen["run_output"] = run_output

    _patch_runner_symbol(monkeypatch, "_record_ledger_outcomes", _record)
    out = runner.run_mutations(paths=["m.a__mutmut_1"], strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert seen["names"] == ["m.a__mutmut_1"]
    assert seen["context"] == "explicit_selectors"

def test_run_mutations_paths_normalizes_selectors(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_normalize_path_selectors", lambda _root, _paths: (["src/a.py"], ["missing.py"]))

    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return _FakePopen([("done", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(paths=["src/a.py", "missing.py"], project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "src/a.py"]
    assert out["normalized_paths"] == ["src/a.py"]
    assert out["ignored_paths"] == ["missing.py"]

def test_run_mutations_paths_selector_miss_surfaces_clear_hint(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_normalize_path_selectors", lambda _root, _paths: (["src/a.py"], []))
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen([("", "Filtered for specific mutants, but nothing matches")], returncode=1),
    )
    out = runner.run_mutations(paths=["src/a.py"], project_root=tmp_path)
    assert out["returncode"] == 1
    assert out["refresh_recommended"] is True
    assert "path selectors did not match any generated mutants" in out["summary"]

def test_run_mutations_paths_with_no_valid_selectors_fails_early(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_normalize_path_selectors", lambda _root, _paths: ([], ["bad.py"]))
    out = runner.run_mutations(paths=["bad.py"], project_root=tmp_path)
    assert out["returncode"] == -1
    assert out["summary"] == "path selectors did not match mutation roots"

def test_run_mutations_zero_files_mutated_adds_refresh_hint(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen([("0 files mutated, 54 unmodified", "")], returncode=0),
    )
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["refresh_recommended"] is True
    assert "pymutant_baseline_refresh" in out["hint"]

def test_augment_paths_selector_miss_passthrough_cases() -> None:
    non_int = runner.api._augment_paths_selector_miss(
        result={"returncode": None, "stderr": "Filtered for specific mutants, but nothing matches"},
        normalized_paths=["src/a.py"],
    )
    assert non_int["returncode"] is None

    non_stale = runner.api._augment_paths_selector_miss(
        result={"returncode": 1, "stderr": "boom", "summary": "boom"},
        normalized_paths=["src/a.py"],
    )
    assert non_stale["summary"] == "boom"

def test_augment_zero_mutation_hint_sets_default_summary() -> None:
    out = runner.api._augment_zero_mutation_hint(result={"returncode": 0, "stdout": "0 files mutated, 10 unmodified", "stderr": "", "summary": ""})
    assert out["summary"] == "mutmut reported zero mutated files"
    assert out["refresh_recommended"] is True

def test_run_mutations_strict_campaign_does_not_mark_attempted_on_launch_error(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 1)
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: ["m1"])
    _patch_runner_symbol(monkeypatch, "_load_exit_codes_by_key", lambda _root: {})

    def _raise(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(runner.subprocess, "Popen", _raise)
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == -1
    assert out["campaign_attempted"] == 0
    assert out["remaining_not_checked"] == 1
