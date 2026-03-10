# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .baseline import baseline_status, refresh_baseline
from .failure_explain import explain_failure
from .init import init_project
from .ledger import ledger_status, reset_ledger
from .patch_suggest import suggest_pytest_patch
from .policy import evaluate_policy
from .prioritization import rank_survivors
from .profiles import resolve_profile
from .quarantine import classify_transient_failure, load_quarantine, record_quarantine
from .reporting import render_html_bundle
from .results import get_mutant_diff, get_results, get_surviving_mutants
from .runner import kill_stuck_mutmut, reset_strict_campaign, run_mutations, strict_campaign_status
from .schema import with_schema
from .score import compute_score, load_score_history, update_score_history
from .setup import check_setup, detect_layout
from .trends import trend_report

mcp = FastMCP("pymutant")
_PROJECT_ROOT_OVERRIDE: Path | None = None


def _root() -> Path:
    """Return the project root.

    Resolution order:
    1. runtime override set via pymutant_set_project_root
    2. PYMUTANT_PROJECT_ROOT env var
    3. os.getcwd()
    """
    if _PROJECT_ROOT_OVERRIDE is not None:
        return _PROJECT_ROOT_OVERRIDE
    env_root = os.environ.get("PYMUTANT_PROJECT_ROOT")
    if env_root:
        return Path(env_root)
    return Path(os.getcwd())


def _response(data: Any, *, ok: bool = True, error: dict[str, Any] | None = None) -> dict[str, Any]:
    return with_schema(
        {
            "ok": ok,
            "data": data,
            "error": error,
        }
    )


def _error_from_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "tool_execution_error",
        "message": str(result.get("stderr") or result.get("summary") or "tool failed"),
        "details": {
            "returncode": result.get("returncode"),
            "summary": result.get("summary"),
        },
    }


@mcp.tool()
def pymutant_set_project_root(path: str) -> dict[str, Any]:
    """Set process-local project root for subsequent tool calls in this MCP process."""
    global _PROJECT_ROOT_OVERRIDE
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    if not candidate.exists() or not candidate.is_dir():
        return _response(
            {
                "path": path,
                "resolved_path": str(candidate),
                "active_project_root": str(_root()),
            },
            ok=False,
            error={"type": "invalid_project_root", "message": f"project root does not exist: {candidate}"},
        )
    previous = _PROJECT_ROOT_OVERRIDE
    _PROJECT_ROOT_OVERRIDE = candidate
    return _response(
        {
            "path": path,
            "resolved_path": str(candidate),
            "previous_project_root": str(previous) if previous is not None else None,
            "active_project_root": str(_PROJECT_ROOT_OVERRIDE),
        }
    )


@mcp.tool()
def pymutant_run(
    paths: list[str] | None = None,
    max_children: int | None = None,
    strict_campaign: bool = False,
    changed_only: bool = False,
    base_ref: str | None = None,
) -> dict[str, Any]:
    """Run mutmut mutation testing on the current project.

    Args:
        paths: Optional list of source paths to mutate (e.g. ["src/mymodule.py"]).
        max_children: Number of parallel workers (default: mutmut decides).
        strict_campaign: When True, snapshot pending mutants once and only process that fixed set.
        changed_only: When True, mutate only changed Python files derived from git diff.
        base_ref: Optional git base ref for changed_only diff (default: HEAD).
    """
    root = _root()
    result = run_mutations(
        paths=paths,
        max_children=max_children,
        strict_campaign=strict_campaign,
        changed_only=changed_only,
        base_ref=base_ref,
        project_root=root,
    )
    transient, reason = classify_transient_failure(result)
    quarantine_entry = None
    if transient and result.get("batched") and int(result.get("returncode", 0)) != 0:
        quarantine_entry = record_quarantine(
            [],
            reason=reason,
            repeatability=0.5,
            consistency=0.7,
            cleanup_success=0.5,
            project_root=root,
        )
    data = dict(result)
    data["quarantine"] = {"transient": transient, "reason": reason, "entry": quarantine_entry}
    if int(result.get("returncode", 0)) != 0:
        return _response(data, ok=False, error=_error_from_result(result))
    return _response(data)


@mcp.tool()
def pymutant_kill_stuck() -> dict[str, Any]:
    """Kill stuck mutmut/pytest worker processes related to mutation runs."""
    result = kill_stuck_mutmut(project_root=_root())
    ok = bool(result.get("ok", False)) and int(result.get("returncode", 0)) in (0, -1)
    return _response(result, ok=ok, error=None if ok else _error_from_result(result))


@mcp.tool()
def pymutant_results(
    include_killed: bool = False,
    file_filter: str | None = None,
) -> dict[str, Any]:
    """Return structured mutation results from the last run.

    Args:
        include_killed: If True, include killed mutants in output (verbose).
        file_filter: Only return mutants whose source_file contains this string.
    """
    return _response(
        get_results(
        include_killed=include_killed,
        file_filter=file_filter,
        project_root=_root(),
        )
    )


@mcp.tool()
def pymutant_show_diff(mutant_name: str) -> dict[str, Any]:
    """Return unified diff for a single mutant.

    Args:
        mutant_name: The mutant key, e.g. "src.mymodule.my_func__mutmut_3".
    """
    diff = get_mutant_diff(mutant_name, project_root=_root())
    if diff.startswith("ERROR:"):
        return _response({"mutant_name": mutant_name, "diff": diff}, ok=False, error={"type": "diff_error", "message": diff})
    return _response({"mutant_name": mutant_name, "diff": diff})


@mcp.tool()
def pymutant_compute_score() -> dict[str, Any]:
    """Compute mutation score: killed / (killed + survived + timeout + segfault).

    Returns score, percentage string, and per-status counts.
    """
    return _response(compute_score(project_root=_root()))


@mcp.tool()
def pymutant_update_score_history(label: str | None = None) -> dict[str, Any]:
    """Append current score to mutation-score.json in the project root.

    Args:
        label: Optional human-readable label for this snapshot.
    """
    return _response(update_score_history(label=label, project_root=_root()))


@mcp.tool()
def pymutant_surviving_mutants(file_filter: str | None = None) -> dict[str, Any]:
    """Return all surviving mutants with diffs, grouped by source file.

    Args:
        file_filter: Only return results for files whose path contains this string.
    """
    return _response(get_surviving_mutants(file_filter=file_filter, project_root=_root()))


@mcp.tool()
def pymutant_score_history() -> dict[str, Any]:
    """Return the full score history from mutation-score.json."""
    return _response(load_score_history(_root()))


@mcp.tool()
def pymutant_detect_layout() -> dict[str, Any]:
    """Detect the project layout and return a suggested mutmut configuration.

    Identifies flat, flat_src, or monorepo layouts. For monorepo projects,
    explains the key-mismatch problem and the src/ symlink fix required.
    Returns suggested paths_to_mutate, tests_dir, and also_copy values.
    """
    return _response(detect_layout(project_root=_root()))


@mcp.tool()
def pymutant_check_setup() -> dict[str, Any]:
    """Run pre-flight checks for mutmut readiness on the project.

    Checks: mutmut installed, pyproject.toml present, [tool.mutmut] config exists,
    paths_to_mutate and tests_dir are lists (not strings), all configured paths exist,
    monorepo key-mismatch detection, and conftest.py MUTANT_UNDER_TEST guard.
    Returns ok=True only if all checks pass.
    """
    result = check_setup(project_root=_root())
    return _response(result, ok=bool(result.get("ok", False)), error=None if result.get("ok") else {"type": "setup_error", "message": "setup checks failed"})


@mcp.tool()
def pymutant_init(
    paths_to_mutate: list[str] | None = None,
    tests_dir: list[str] | None = None,
    also_copy: list[str] | None = None,
    pytest_add_cli_args: list[str] | None = None,
    with_conftest: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scaffold mutmut config in pyproject.toml and optionally create conftest.py.

    Auto-detects project layout if paths are not provided. Safe to run on existing
    projects — will not overwrite an existing [tool.mutmut] section or conftest.py
    that already has the MUTANT_UNDER_TEST guard.

    Args:
        paths_to_mutate: Override auto-detected mutation paths.
        tests_dir: Override auto-detected test directories.
        also_copy: Extra files/dirs for mutmut to copy alongside source.
        pytest_add_cli_args: Extra pytest args (e.g. ["--ignore=tests/slow_test.py"]).
        with_conftest: Write conftest.py with MUTANT_UNDER_TEST sys.path guard.
        dry_run: Show what would be written without modifying any files.
    """
    result = init_project(
        paths_to_mutate=paths_to_mutate,
        tests_dir=tests_dir,
        also_copy=also_copy,
        pytest_add_cli_args=pytest_add_cli_args,
        with_conftest=with_conftest,
        dry_run=dry_run,
        project_root=_root(),
    )
    return _response(result)


@mcp.tool()
def pymutant_ledger_status() -> dict[str, Any]:
    """Return status for mutation ledger and strict campaign progress."""
    root = _root()
    return _response(
        {
        "ledger": ledger_status(project_root=root),
        "campaign": strict_campaign_status(project_root=root),
        "quarantine": load_quarantine(project_root=root),
        "baseline": baseline_status(project_root=root, command_mode="status"),
        }
    )


@mcp.tool()
def pymutant_reset_campaign(clear_ledger: bool = False) -> dict[str, Any]:
    """Reset strict-campaign state; optionally clear outcome ledger too."""
    root = _root()
    removed_campaign = reset_strict_campaign(project_root=root)
    removed_ledger = reset_ledger(project_root=root) if clear_ledger else False
    return _response(
        {
        "ok": True,
        "removed_campaign": removed_campaign,
        "removed_ledger": removed_ledger,
        }
    )


@mcp.tool()
def pymutant_rank_survivors(top_n: int = 50, profile: str | None = None, config_path: str | None = None) -> dict[str, Any]:
    root = _root()
    ranked = rank_survivors(project_root=root, top_n=top_n)
    return _response(
        {
            "profile": resolve_profile(profile=profile, config_path=config_path, project_root=root),
            "ranking": ranked,
        }
    )


@mcp.tool()
def pymutant_explain_failure(returncode: int, summary: str = "", stderr: str = "") -> dict[str, Any]:
    return _response(explain_failure({"returncode": returncode, "summary": summary, "stderr": stderr}))


@mcp.tool()
def pymutant_policy_check(profile: str | None = None, config_path: str | None = None, baseline_path: str | None = None) -> dict[str, Any]:
    root = _root()
    score_data = compute_score(project_root=root)
    runtime_baseline = baseline_status(
        project_root=root,
        command_mode="policy",
        profile=profile,
        config_path=config_path,
    )
    policy = evaluate_policy(
        current_score=float(score_data["score"]),
        profile=profile,
        config_path=config_path,
        baseline_path=baseline_path,
        runtime_baseline=runtime_baseline,
        project_root=root,
    )
    if policy.get("ok"):
        return _response(policy)
    failures = [str(item) for item in policy.get("failures", [])]
    baseline_invalid = any(item.startswith("baseline invalid:") for item in failures)
    error_type = "baseline_invalid" if baseline_invalid else "policy_failure"
    return _response(policy, ok=False, error={"type": error_type, "message": "; ".join(failures)})


@mcp.tool()
def pymutant_trend_report(window: int = 5) -> dict[str, Any]:
    return _response(trend_report(load_score_history(_root()), window=window))


@mcp.tool()
def pymutant_suggest_pytest_patch(mutant_name: str, source_file: str, diff: str, apply: bool = False) -> dict[str, Any]:
    return _response(
        suggest_pytest_patch(
            mutant_name=mutant_name,
            source_file=source_file,
            diff=diff,
            apply=apply,
            project_root=_root(),
        )
    )


@mcp.tool()
def pymutant_render_report(profile: str | None = None, config_path: str | None = None, baseline_path: str | None = None) -> dict[str, Any]:
    root = _root()
    score_data = compute_score(project_root=root)
    result_data = get_results(include_killed=False, project_root=root)
    runtime_baseline = baseline_status(
        project_root=root,
        command_mode="render_report",
        profile=profile,
        config_path=config_path,
    )
    policy_data = evaluate_policy(
        current_score=float(score_data["score"]),
        profile=profile,
        config_path=config_path,
        baseline_path=baseline_path,
        runtime_baseline=runtime_baseline,
        project_root=root,
    )
    trend_data = trend_report(load_score_history(root))
    report = render_html_bundle(
        score=score_data,
        results=result_data,
        policy=policy_data,
        trend=trend_data,
        project_root=root,
    )
    return _response(report)


@mcp.tool()
def pymutant_baseline_status(profile: str | None = None, config_path: str | None = None, command_mode: str = "status") -> dict[str, Any]:
    return _response(
        baseline_status(
            project_root=_root(),
            profile=profile,
            config_path=config_path,
            command_mode=command_mode,
        )
    )


@mcp.tool()
def pymutant_baseline_refresh(profile: str | None = None, config_path: str | None = None, command_mode: str = "manual_refresh") -> dict[str, Any]:
    return _response(
        refresh_baseline(
            project_root=_root(),
            profile=profile,
            config_path=config_path,
            command_mode=command_mode,
        )
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pymutant")
    parser.add_argument(
        "--project-root",
        help="Project root to operate on (overrides cwd for this process).",
    )
    args = parser.parse_args(argv)
    if args.project_root:
        root = Path(args.project_root).expanduser()
        if not root.is_absolute():
            root = (Path.cwd() / root).resolve()
        os.environ["PYMUTANT_PROJECT_ROOT"] = str(root)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
