# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
from pathlib import Path

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


def test_select_batch_names_empty(tmp_path: Path) -> None:
    runner._PENDING_CURSOR_BY_ROOT.clear()
    assert runner._select_batch_names([], tmp_path, 2) == []


def test_select_batch_names_rotates_and_wraps(tmp_path: Path) -> None:
    runner._PENDING_CURSOR_BY_ROOT.clear()
    names = ["a", "b", "c"]
    assert runner._select_batch_names(names, tmp_path, 2) == ["a", "b"]
    assert runner._select_batch_names(names, tmp_path, 2) == ["c", "a"]
    assert runner._select_batch_names(names, tmp_path, 2) == ["b", "c"]


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


def test_record_ledger_outcomes_records_stale_and_mapped(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_load_exit_codes_by_key", lambda _root: {"m1": 1, "m2": None})
    seen: dict[str, object] = {}

    def _append(outcomes: dict[str, str], context: str, project_root: Path) -> None:
        seen["outcomes"] = outcomes
        seen["context"] = context
        seen["project_root"] = project_root

    monkeypatch.setattr(runner, "append_ledger_event", _append)
    runner._record_ledger_outcomes(tmp_path, ["m1", "m2"], stale_names={"m2"}, context="ctx")
    assert seen["outcomes"] == {"m1": "killed", "m2": "stale"}
    assert seen["context"] == "ctx"


def test_record_ledger_outcomes_empty_names_noop(monkeypatch, tmp_path: Path) -> None:
    called = {"append": False}
    monkeypatch.setattr(
        runner, "_load_exit_codes_by_key", lambda _root: (_ for _ in ()).throw(AssertionError("unused"))
    )
    monkeypatch.setattr(
        runner,
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
    monkeypatch.setattr(runner, "_load_exit_codes_by_key", lambda _root: {name: None})
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        runner,
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
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: ["m1", "m2"])
    campaign = runner._init_or_load_strict_campaign(tmp_path)
    assert campaign == {"names": ["m1", "m2"], "stale": [], "attempted": []}
    assert (tmp_path / runner.STRICT_CAMPAIGN_FILE).exists()


def test_init_or_load_strict_campaign_handles_invalid_file(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / runner.STRICT_CAMPAIGN_FILE).write_text("{")
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: ["x"])
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
    monkeypatch.setattr(runner, "_load_exit_codes_by_key", lambda _root: {"m1": None, "m2": 1, "m3": None})
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
    class Dummy:
        returncode = 0

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: Dummy())
    err = runner._dependency_preflight(tmp_path, ["/venv/python", "-m", "mutmut"])
    assert err is None


def test_dependency_preflight_fail(monkeypatch, tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text("from pymutant import main")

    class Dummy:
        returncode = 1

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: Dummy())
    err = runner._dependency_preflight(tmp_path, ["/venv/python", "-m", "mutmut"])
    assert err is not None
    assert "uv sync" in err


def test_dependency_preflight_non_module_cmd(tmp_path: Path) -> None:
    assert runner._dependency_preflight(tmp_path, ["mutmut"]) is None


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


def test_run_mutations_success(monkeypatch, tmp_path: Path) -> None:
    py = tmp_path / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("")

    class RunOK:
        returncode = 0

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: RunOK())
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([("killed 2", "")], returncode=0))
    out = runner.run_mutations(paths=["src/mod.py"], max_children=2, project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["summary"] == "killed 2"
    assert out["batched"] is False


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
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([], timeout_always=True))
    monkeypatch.setattr(runner, "MUTMUT_TIMEOUT", 0)
    called = {"k": False}
    monkeypatch.setattr(runner, "_terminate_process_tree", lambda _proc: called.__setitem__("k", True))
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == -1
    assert "timed out" in out["stderr"]
    assert called["k"] is True


def test_run_mutations_no_progress_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: _FakePopen([], timeout_always=True))
    monkeypatch.setattr(runner, "MUTMUT_TIMEOUT", 1000)
    monkeypatch.setattr(runner, "MUTMUT_NO_PROGRESS_TIMEOUT", 0)
    monkeypatch.setattr(runner, "_terminate_process_tree", lambda _proc: None)
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == -1
    assert "stalled" in out["stderr"]


def test_run_mutations_loop_continues_until_output(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen([("progress", ""), ("done killed", "")], returncode=0),
    )
    monkeypatch.setattr(runner, "MUTMUT_TIMEOUT", 1000)
    monkeypatch.setattr(runner, "MUTMUT_NO_PROGRESS_TIMEOUT", 1000)
    out = runner.run_mutations(project_root=tmp_path)
    assert out["returncode"] == 0
    assert "killed" in out["summary"]


def test_run_mutations_batches_pending_not_checked(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 2)
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: ["m1", "m2", "m3"])

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
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 2)
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: ["m1", "m2", "m3"])

    calls = {"n": 0}

    def fake_exit_codes(_root: Path) -> dict[str, int | None]:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"m1": None, "m2": None, "m3": None}
        return {"m1": 1, "m2": 0, "m3": None}

    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return _FakePopen([("done", "")], returncode=0)

    monkeypatch.setattr(runner, "_load_exit_codes_by_key", fake_exit_codes)
    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "m1", "m2", "--max-children", "2"]
    assert out["strict_campaign"] is True
    assert out["campaign_total"] == 3
    assert out["campaign_attempted"] == 2
    assert out["remaining_not_checked"] == 1


def test_run_mutations_strict_campaign_marks_stale_and_continues(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 1)
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: ["m1"])
    monkeypatch.setattr(runner, "_load_exit_codes_by_key", lambda _root: {"m1": None})
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


def test_run_mutations_strict_campaign_marks_stale_with_empty_stderr(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 1)
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: ["m1"])
    monkeypatch.setattr(runner, "_load_exit_codes_by_key", lambda _root: {"m1": None})
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *a, **k: _FakePopen([("", "Filtered for specific mutants, but nothing matches")], returncode=1),
    )
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert (
        out["stderr"]
        == "Filtered for specific mutants, but nothing matches\nMarked stale selectors and continuing strict campaign."
    )


def test_run_mutations_strict_campaign_no_pending_is_noop(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: [])
    monkeypatch.setattr(runner, "_run_cmd", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not run cmd")))
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert out["summary"] == "strict campaign complete; nothing to run"
    assert out["strict_campaign"] is True
    assert out["campaign_total"] == 0
    assert out["campaign_attempted"] == 0
    assert out["remaining_not_checked"] == 0


def test_run_mutations_strict_campaign_ignored_with_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)

    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return _FakePopen([("done", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    out = runner.run_mutations(paths=["src/x.py"], strict_campaign=True, project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "src/x.py"]
    assert out["strict_campaign"] is False


def test_run_mutations_paths_mutant_selectors_record_ledger(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
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

    monkeypatch.setattr(runner, "_record_ledger_outcomes", _record)
    out = runner.run_mutations(paths=["m.a__mutmut_1"], strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == 0
    assert seen["names"] == ["m.a__mutmut_1"]
    assert seen["context"] == "explicit_selectors"


def test_run_mutations_strict_campaign_does_not_mark_attempted_on_launch_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 1)
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: ["m1"])
    monkeypatch.setattr(runner, "_load_exit_codes_by_key", lambda _root: {})

    def _raise(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(runner.subprocess, "Popen", _raise)
    out = runner.run_mutations(strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == -1
    assert out["campaign_attempted"] == 0
    assert out["remaining_not_checked"] == 1


def test_run_mutations_batches_pending_respects_explicit_max_children(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 1)
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: ["m1", "m2"])

    seen: dict[str, list[str]] = {}

    def _popen(cmd, **_kwargs):  # type: ignore[no-untyped-def]
        seen["cmd"] = cmd
        return _FakePopen([("killed 1", "")], returncode=0)

    monkeypatch.setattr(runner.subprocess, "Popen", _popen)
    runner.run_mutations(max_children=4, project_root=tmp_path)
    assert seen["cmd"] == ["mutmut", "run", "m1", "--max-children", "4"]


def test_run_mutations_batched_retries_when_filters_stale(monkeypatch, tmp_path: Path) -> None:
    runner._PENDING_CURSOR_BY_ROOT.clear()
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 2)

    names_calls = [["old1", "old2", "old3"], ["new1", "new2", "new3"]]
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

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
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 1)

    names_calls = [["old1"], ["new1"]]
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

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
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 1)

    names_calls = [["old1"], []]
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

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
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 2)

    names_calls = [["old1", "old2"], ["new1", "new2"]]
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

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
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
    monkeypatch.setattr(runner, "_batch_size", lambda: 1)

    names_calls = [["old1"], ["new1"]]
    monkeypatch.setattr(runner, "_load_not_checked_mutants", lambda _root: names_calls.pop(0))

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
    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)

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

    monkeypatch.setattr(runner, "_mutmut_cmd_prefix", lambda _root: ["mutmut"])
    monkeypatch.setattr(runner, "_dependency_preflight", lambda _root, _cmd: None)
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
