# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from pymutant import ledger, results, runner, score
from pymutant.config import restore_env_batch_size, set_env_batch_size
from pymutant.policy import evaluate_policy
from pymutant.profiles import resolve_profile
from pymutant.schema import with_schema
from pymutant.trends import trend_report

ARTIFACT_OUTPUT_CHARS = 400


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(with_schema(payload), indent=2) + "\n")


def _preview_output(text: str, *, limit: int = ARTIFACT_OUTPUT_CHARS) -> str:
    compact = text.strip()
    if len(compact) <= limit:
        return compact
    omitted = len(compact) - limit
    return f"{compact[:limit]}\n\n[artifact output truncated: omitted {omitted} characters]"


def _artifact_safe_run_result(result: dict[str, Any]) -> dict[str, Any]:
    artifact = {key: value for key, value in result.items() if key not in {"stdout", "stderr"}}
    summary = str(result.get("summary", "") or "").strip()
    stdout = str(result.get("stdout", "") or "")
    stderr = str(result.get("stderr", "") or "")
    returncode = int(result.get("returncode", 0))

    if stderr.strip():
        artifact["stderr_preview"] = _preview_output(stderr)
    if stdout.strip() and (returncode != 0 or not summary):
        artifact["stdout_preview"] = _preview_output(stdout)
    if stdout.strip() and returncode == 0 and summary:
        artifact["stdout_suppressed"] = True
    return artifact


def _record_interruption(
    interruptions: list[dict[str, Any]],
    *,
    result: dict[str, Any],
    cleanup: dict[str, Any],
) -> None:
    interruptions.append(
        {
            "returncode": int(result.get("returncode", -1)),
            "summary": str(result.get("summary", "")),
            "cleanup": cleanup,
        }
    )


def _run_with_retries(
    *,
    project_root: Path,
    max_children: int,
    strict_campaign: bool,
    retries_remaining: int,
    interruptions: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    while True:
        last_run = runner.run_mutations(
            max_children=max_children,
            strict_campaign=strict_campaign,
            project_root=project_root,
        )
        returncode = int(last_run.get("returncode", -1))
        if returncode not in {-15, -9} or retries_remaining <= 0:
            return last_run, retries_remaining
        cleanup = runner.kill_stuck_mutmut(project_root=project_root)
        _record_interruption(interruptions, result=last_run, cleanup=cleanup)
        retries_remaining -= 1


def _mark_interrupted_with_progress(
    *,
    last_run: dict[str, Any],
    checked_mutants: int,
    interruptions: list[dict[str, Any]],
) -> bool:
    interrupted_with_progress = (
        int(last_run.get("returncode", -1)) in {-15, -9}
        and str(last_run.get("summary", "")).strip() == "Running mutation testing"
        and checked_mutants > 0
    )
    if interrupted_with_progress:
        interruptions.append(
            {
                "returncode": int(last_run.get("returncode", -1)),
                "summary": str(last_run.get("summary", "")),
                "reason": "interrupted_with_progress",
                "checked_mutants": checked_mutants,
            }
        )
    return interrupted_with_progress


def _execution_reasons(
    *,
    last_run: dict[str, Any],
    interrupted_with_progress: bool,
    checked_mutants: int,
    min_checked_mutants: int,
    killed: int,
    survived: int,
    timeouts: int,
    segfaults: int,
    quality_signal_known: bool,
) -> list[str]:
    reasons: list[str] = []
    if int(last_run.get("returncode", -1)) != 0 and not interrupted_with_progress:
        reasons.append(f"nonzero_returncode:{last_run.get('returncode')}")
    if checked_mutants == 0 and min_checked_mutants > 0:
        reasons.append("no_mutants_checked")
    if quality_signal_known and (timeouts + segfaults) > 0 and (killed + survived) == 0:
        reasons.append("unstable_run_without_quality_signal")
    return reasons


def _quality_metrics(
    *,
    project_root: Path,
    batch_size: int,
    max_children: int,
    iterations: int,
    duration_seconds: float,
    last_run: dict[str, Any],
    ledger_status: dict[str, Any],
    score_data: dict[str, Any],
    counts: dict[str, Any],
    interruptions: list[dict[str, Any]],
    checked_mutants: int,
    execution_reasons: list[str],
    interrupted_with_progress: bool,
    history: dict[str, Any],
) -> dict[str, Any]:
    return with_schema(
        {
            "mode": "quality",
            "batch_size": batch_size,
            "max_children": max_children,
            "iterations": iterations,
            "duration_seconds": duration_seconds,
            "last_run": _artifact_safe_run_result(last_run),
            "ledger": ledger_status,
            "score": score_data,
            "counts": counts,
            "interruptions": interruptions,
            "checked_mutants": checked_mutants,
            "execution": {
                "status": "tooling_error" if execution_reasons else "ok",
                "tooling_error": bool(execution_reasons),
                "reasons": execution_reasons,
                "interrupted_with_progress": interrupted_with_progress,
            },
            "profile": resolve_profile(project_root=project_root),
            "policy": evaluate_policy(current_score=float(score_data["score"]), project_root=project_root),
            "trend": trend_report(history),
        }
    )


def _quality_failures(
    *,
    last_run: dict[str, Any],
    iterations: int,
    max_iterations: int,
    execution_reasons: list[str],
    score_data: dict[str, Any],
    score_floor: float,
    timeouts: int,
    max_timeout: int,
    segfaults: int,
    max_segfault: int,
    duration_seconds: float,
    max_duration_seconds: float,
    checked_mutants: int,
    min_checked_mutants: int,
) -> list[str]:
    failures: list[str] = []
    if execution_reasons:
        failures.append(f"tooling_error: {';'.join(execution_reasons)}")
    if bool(last_run.get("strict_campaign")) and int(last_run.get("remaining_not_checked", -1)) != 0:
        failures.append(f"campaign incomplete: remaining_not_checked={last_run.get('remaining_not_checked')}")
    if iterations >= max_iterations:
        failures.append(f"hit max_iterations={max_iterations}")
    if not execution_reasons and float(score_data["score"]) < score_floor:
        failures.append(f"score below floor: {score_data['score']} < {score_floor}")
    if timeouts > max_timeout:
        failures.append(f"timeout budget exceeded: {timeouts} > {max_timeout}")
    if segfaults > max_segfault:
        failures.append(f"segfault budget exceeded: {segfaults} > {max_segfault}")
    if duration_seconds > max_duration_seconds:
        failures.append(f"duration budget exceeded: {duration_seconds} > {max_duration_seconds}")
    if not execution_reasons and checked_mutants < min_checked_mutants:
        failures.append(f"checked mutants below floor: {checked_mutants} < {min_checked_mutants}")
    return failures


def _set_batch_size(batch_size: int) -> str | None:
    return set_env_batch_size(batch_size)


def _restore_batch_size(previous: str | None) -> None:
    restore_env_batch_size(previous)


def run_quality_benchmark(
    *,
    project_root: Path,
    batch_size: int,
    max_children: int,
    max_iterations: int,
    score_floor: float,
    max_timeout: int,
    max_segfault: int,
    max_duration_seconds: float,
    min_checked_mutants: int,
) -> tuple[dict[str, Any], list[str]]:
    previous_batch_size = _set_batch_size(batch_size)
    try:
        start = time.monotonic()
        runner.reset_strict_campaign(project_root=project_root)
        ledger.reset_ledger(project_root=project_root)

        iterations = 0
        retries_remaining = 2
        interruptions: list[dict[str, Any]] = []
        last_run: dict[str, Any] = {}
        while True:
            iterations += 1
            last_run, retries_remaining = _run_with_retries(
                project_root=project_root,
                max_children=max_children,
                strict_campaign=True,
                retries_remaining=retries_remaining,
                interruptions=interruptions,
            )
            returncode = int(last_run.get("returncode", -1))
            if returncode != 0:
                break
            if int(last_run.get("remaining_not_checked", 0)) == 0:
                break
            if iterations >= max_iterations:
                break

        # Cold-start safeguard: on fresh checkouts there may be no existing mutmut
        # metadata, yielding an empty strict campaign. Seed with one unfiltered run.
        if int(last_run.get("campaign_total", 0)) == 0:
            iterations += 1
            retries_before_cold_start = retries_remaining
            last_run, retries_remaining = _run_with_retries(
                project_root=project_root,
                max_children=max_children,
                strict_campaign=False,
                retries_remaining=retries_remaining,
                interruptions=interruptions,
            )
            if retries_remaining < retries_before_cold_start:
                iterations += 1
            if int(last_run.get("returncode", -1)) in {-15, -9}:
                last_run = runner.run_mutations(
                    max_children=max_children,
                    strict_campaign=False,
                    project_root=project_root,
                )

        duration_seconds = round(time.monotonic() - start, 3)
        ledger_status = ledger.ledger_status(project_root=project_root)
        score_data = score.compute_score(project_root=project_root)
        counts = results.get_results(include_killed=True, project_root=project_root)["counts"]
        checked_mutants = int(score_data.get("total", 0)) - int(score_data.get("not_checked", 0))
        interrupted_with_progress = _mark_interrupted_with_progress(
            last_run=last_run,
            checked_mutants=checked_mutants,
            interruptions=interruptions,
        )

        history = score.load_score_history(project_root)
        killed = int(score_data.get("killed", 0)) if "killed" in score_data else 0
        survived = int(score_data.get("survived", 0)) if "survived" in score_data else 0
        timeouts = int(counts.get("timeout", 0))
        segfaults = int(counts.get("segfault", 0))
        quality_signal_known = "killed" in score_data and "survived" in score_data

        execution_reasons = _execution_reasons(
            last_run=last_run,
            interrupted_with_progress=interrupted_with_progress,
            checked_mutants=checked_mutants,
            min_checked_mutants=min_checked_mutants,
            killed=killed,
            survived=survived,
            timeouts=timeouts,
            segfaults=segfaults,
            quality_signal_known=quality_signal_known,
        )

        metrics = _quality_metrics(
            project_root=project_root,
            batch_size=batch_size,
            max_children=max_children,
            iterations=iterations,
            duration_seconds=duration_seconds,
            last_run=last_run,
            ledger_status=ledger_status,
            score_data=score_data,
            counts=counts,
            interruptions=interruptions,
            checked_mutants=checked_mutants,
            execution_reasons=execution_reasons,
            interrupted_with_progress=interrupted_with_progress,
            history=history,
        )

        failures = _quality_failures(
            last_run=last_run,
            iterations=iterations,
            max_iterations=max_iterations,
            execution_reasons=execution_reasons,
            score_data=score_data,
            score_floor=score_floor,
            timeouts=timeouts,
            max_timeout=max_timeout,
            segfaults=segfaults,
            max_segfault=max_segfault,
            duration_seconds=duration_seconds,
            max_duration_seconds=max_duration_seconds,
            checked_mutants=checked_mutants,
            min_checked_mutants=min_checked_mutants,
        )
        return metrics, failures
    finally:
        _restore_batch_size(previous_batch_size)


def run_throughput_benchmark(
    *,
    project_root: Path,
    batch_size: int,
    max_children: int,
    max_first_call_seconds: float,
    max_noop_call_seconds: float,
    max_total_seconds: float,
) -> tuple[dict[str, Any], list[str]]:
    previous_batch_size = _set_batch_size(batch_size)
    try:
        runner.reset_strict_campaign(project_root=project_root)
        ledger.reset_ledger(project_root=project_root)

        strict_path = project_root / runner.STRICT_CAMPAIGN_FILE
        strict_path.write_text(
            json.dumps(
                {"names": ["pymutant.__benchmark__mutmut_0"], "stale": [], "attempted": []},
                indent=2,
            )
            + "\n"
        )

        start = time.monotonic()
        first_start = time.monotonic()
        first = runner.run_mutations(max_children=max_children, strict_campaign=True, project_root=project_root)
        first_seconds = round(time.monotonic() - first_start, 3)

        second_start = time.monotonic()
        second = runner.run_mutations(max_children=max_children, strict_campaign=True, project_root=project_root)
        noop_seconds = round(time.monotonic() - second_start, 3)
        total_seconds = round(time.monotonic() - start, 3)

        metrics: dict[str, Any] = with_schema(
            {
            "mode": "throughput",
            "batch_size": batch_size,
            "max_children": max_children,
            "first_call_seconds": first_seconds,
            "noop_call_seconds": noop_seconds,
            "total_seconds": total_seconds,
            "first_call": _artifact_safe_run_result(first),
            "noop_call": _artifact_safe_run_result(second),
            "profile": resolve_profile(project_root=project_root),
            }
        )

        failures: list[str] = []
        if int(first.get("returncode", -1)) != 0:
            failures.append(f"first strict run failed: {first.get('returncode')}")
        # On fresh CI checkouts strict campaigns can legitimately contain no
        # runnable selectors (campaign_total == 0). Only require stale marking
        # when the first strict pass actually had campaign entries.
        if int(first.get("campaign_total", 0)) > 0 and int(first.get("campaign_stale", 0)) < 1:
            failures.append("first strict run did not mark stale selector")
        if int(second.get("returncode", -1)) != 0:
            failures.append(f"noop strict run failed: {second.get('returncode')}")
        if int(second.get("batch_size", -1)) != 0:
            failures.append(f"noop strict run was not no-op batch_size={second.get('batch_size')}")
        if int(second.get("remaining_not_checked", -1)) != 0:
            failures.append(
                f"noop strict run unexpectedly has remaining_not_checked={second.get('remaining_not_checked')}"
            )
        if str(second.get("summary")) != "strict campaign complete; nothing to run":
            failures.append(f"unexpected noop summary: {second.get('summary')}")
        if first_seconds > max_first_call_seconds:
            failures.append(f"first call too slow: {first_seconds} > {max_first_call_seconds}")
        if noop_seconds > max_noop_call_seconds:
            failures.append(f"noop call too slow: {noop_seconds} > {max_noop_call_seconds}")
        if total_seconds > max_total_seconds:
            failures.append(f"total runtime too slow: {total_seconds} > {max_total_seconds}")
        return metrics, failures
    finally:
        _restore_batch_size(previous_batch_size)


def _print_failures(mode: str, failures: list[str]) -> None:
    if not failures:
        print(f"{mode} benchmark passed", flush=True)
        return
    for item in failures:
        print(f"{mode} benchmark failure: {item}", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="benchmark")
    parser.add_argument("mode", choices=["quality", "throughput"])
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--baseline", default=".ci/benchmark-baseline.json")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    baseline = _load_json(Path(args.baseline))

    if args.mode == "quality":
        q = baseline.get("quality", {})
        metrics, failures = run_quality_benchmark(
            project_root=project_root,
            batch_size=int(q.get("batch_size", 10)),
            max_children=int(q.get("max_children", 1)),
            max_iterations=int(q.get("max_iterations", 500)),
            score_floor=float(q.get("min_score", 0.0)),
            max_timeout=int(q.get("max_timeout", 999999)),
            max_segfault=int(q.get("max_segfault", 999999)),
            max_duration_seconds=float(q.get("max_duration_seconds", 999999.0)),
            min_checked_mutants=int(q.get("min_checked_mutants", 1)),
        )
    else:
        t = baseline.get("throughput", {})
        metrics, failures = run_throughput_benchmark(
            project_root=project_root,
            batch_size=int(t.get("batch_size", 5)),
            max_children=int(t.get("max_children", 1)),
            max_first_call_seconds=float(t.get("max_first_call_seconds", 300.0)),
            max_noop_call_seconds=float(t.get("max_noop_call_seconds", 30.0)),
            max_total_seconds=float(t.get("max_total_seconds", 330.0)),
        )

    _write_json(Path(args.json_out) if args.json_out else None, metrics)
    print(json.dumps(metrics, indent=2), flush=True)
    _print_failures(args.mode, failures)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
