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


def test_run_mutations_batches_pending_respects_explicit_max_children(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 1)
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: ["m1", "m2"])

    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return _FakePopen([("killed 1", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    runner.run_mutations(max_children=4, project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "m1", "--max-children", "4"]

def test_run_mutations_batched_retries_when_filters_stale(monkeypatch, tmp_path: Path) -> None:
    runner._PENDING_CURSOR_BY_ROOT.clear()
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 2)

    names_calls = [["old1", "old2", "old3"], ["new1", "new2", "new3"]]
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

    cmds: list[list[str]] = []

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        cmds.append(cmd)
        if len(cmds) == 1:
            return _FakePopen(
                [("", "AssertionError: Filtered for specific mutants, but nothing matches")],
                returncode=1,
            )
        return _FakePopen([("killed 1", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(project_root=tmp_path)
    assert cmds[0] == ["mutmut", "run", "old1", "old2", "--max-children", "2"]
    assert cmds[1] == ["mutmut", "run", "new3", "new1", "--max-children", "2"]
    assert out["returncode"] == 0

def test_run_mutations_batched_retry_with_explicit_max_children(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 1)

    names_calls = [["old1"], ["new1"]]
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

    cmds: list[list[str]] = []

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        cmds.append(cmd)
        if len(cmds) == 1:
            return _FakePopen(
                [("", "AssertionError: Filtered for specific mutants, but nothing matches")],
                returncode=1,
            )
        return _FakePopen([("killed 1", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    runner.run_mutations(max_children=4, project_root=tmp_path)
    assert cmds[1] == ["mutmut", "run", "new1", "--max-children", "4"]

def test_run_mutations_batched_retry_no_pending_after_refresh(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 1)

    names_calls = [["old1"], []]
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen(
            [("", "AssertionError: Filtered for specific mutants, but nothing matches")],
            returncode=1,
        ),
    )
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == 1
    assert out["remaining_not_checked"] == 0

def test_run_mutations_batched_fallbacks_to_unfiltered_on_second_stale(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 2)

    names_calls = [["old1", "old2"], ["new1", "new2"]]
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

    cmds: list[list[str]] = []

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        cmds.append(cmd)
        if len(cmds) < 3:
            return _FakePopen(
                [("", "AssertionError: Filtered for specific mutants, but nothing matches")],
                returncode=1,
            )
        return _FakePopen([("killed 1", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(project_root=tmp_path)
    assert cmds[0] == ["mutmut", "run", "old1", "old2", "--max-children", "2"]
    assert cmds[1] == ["mutmut", "run", "new1", "new2", "--max-children", "2"]
    assert cmds[2] == ["mutmut", "run", "--max-children", "2"]
    assert out["returncode"] == 0

def test_run_mutations_batched_fallback_unfiltered_respects_explicit_max_children(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    _patch_runner_symbol(monkeypatch, "_batch_size", lambda: 1)

    names_calls = [["old1"], ["new1"]]
    _patch_runner_symbol(monkeypatch, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

    cmds: list[list[str]] = []

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        cmds.append(cmd)
        if len(cmds) < 3:
            return _FakePopen(
                [("", "AssertionError: Filtered for specific mutants, but nothing matches")],
                returncode=1,
            )
        return _FakePopen([("killed 1", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    runner.run_mutations(max_children=4, project_root=tmp_path)
    assert cmds[2] == ["mutmut", "run", "--max-children", "4"]

def test_run_mutations_missing_mutmut(monkeypatch, tmp_path: Path) -> None:
    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)

    def _raise(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(runner.subprocess, "Popen", _raise)
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == -1
    assert "mutmut not found" in out["stderr"]

def test_run_mutations_loop_file_not_found(monkeypatch, tmp_path: Path) -> None:
    class LoopErr(_FakePopen):
        def communicate(self, timeout: int = 1) -> tuple[str, str]:
            raise FileNotFoundError

    _patch_runner_symbol(monkeypatch, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    _patch_runner_symbol(monkeypatch, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: LoopErr([]))
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == -1
    assert "mutmut not found" in out["stderr"]

def test_kill_stuck_mutmut_no_pkill(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: None)
    out = runner.kill_stuck_mutmut(tmp_path)
    assert out["returncode"] == -1

def test_kill_stuck_mutmut(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/pkill")

    class Done:
        def __init__(self, code: int) -> None:
            self.returncode = code

    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return Done(0 if "mutmut run" in cmd[-1] else 1)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    out = runner.kill_stuck_mutmut(tmp_path)
    assert out["ok"] is True
    assert out["killed_any"] is True
    assert len(calls) == 4

def test_kill_stuck_mutmut_none_killed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/pkill")

    class Done:
        def __init__(self, code: int) -> None:
            self.returncode = code

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: Done(1))
    out = runner.kill_stuck_mutmut(tmp_path)
    assert out["killed_any"] is False

def test_strict_campaign_status_missing(tmp_path: Path) -> None:
    out = runner.strict_campaign_status(tmp_path)
    assert out["exists"] is False
    assert out["campaign_total"] == 0

def test_strict_campaign_status_existing_and_reset(tmp_path: Path) -> None:
    (tmp_path / runner.STRICT_CAMPAIGN_FILE).write_text('{"names":["m1","m2"],"stale":["m2"],"attempted":["m1"]}')
    out = runner.strict_campaign_status(tmp_path)
    assert out["exists"] is True
    assert out["campaign_total"] == 2
    assert out["campaign_attempted"] == 1
    assert out["campaign_stale"] == 1
    assert out["remaining_not_checked"] == 1
    assert runner.reset_strict_campaign(tmp_path) is True
    assert runner.reset_strict_campaign(tmp_path) is False

