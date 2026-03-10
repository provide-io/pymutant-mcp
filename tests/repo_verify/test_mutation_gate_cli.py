# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_verify import mutation_gate


def test_chunks() -> None:
    assert mutation_gate._chunks([], 10) == []
    assert mutation_gate._chunks(["a", "b", "c"], 2) == [["a", "b"], ["c"]]
    assert mutation_gate._chunks(["a"], 0) == [["a"]]


def test_write_json(tmp_path: Path) -> None:
    out = tmp_path / "x" / "payload.json"
    mutation_gate._write_json(out, {"a": 1})
    payload = json.loads(out.read_text())
    assert payload["a"] == 1
    assert payload["schema_version"] == "1.0"


def test_survivor_names(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mutation_gate.results,
        "get_results",
        lambda **_kwargs: {
            "mutants": [
                {"name": "b", "status": "survived"},
                {"name": "a", "status": "survived"},
                {"name": "k", "status": "killed"},
            ]
        },
    )
    assert mutation_gate._survivor_names(tmp_path) == ["a", "b"]


def test_run_mutation_gate_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: True)

    calls = {"n": 0}

    def fake_survivors(_root: Path) -> list[str]:
        calls["n"] += 1
        if calls["n"] == 1:
            return ["m1", "m2"]
        return []

    monkeypatch.setattr(mutation_gate, "_survivor_names", fake_survivors)
    monkeypatch.setattr(
        mutation_gate.runner,
        "run_mutations",
        lambda **_kwargs: {"returncode": 0, "summary": "ok"},
    )

    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=10,
        max_rounds=3,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=True,
    )
    assert failures == []
    assert payload["final_survivors"] == 0
    assert payload["rounds"][0]["survivors_before"] == 2
    assert payload["execution"]["tooling_error"] is False


def test_run_mutation_gate_seed_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate, "_survivor_names", lambda _root: [])
    monkeypatch.setattr(
        mutation_gate.runner,
        "run_mutations",
        lambda **_kwargs: {"returncode": 3, "summary": "bad"},
    )

    _payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=1,
        max_children=1,
        changed_only=True,
        base_ref="origin/main",
        reset_state=True,
    )
    assert failures == ["tooling_error: seed_run_failed:3"]


def test_run_mutation_gate_interruption_cleanup(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate, "_survivor_names", lambda _root: [])
    calls = {"n": 0}

    def fake_run(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {"returncode": -15, "summary": "run"}
        return {"returncode": 0, "summary": "ok"}

    monkeypatch.setattr(mutation_gate.runner, "run_mutations", fake_run)
    monkeypatch.setattr(mutation_gate.runner, "kill_stuck_mutmut", lambda **_kwargs: {"ok": True})

    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=1,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
    )
    assert failures == []
    assert payload["seed_cleanup"] == {"ok": True}
    assert payload["interruptions"] == 1


def test_run_mutation_gate_no_progress(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    state = {"n": 0}

    def fake_survivors(_root: Path) -> list[str]:
        state["n"] += 1
        if state["n"] == 1:
            return ["m1"]
        return ["m1", "m2"]

    monkeypatch.setattr(mutation_gate, "_survivor_names", fake_survivors)
    monkeypatch.setattr(mutation_gate.runner, "run_mutations", lambda **_kwargs: {"returncode": 0, "summary": "ok"})

    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=2,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
    )
    assert "no progress in round 1: 1 -> 2" in failures
    assert payload["final_survivors"] == 2


def test_run_mutation_gate_zero_rounds(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate, "_survivor_names", lambda _root: ["m1"])
    monkeypatch.setattr(mutation_gate.runner, "run_mutations", lambda **_kwargs: {"returncode": 0, "summary": "ok"})
    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=0,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
    )
    assert payload["rounds"] == []
    assert failures == ["survivors remain: 1"]


def test_run_mutation_gate_batch_interruption(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)

    state = {"n": 0}

    def fake_survivors(_root: Path) -> list[str]:
        state["n"] += 1
        if state["n"] == 1:
            return ["m1"]
        return []

    monkeypatch.setattr(mutation_gate, "_survivor_names", fake_survivors)

    calls = {"n": 0}

    def fake_run(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {"returncode": 0, "summary": "seed"}
        if calls["n"] == 2:
            return {"returncode": -15, "summary": "batch"}
        return {"returncode": 0, "summary": "batch-ok"}

    monkeypatch.setattr(mutation_gate.runner, "run_mutations", fake_run)
    monkeypatch.setattr(mutation_gate.runner, "kill_stuck_mutmut", lambda **_kwargs: {"ok": True})

    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=3,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
    )
    assert failures == []
    batch = payload["rounds"][0]["batches"][0]
    assert batch["cleanup"] == {"ok": True}
    assert payload["interruptions"] == 1


def test_run_mutation_gate_seed_interrupted_beyond_budget(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate, "_survivor_names", lambda _root: [])
    monkeypatch.setattr(mutation_gate.runner, "run_mutations", lambda **_kwargs: {"returncode": -15, "summary": "run"})
    monkeypatch.setattr(mutation_gate.runner, "kill_stuck_mutmut", lambda **_kwargs: {"ok": True})

    _payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=1,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
        max_interruptions=0,
    )
    assert failures == ["tooling_error: seed_run_interrupted_beyond_retry_budget"]


def test_run_mutation_gate_time_budget_before_round(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate.runner, "run_mutations", lambda **_kwargs: {"returncode": 0, "summary": "ok"})
    monkeypatch.setattr(mutation_gate, "_survivor_names", lambda _root: ["m1"])
    times = iter([0.0, 2.0, 2.0])
    monkeypatch.setattr(mutation_gate.time, "monotonic", lambda: next(times))
    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=1,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
        max_seconds=1.0,
    )
    assert payload["rounds"] == []
    assert failures == ["time budget exceeded before round 1: 1.0s", "survivors remain: 1"]


def test_run_mutation_gate_time_budget_in_round(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate.runner, "run_mutations", lambda **_kwargs: {"returncode": 0, "summary": "ok"})

    state = {"n": 0}

    def fake_survivors(_root: Path) -> list[str]:
        state["n"] += 1
        if state["n"] == 1:
            return ["m1"]
        return []

    monkeypatch.setattr(mutation_gate, "_survivor_names", fake_survivors)
    times = iter([0.0, 0.0, 2.0, 2.0, 2.0])
    monkeypatch.setattr(mutation_gate.time, "monotonic", lambda: next(times))
    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=2,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
        max_seconds=1.0,
    )
    assert payload["rounds"][0]["survivors_after"] == 0
    assert failures == ["time budget exceeded in round 1: 1.0s"]


def test_run_mutation_gate_batch_interrupted_beyond_budget(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate.runner, "kill_stuck_mutmut", lambda **_kwargs: {"ok": True})

    state = {"n": 0}

    def fake_survivors(_root: Path) -> list[str]:
        state["n"] += 1
        if state["n"] == 1:
            return ["m1"]
        return []

    monkeypatch.setattr(mutation_gate, "_survivor_names", fake_survivors)

    calls = {"n": 0}

    def fake_run(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {"returncode": 0, "summary": "seed"}
        return {"returncode": -15, "summary": "batch"}

    monkeypatch.setattr(mutation_gate.runner, "run_mutations", fake_run)
    _payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=1,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
        max_interruptions=0,
    )
    assert failures == ["tooling_error: batch_interruption_beyond_retry_budget:round_1"]


def test_run_mutation_gate_repeated_survivor_set(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate.runner, "run_mutations", lambda **_kwargs: {"returncode": 0, "summary": "ok"})
    state = {"n": 0}

    def fake_survivors(_root: Path) -> list[str]:
        state["n"] += 1
        if state["n"] == 1:
            return ["a", "b"]
        if state["n"] == 2:
            return ["a"]
        return ["a", "b"]

    monkeypatch.setattr(mutation_gate, "_survivor_names", fake_survivors)
    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=3,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
    )
    assert "survivor set repeated before round 2: 2" in failures
    assert payload["rounds"][0]["survivors_after"] == 1


def test_run_mutation_gate_repeated_survivor_set_after_round(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mutation_gate.runner, "reset_strict_campaign", lambda **_kwargs: False)
    monkeypatch.setattr(mutation_gate.runner, "run_mutations", lambda **_kwargs: {"returncode": 0, "summary": "ok"})
    state = {"n": 0}

    def fake_survivors(_root: Path) -> list[str]:
        state["n"] += 1
        if state["n"] == 1:
            return ["a", "b"]  # round1 before
        if state["n"] == 2:
            return ["x"]  # round1 after
        if state["n"] == 3:
            return ["y"]  # round2 before
        return ["a", "b"]  # round2 after repeats round1-before signature

    monkeypatch.setattr(mutation_gate, "_survivor_names", fake_survivors)
    payload, failures = mutation_gate.run_mutation_gate(
        project_root=tmp_path,
        batch_size=1,
        max_rounds=3,
        max_children=1,
        changed_only=False,
        base_ref=None,
        reset_state=False,
    )
    assert "survivor set repeated in round 2: 2" in failures
    assert payload["rounds"][1]["survivors_after"] == 2


def test_print_failures(capsys) -> None:
    mutation_gate._print_failures(["a", "b"])
    out = capsys.readouterr().out
    assert "mutation gate failure: a" in out
    assert "mutation gate failure: b" in out


def test_main_success(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / "gate.json"
    monkeypatch.setattr(
        mutation_gate,
        "run_mutation_gate",
        lambda **_kwargs: ({"final_survivors": 0}, []),
    )
    mutation_gate.main(["--project-root", str(tmp_path), "--json-out", str(out), "--changed-only", "--base-ref", "origin/main"])
    payload = json.loads(out.read_text())
    assert payload["final_survivors"] == 0


def test_main_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mutation_gate,
        "run_mutation_gate",
        lambda **_kwargs: ({"final_survivors": 1}, ["bad"]),
    )
    with pytest.raises(SystemExit) as exc:
        mutation_gate.main(["--project-root", str(tmp_path), "--no-reset"])
    assert exc.value.code == 1
