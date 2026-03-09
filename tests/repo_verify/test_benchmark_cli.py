# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_verify import benchmark


def test_load_json_variants(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    assert benchmark._load_json(p) == {}
    p.write_text("{")
    assert benchmark._load_json(p) == {}
    p.write_text("[]")
    assert benchmark._load_json(p) == {}
    p.write_text('{"a":1}')
    assert benchmark._load_json(p) == {"a": 1}


def test_write_json_none_and_path(tmp_path: Path) -> None:
    benchmark._write_json(None, {"a": 1})
    out = tmp_path / "dir" / "out.json"
    benchmark._write_json(out, {"a": 1})
    payload = json.loads(out.read_text())
    assert payload["a"] == 1
    assert payload["schema_version"] == "1.0"
    assert "generated_at" in payload


def test_batch_size_env_restore(monkeypatch) -> None:
    monkeypatch.delenv("PYMUTANT_BATCH_SIZE", raising=False)
    prev = benchmark._set_batch_size(11)
    assert prev is None
    assert benchmark.os.environ["PYMUTANT_BATCH_SIZE"] == "11"
    benchmark._restore_batch_size(prev)
    assert "PYMUTANT_BATCH_SIZE" not in benchmark.os.environ

    monkeypatch.setenv("PYMUTANT_BATCH_SIZE", "9")
    prev2 = benchmark._set_batch_size(12)
    assert prev2 == "9"
    benchmark._restore_batch_size(prev2)
    assert benchmark.os.environ["PYMUTANT_BATCH_SIZE"] == "9"


def test_run_quality_benchmark_pass(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_run_mutations(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {"returncode": 0, "remaining_not_checked": 1, "campaign_total": 10}
        return {"returncode": 0, "remaining_not_checked": 0, "campaign_total": 10}

    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {"counts": {}, "exists": True})
    monkeypatch.setattr(
        benchmark.score,
        "compute_score",
        lambda **_kwargs: {"score": 0.5},
    )
    monkeypatch.setattr(
        benchmark.results,
        "get_results",
        lambda **_kwargs: {"counts": {"timeout": 1, "segfault": 2}},
    )

    metrics, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=7,
        max_children=1,
        max_iterations=10,
        score_floor=0.3,
        max_timeout=3,
        max_segfault=4,
        max_duration_seconds=999.0,
        min_checked_mutants=0,
    )
    assert failures == []
    assert metrics["iterations"] == 2
    assert metrics["last_run"]["remaining_not_checked"] == 0
    assert metrics["batch_size"] == 7
    assert metrics["interruptions"] == []


def test_run_quality_benchmark_recovers_from_interruptions(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_run_mutations(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] <= 2:
            return {"returncode": -15, "summary": "Running mutation testing"}
        return {"returncode": 0, "remaining_not_checked": 0, "campaign_total": 5}

    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)
    monkeypatch.setattr(
        benchmark.runner,
        "kill_stuck_mutmut",
        lambda **_kwargs: {"ok": True, "killed_any": True},
    )
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {})
    monkeypatch.setattr(benchmark.score, "compute_score", lambda **_kwargs: {"score": 1.0})
    monkeypatch.setattr(benchmark.results, "get_results", lambda **_kwargs: {"counts": {}})

    metrics, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=10,
        max_children=1,
        max_iterations=10,
        score_floor=0.5,
        max_timeout=0,
        max_segfault=0,
        max_duration_seconds=999.0,
        min_checked_mutants=0,
    )
    assert failures == []
    assert len(metrics["interruptions"]) == 2
    assert metrics["interruptions"][0]["returncode"] == -15


def test_run_quality_benchmark_cold_start_unfiltered(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_run_mutations(**kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "returncode": 0,
                "remaining_not_checked": 0,
                "campaign_total": 0,
            }
        assert kwargs["strict_campaign"] is False
        return {
            "returncode": 0,
            "remaining_not_checked": 0,
            "campaign_total": 10,
        }

    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {})
    monkeypatch.setattr(benchmark.score, "compute_score", lambda **_kwargs: {"score": 0.5})
    monkeypatch.setattr(benchmark.results, "get_results", lambda **_kwargs: {"counts": {}})

    metrics, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=7,
        max_children=1,
        max_iterations=10,
        score_floor=0.3,
        max_timeout=3,
        max_segfault=4,
        max_duration_seconds=999.0,
        min_checked_mutants=0,
    )
    assert failures == []
    assert metrics["iterations"] == 2


def test_run_quality_benchmark_cold_start_interruption_retry(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_run_mutations(**kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {"returncode": 0, "remaining_not_checked": 0, "campaign_total": 0}
        if calls["n"] == 2:
            assert kwargs["strict_campaign"] is False
            return {"returncode": -15, "summary": "Running mutation testing", "campaign_total": 10}
        assert kwargs["strict_campaign"] is False
        return {"returncode": 0, "remaining_not_checked": 0, "campaign_total": 10}

    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)
    monkeypatch.setattr(benchmark.runner, "kill_stuck_mutmut", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {})
    monkeypatch.setattr(benchmark.score, "compute_score", lambda **_kwargs: {"score": 1.0})
    monkeypatch.setattr(benchmark.results, "get_results", lambda **_kwargs: {"counts": {}})

    metrics, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=7,
        max_children=1,
        max_iterations=10,
        score_floor=0.3,
        max_timeout=3,
        max_segfault=4,
        max_duration_seconds=999.0,
        min_checked_mutants=0,
    )
    assert failures == []
    assert metrics["iterations"] == 3
    assert len(metrics["interruptions"]) == 1


def test_run_quality_benchmark_collects_failures(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(
        benchmark.runner,
        "run_mutations",
        lambda **_kwargs: {"returncode": 2, "remaining_not_checked": 3, "strict_campaign": True},
    )
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {})
    monkeypatch.setattr(benchmark.score, "compute_score", lambda **_kwargs: {"score": 0.1})
    monkeypatch.setattr(
        benchmark.results,
        "get_results",
        lambda **_kwargs: {"counts": {"timeout": 10, "segfault": 20}},
    )
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: 1000.0)

    _metrics, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=5,
        max_children=1,
        max_iterations=1,
        score_floor=0.2,
        max_timeout=1,
        max_segfault=1,
        max_duration_seconds=0.1,
        min_checked_mutants=0,
    )
    assert any("nonzero returncode" in item for item in failures)
    assert any("campaign incomplete" in item for item in failures)
    assert any("hit max_iterations" in item for item in failures)
    assert any("score below floor" in item for item in failures)
    assert any("timeout budget exceeded" in item for item in failures)
    assert any("segfault budget exceeded" in item for item in failures)


def test_run_quality_benchmark_interrupted_with_progress_not_failure(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_run_mutations(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return {"returncode": -15, "summary": "Running mutation testing", "campaign_total": 10}

    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)
    monkeypatch.setattr(benchmark.runner, "kill_stuck_mutmut", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {})
    monkeypatch.setattr(
        benchmark.score,
        "compute_score",
        lambda **_kwargs: {"score": 0.8, "total": 10, "not_checked": 1},
    )
    monkeypatch.setattr(benchmark.results, "get_results", lambda **_kwargs: {"counts": {}})

    metrics, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=10,
        max_children=1,
        max_iterations=10,
        score_floor=0.1,
        max_timeout=10,
        max_segfault=10,
        max_duration_seconds=999.0,
        min_checked_mutants=1,
    )
    assert not any("nonzero returncode" in item for item in failures)
    assert any(item.get("reason") == "interrupted_with_progress" for item in metrics["interruptions"])


def test_run_quality_benchmark_iteration_and_duration_failures(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(
        benchmark.runner,
        "run_mutations",
        lambda **_kwargs: {"returncode": 0, "remaining_not_checked": 1},
    )
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {})
    monkeypatch.setattr(benchmark.score, "compute_score", lambda **_kwargs: {"score": 1.0})
    monkeypatch.setattr(benchmark.results, "get_results", lambda **_kwargs: {"counts": {}})
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: next(ticks))

    _metrics, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=5,
        max_children=1,
        max_iterations=1,
        score_floor=0.1,
        max_timeout=10,
        max_segfault=10,
        max_duration_seconds=0.5,
        min_checked_mutants=0,
    )
    assert any("hit max_iterations=1" in item for item in failures)
    assert any("duration budget exceeded" in item for item in failures)


def test_run_quality_benchmark_checked_mutant_floor(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(
        benchmark.runner,
        "run_mutations",
        lambda **_kwargs: {"returncode": 0, "remaining_not_checked": 0, "campaign_total": 10},
    )
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {})
    monkeypatch.setattr(
        benchmark.score, "compute_score", lambda **_kwargs: {"score": 1.0, "total": 0, "not_checked": 0}
    )
    monkeypatch.setattr(benchmark.results, "get_results", lambda **_kwargs: {"counts": {}})

    _metrics, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=5,
        max_children=1,
        max_iterations=5,
        score_floor=0.0,
        max_timeout=10,
        max_segfault=10,
        max_duration_seconds=999.0,
        min_checked_mutants=1,
    )
    assert any("checked mutants below floor" in item for item in failures)


def test_run_throughput_benchmark_pass(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_run_mutations(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {"returncode": 0, "campaign_stale": 1}
        return {
            "returncode": 0,
            "batch_size": 0,
            "remaining_not_checked": 0,
            "summary": "strict campaign complete; nothing to run",
        }

    ticks = iter([0.0, 0.0, 0.2, 0.2, 0.25, 0.25])
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)

    metrics, failures = benchmark.run_throughput_benchmark(
        project_root=tmp_path,
        batch_size=5,
        max_children=1,
        max_first_call_seconds=1.0,
        max_noop_call_seconds=1.0,
        max_total_seconds=2.0,
    )
    assert failures == []
    assert metrics["first_call_seconds"] == 0.2
    assert metrics["noop_call_seconds"] == 0.05


def test_run_throughput_benchmark_failures(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_run_mutations(**_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {"returncode": 1, "campaign_stale": 0}
        return {"returncode": 2, "batch_size": 1, "remaining_not_checked": 1, "summary": "x"}

    ticks = iter([0.0, 0.0, 10.0, 10.0, 20.0, 20.0])
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)

    _metrics, failures = benchmark.run_throughput_benchmark(
        project_root=tmp_path,
        batch_size=5,
        max_children=1,
        max_first_call_seconds=1.0,
        max_noop_call_seconds=1.0,
        max_total_seconds=5.0,
    )
    assert any("first strict run failed" in item for item in failures)
    assert any("did not mark stale" in item for item in failures)
    assert any("noop strict run failed" in item for item in failures)
    assert any("was not no-op" in item for item in failures)
    assert any("unexpectedly has remaining_not_checked" in item for item in failures)
    assert any("unexpected noop summary" in item for item in failures)
    assert any("first call too slow" in item for item in failures)
    assert any("noop call too slow" in item for item in failures)
    assert any("total runtime too slow" in item for item in failures)


def test_print_failures(capsys) -> None:
    benchmark._print_failures("quality", [])
    out = capsys.readouterr()
    assert "quality benchmark passed" in out.out

    benchmark._print_failures("quality", ["x"])
    out2 = capsys.readouterr()
    assert "quality benchmark failure: x" in out2.err


def test_main_quality_and_throughput(monkeypatch, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "quality": {"batch_size": 1, "max_children": 1, "max_iterations": 2, "min_score": 0.0},
                "throughput": {"batch_size": 1, "max_children": 1},
            }
        )
    )

    monkeypatch.setattr(benchmark, "run_quality_benchmark", lambda **_kwargs: ({"m": "q"}, []))
    out_q = tmp_path / "q.json"
    benchmark.main(["quality", "--project-root", str(tmp_path), "--baseline", str(baseline), "--json-out", str(out_q)])
    q_payload = json.loads(out_q.read_text())
    assert q_payload["m"] == "q"
    assert q_payload["schema_version"] == "1.0"

    monkeypatch.setattr(benchmark, "run_throughput_benchmark", lambda **_kwargs: ({"m": "t"}, []))
    out_t = tmp_path / "t.json"
    benchmark.main(
        ["throughput", "--project-root", str(tmp_path), "--baseline", str(baseline), "--json-out", str(out_t)]
    )
    t_payload = json.loads(out_t.read_text())
    assert t_payload["m"] == "t"
    assert t_payload["schema_version"] == "1.0"


def test_main_exits_on_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(benchmark, "run_quality_benchmark", lambda **_kwargs: ({"m": "q"}, ["bad"]))
    with pytest.raises(SystemExit) as exc:
        benchmark.main(["quality", "--project-root", str(tmp_path)])
    assert exc.value.code == 1
