# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from repo_verify import benchmark


def test_run_quality_benchmark_cold_start_interruption_exhausts_retries(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake_run_mutations(**kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return {"returncode": 0, "remaining_not_checked": 0, "campaign_total": 0}
        assert kwargs["strict_campaign"] is False
        if calls["n"] <= 4:
            return {"returncode": -15, "summary": "Running mutation testing", "campaign_total": 10}
        return {"returncode": 0, "remaining_not_checked": 0, "campaign_total": 10}

    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)
    monkeypatch.setattr(benchmark.runner, "kill_stuck_mutmut", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {})
    monkeypatch.setattr(
        benchmark.score,
        "compute_score",
        lambda **_kwargs: {"score": 1.0, "total": 10, "not_checked": 1, "killed": 1, "survived": 1},
    )
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
    assert len(metrics["interruptions"]) == 2
