# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from repo_verify import benchmark, mutation_gate


def test_benchmark_artifact_safe_run_result_suppresses_success_stdout() -> None:
    compact = benchmark._artifact_safe_run_result(
        {"returncode": 0, "summary": "ok", "stdout": "very noisy progress", "stderr": ""}
    )
    assert compact["summary"] == "ok"
    assert compact["stdout_suppressed"] is True
    assert "stdout_preview" not in compact
    assert "stdout" not in compact


def test_benchmark_artifact_safe_run_result_keeps_failure_previews() -> None:
    compact = benchmark._artifact_safe_run_result(
        {"returncode": 1, "summary": "", "stdout": "x" * 450, "stderr": "bad stderr"}
    )
    assert compact["stdout_preview"].startswith("x" * 50)
    assert "truncated" in compact["stdout_preview"]
    assert compact["stderr_preview"] == "bad stderr"


def test_mutation_gate_artifact_safe_run_result_suppresses_success_stdout() -> None:
    compact = mutation_gate._artifact_safe_run_result(
        {"returncode": 0, "summary": "ok", "stdout": "very noisy progress", "stderr": ""}
    )
    assert compact["summary"] == "ok"
    assert compact["stdout_suppressed"] is True
    assert "stdout" not in compact
    assert "stdout_preview" not in compact


def test_mutation_gate_artifact_safe_run_result_keeps_failure_previews() -> None:
    compact = mutation_gate._artifact_safe_run_result(
        {"returncode": 2, "summary": "", "stdout": "x" * 450, "stderr": "bad stderr"}
    )
    assert compact["stdout_preview"].startswith("x" * 50)
    assert "truncated" in compact["stdout_preview"]
    assert compact["stderr_preview"] == "bad stderr"
