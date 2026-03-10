# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

from repo_verify import benchmark


def _assert_quality_payload(payload: dict[str, Any]) -> None:
    assert payload["mode"] == "quality"
    assert payload["schema_version"] == "1.0"
    assert "generated_at" in payload
    assert isinstance(payload["batch_size"], int)
    assert isinstance(payload["max_children"], int)
    assert isinstance(payload["iterations"], int)
    assert isinstance(payload["duration_seconds"], float)
    assert isinstance(payload["last_run"], dict)
    assert isinstance(payload["ledger"], dict)
    assert isinstance(payload["score"], dict)
    assert isinstance(payload["counts"], dict)
    assert isinstance(payload["interruptions"], list)
    assert isinstance(payload["checked_mutants"], int)
    assert isinstance(payload["execution"], dict)
    assert isinstance(payload["profile"], dict)
    assert isinstance(payload["policy"], dict)
    assert isinstance(payload["trend"], dict)


def _assert_throughput_payload(payload: dict[str, Any]) -> None:
    assert payload["mode"] == "throughput"
    assert payload["schema_version"] == "1.0"
    assert "generated_at" in payload
    assert isinstance(payload["batch_size"], int)
    assert isinstance(payload["max_children"], int)
    assert isinstance(payload["first_call_seconds"], float)
    assert isinstance(payload["noop_call_seconds"], float)
    assert isinstance(payload["total_seconds"], float)
    assert isinstance(payload["first_call"], dict)
    assert isinstance(payload["noop_call"], dict)
    assert isinstance(payload["profile"], dict)


def test_quality_benchmark_payload_contract(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(
        benchmark.runner,
        "run_mutations",
        lambda **_kwargs: {"returncode": 0, "remaining_not_checked": 0, "campaign_total": 5, "strict_campaign": True},
    )
    monkeypatch.setattr(benchmark.ledger, "ledger_status", lambda **_kwargs: {"exists": True})
    monkeypatch.setattr(benchmark.score, "compute_score", lambda **_kwargs: {"score": 0.75, "total": 20, "not_checked": 5})
    monkeypatch.setattr(benchmark.results, "get_results", lambda **_kwargs: {"counts": {"timeout": 0, "segfault": 0}})

    payload, failures = benchmark.run_quality_benchmark(
        project_root=tmp_path,
        batch_size=10,
        max_children=1,
        max_iterations=10,
        score_floor=0.1,
        max_timeout=1,
        max_segfault=1,
        max_duration_seconds=999.0,
        min_checked_mutants=1,
    )

    assert failures == []
    _assert_quality_payload(payload)


def test_throughput_benchmark_payload_contract(monkeypatch, tmp_path: Path) -> None:
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

    ticks = iter([0.0, 0.0, 0.5, 0.5, 0.7, 0.7])
    monkeypatch.setattr(benchmark.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(benchmark.runner, "reset_strict_campaign", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.ledger, "reset_ledger", lambda **_kwargs: True)
    monkeypatch.setattr(benchmark.runner, "run_mutations", fake_run_mutations)

    payload, failures = benchmark.run_throughput_benchmark(
        project_root=tmp_path,
        batch_size=5,
        max_children=1,
        max_first_call_seconds=2.0,
        max_noop_call_seconds=2.0,
        max_total_seconds=3.0,
    )

    assert failures == []
    _assert_throughput_payload(payload)
