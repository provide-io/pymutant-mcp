# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess

from pymutant import runner


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


def test_terminate_process_tree_unix(monkeypatch) -> None:
    proc = _FakePopen([("", "")])
    called: list[tuple[int, int]] = []
    monkeypatch.setattr(runner.os, "killpg", lambda pid, sig: called.append((pid, sig)))
    runner._terminate_process_tree(proc)
    assert called

def test_terminate_process_tree_already_exited(monkeypatch) -> None:
    proc = _FakePopen([("", "")])
    monkeypatch.setattr(proc, "poll", lambda: 0)
    runner._terminate_process_tree(proc)

def test_terminate_process_tree_process_lookup(monkeypatch) -> None:
    proc = _FakePopen([("", "")])

    def _raise(_pid: int, _sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(runner.os, "killpg", _raise)
    runner._terminate_process_tree(proc)

def test_terminate_process_tree_fallback_terminate(monkeypatch) -> None:
    proc = _FakePopen([("", "")])
    monkeypatch.setattr(runner.os, "killpg", lambda _pid, _sig: (_ for _ in ()).throw(OSError("x")))
    runner._terminate_process_tree(proc)
    assert proc.returncode == -15

def test_terminate_process_tree_kill_after_wait_timeout(monkeypatch) -> None:
    proc = _FakePopen([("", "")])
    monkeypatch.setattr(runner.os, "killpg", lambda _pid, _sig: None)
    monkeypatch.setattr(
        proc,
        "wait",
        lambda timeout=3: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["x"], timeout=timeout)),
    )
    runner._terminate_process_tree(proc)

def test_terminate_process_tree_kill_fallback(monkeypatch) -> None:
    proc = _FakePopen([("", "")])

    calls = {"n": 0}

    def killpg(_pid: int, _sig: int) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("x")

    monkeypatch.setattr(runner.os, "killpg", killpg)
    monkeypatch.setattr(
        proc,
        "wait",
        lambda timeout=3: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["x"], timeout=timeout)),
    )
    runner._terminate_process_tree(proc)
    assert proc.returncode == -9

def test_terminate_process_tree_windows_branch(monkeypatch) -> None:
    proc = _FakePopen([("", "")])
    monkeypatch.setattr(runner.os, "name", "nt", raising=False)
    runner._terminate_process_tree(proc)
    assert proc.returncode == -15

def test_terminate_process_tree_windows_kill(monkeypatch) -> None:
    proc = _FakePopen([("", "")])
    monkeypatch.setattr(runner.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        proc,
        "wait",
        lambda timeout=3: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=["x"], timeout=timeout)),
    )
    runner._terminate_process_tree(proc)
    assert proc.returncode == -9
