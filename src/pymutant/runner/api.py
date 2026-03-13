# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pymutant.baseline import ensure_runtime_baseline

from .helpers import (
    DEFAULT_BATCH_MAX_CHILDREN,
    _batch_size,
    _dependency_preflight,
    _init_or_load_strict_campaign,
    _load_not_checked_mutants,
    _mutmut_cmd_prefix,
    _noop_payload,
    _normalize_path_selectors,
    _project_root_or_cwd,
    _record_ledger_outcomes,
    _refresh_strict_campaign_names,
    _resolve_changed_paths_for_mutation,
    _run_cmd,
    _sanitize_mutant_meta_files,
    _save_strict_campaign,
    _select_batch_names,
    _strict_campaign_path,
    _strict_remaining_names,
)


def _build_command(
    *,
    root: Path,
    paths: list[str] | None,
    strict_campaign: bool,
    changed_only: bool,
    base_ref: str | None,
) -> dict[str, Any]:
    cmd_prefix = _mutmut_cmd_prefix(root)
    cmd = [*cmd_prefix, "run"]
    pending_names: list[str] = []
    batch_names: list[str] = []
    changed_paths: list[str] = []
    strict_campaign_state = None

    normalized_paths: list[str] = []
    ignored_paths: list[str] = []

    if paths:
        normalized_paths, ignored_paths = _normalize_path_selectors(root, paths)
        if not normalized_paths:
            return {
                "result": {
                    "returncode": -1,
                    "stdout": "",
                    "stderr": (
                        "No valid selectors matched files under mutation roots. "
                        f"Ignored selectors: {', '.join(ignored_paths or paths)}"
                    ),
                    "summary": "path selectors did not match mutation roots",
                }
            }
        cmd.extend(normalized_paths)
        strict_campaign = False
        changed_only = False
    elif changed_only:
        changed_paths, changed_error = _resolve_changed_paths_for_mutation(root, base_ref=base_ref)
        if changed_error:
            return {"error": changed_error, "summary": "changed file detection failed"}
        if not changed_paths:
            return {
                "result": {
                    **_noop_payload("no changed python files under mutation roots", strict_campaign=False, changed_only=True),
                    "changed_paths": [],
                }
            }
        cmd.extend(changed_paths)
        strict_campaign = False
    elif strict_campaign:
        strict_campaign_state = _init_or_load_strict_campaign(root)
        pending_names = _strict_remaining_names(root, strict_campaign_state)
        if not pending_names:
            return {
                "result": {
                    **_noop_payload("strict campaign complete; nothing to run", strict_campaign=True),
                    "campaign_total": len(strict_campaign_state["names"]),
                    "campaign_attempted": len(strict_campaign_state["attempted"]),
                    "campaign_stale": len(strict_campaign_state["stale"]),
                }
            }
        batch_names = pending_names[: _batch_size()]
        cmd.extend(batch_names)
    else:
        pending_names = _load_not_checked_mutants(root)
        if pending_names:
            batch_names = _select_batch_names(pending_names, root, _batch_size())
            cmd.extend(batch_names)

    return {
        "cmd": cmd,
        "cmd_prefix": cmd_prefix,
        "pending_names": pending_names,
        "batch_names": batch_names,
        "changed_paths": changed_paths,
        "strict_campaign_state": strict_campaign_state,
        "strict_campaign": strict_campaign,
        "changed_only": changed_only,
        "normalized_paths": normalized_paths,
        "ignored_paths": ignored_paths,
    }
def _apply_max_children(cmd: list[str], *, batch_names: list[str], max_children: int | None) -> None:
    if max_children is not None:
        cmd.extend(["--max-children", str(max_children)])
    elif batch_names:
        cmd.extend(["--max-children", str(DEFAULT_BATCH_MAX_CHILDREN)])


def _maybe_mark_strict_stale(
    *,
    root: Path,
    result: dict[str, Any],
    strict_campaign: bool,
    strict_campaign_state: Any,
    batch_names: list[str],
) -> tuple[bool, dict[str, Any], Any]:
    stale_filter = "Filtered for specific mutants, but nothing matches"
    returncode = result.get("returncode")
    stale_marked = False
    if not (
        strict_campaign
        and strict_campaign_state is not None
        and batch_names
        and isinstance(returncode, int)
        and returncode != 0
        and stale_filter in str(result.get("stderr", ""))
    ):
        return stale_marked, result, strict_campaign_state

    merged_stale = sorted(set(strict_campaign_state["stale"]).union(batch_names))
    strict_campaign_state["stale"] = merged_stale
    _save_strict_campaign(root, strict_campaign_state)
    stale_marked = True
    result["returncode"] = 0
    refreshed = _refresh_strict_campaign_names(root, strict_campaign_state)
    strict_campaign_state["names"] = refreshed["names"]
    strict_campaign_state["stale"] = sorted(set(refreshed["stale"]).union(batch_names))
    strict_campaign_state["attempted"] = refreshed["attempted"]
    _save_strict_campaign(root, strict_campaign_state)
    result["summary"] = "strict campaign refreshed stale selectors"
    err = str(result.get("stderr", "")).strip()
    result["stderr"] = f"{err}\nRefreshed strict-campaign selectors and continuing.".strip()
    return stale_marked, result, strict_campaign_state


def _maybe_retry_batched_stale(
    *,
    root: Path,
    result: dict[str, Any],
    strict_campaign: bool,
    cmd_prefix: list[str],
    batch_names: list[str],
    max_children: int | None,
) -> tuple[dict[str, Any], list[str]]:
    stale_filter = "Filtered for specific mutants, but nothing matches"
    returncode = result.get("returncode")
    if not (
        not strict_campaign
        and batch_names
        and isinstance(returncode, int)
        and returncode != 0
        and stale_filter in str(result.get("stderr", ""))
    ):
        return result, batch_names

    pending_names = _load_not_checked_mutants(root)
    if pending_names:
        batch_names = _select_batch_names(pending_names, root, _batch_size())
        retry_cmd = [*cmd_prefix, "run", *batch_names]
        _apply_max_children(retry_cmd, batch_names=batch_names, max_children=max_children)
        print(f"Retrying with refreshed batch: {' '.join(retry_cmd)} (cwd={root})", file=sys.stderr)
        result = _run_cmd(retry_cmd, root)

    if (
        batch_names
        and isinstance(result.get("returncode"), int)
        and result.get("returncode") != 0
        and stale_filter in str(result.get("stderr", ""))
    ):
        fallback_cmd = [*cmd_prefix, "run"]
        _apply_max_children(fallback_cmd, batch_names=batch_names, max_children=max_children)
        print(f"Falling back to unfiltered run: {' '.join(fallback_cmd)} (cwd={root})", file=sys.stderr)
        result = _run_cmd(fallback_cmd, root)
    return result, batch_names


def _attach_common_result_fields(
    *,
    root: Path,
    result: dict[str, Any],
    strict_campaign: bool,
    strict_campaign_state: Any,
    pending_names: list[str],
    batch_names: list[str],
    changed_only: bool,
    changed_paths: list[str],
    normalized_paths: list[str],
    ignored_paths: list[str],
    sanitize: Mapping[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    result["batched"] = bool(batch_names)
    result["batch_size"] = len(batch_names)
    if strict_campaign and strict_campaign_state is not None:
        campaign_remaining = _strict_remaining_names(root, strict_campaign_state)
        result.update(
            {
                "strict_campaign": True,
                "campaign_total": len(strict_campaign_state["names"]),
                "campaign_attempted": len(strict_campaign_state["attempted"]),
                "campaign_stale": len(strict_campaign_state["stale"]),
                "remaining_not_checked": len(campaign_remaining),
            }
        )
    else:
        result["strict_campaign"] = False
        result["remaining_not_checked"] = max(0, len(pending_names) - len(batch_names))
    result["changed_only"] = changed_only
    if changed_only:
        result["changed_paths"] = changed_paths
    if normalized_paths:
        result["normalized_paths"] = normalized_paths
    if ignored_paths:
        result["ignored_paths"] = ignored_paths
    result["meta_sanitize"] = sanitize
    result["baseline"] = baseline
    return result


def _normalize_changed_only_selector_miss(
    *,
    result: dict[str, Any],
    changed_only: bool,
    changed_paths: list[str],
) -> dict[str, Any]:
    stale_filter = "Filtered for specific mutants, but nothing matches"
    if not changed_only:
        return result
    if not isinstance(result.get("returncode"), int):
        return result
    if result["returncode"] == 0:
        return result
    if stale_filter not in str(result.get("stderr", "")):
        return result
    return {
        **_noop_payload("no matching mutants for changed selectors", strict_campaign=False, changed_only=True),
        "changed_paths": changed_paths,
    }


def _augment_paths_selector_miss(
    *,
    result: dict[str, Any],
    normalized_paths: list[str],
) -> dict[str, Any]:
    stale_filter = "Filtered for specific mutants, but nothing matches"
    if not normalized_paths:
        return result
    if not isinstance(result.get("returncode"), int):
        return result
    if result["returncode"] == 0:
        return result
    if stale_filter not in str(result.get("stderr", "")):
        return result

    message = (
        "path selectors did not match any generated mutants. "
        "Try pymutant_baseline_refresh to clear stale cache, then rerun with normalized_paths."
    )
    err = str(result.get("stderr", "")).strip()
    result["summary"] = message
    result["refresh_recommended"] = True
    result["stderr"] = f"{err}\n{message}".strip()
    return result


def _augment_zero_mutation_hint(
    *,
    result: dict[str, Any],
) -> dict[str, Any]:
    if result.get("returncode") != 0:
        return result
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}".lower()
    if "0 files mutated" not in text:
        return result
    result["refresh_recommended"] = True
    if not str(result.get("summary", "")).strip():
        result["summary"] = "mutmut reported zero mutated files"
    result["hint"] = "Run pymutant_baseline_refresh to clear stale mutants cache and regenerate selectors."
    return result


def _mark_strict_campaign_attempted(
    *,
    root: Path,
    result: dict[str, Any],
    strict_campaign: bool,
    strict_campaign_state: Any,
    batch_names: list[str],
) -> None:
    if not (
        strict_campaign
        and strict_campaign_state is not None
        and batch_names
        and isinstance(result.get("returncode"), int)
        and result["returncode"] != -1
    ):
        return
    strict_campaign_state["attempted"] = sorted(set(strict_campaign_state["attempted"]).union(batch_names))
    _save_strict_campaign(root, strict_campaign_state)


def run_mutations(
    paths: list[str] | None = None,
    max_children: int | None = None,
    strict_campaign: bool = False,
    changed_only: bool = False,
    base_ref: str | None = None,
    include_raw_output: bool = False,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Run `mutmut run` and return structured output."""
    root = _project_root_or_cwd(project_root)
    command_mode = "paths" if paths else "changed_only" if changed_only else "strict_campaign" if strict_campaign else "run"
    baseline = ensure_runtime_baseline(project_root=root, command_mode=command_mode, auto_reset=True)
    sanitize = _sanitize_mutant_meta_files(root)

    plan = _build_command(root=root, paths=paths, strict_campaign=strict_campaign, changed_only=changed_only, base_ref=base_ref)
    if "error" in plan:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": plan["error"],
            "summary": plan["summary"],
            "changed_only": True,
            "meta_sanitize": sanitize,
            "baseline": baseline,
        }
    if "result" in plan:
        result = dict(plan["result"])
        result["meta_sanitize"] = sanitize
        result["baseline"] = baseline
        return result

    cmd = plan["cmd"]
    cmd_prefix = plan["cmd_prefix"]
    pending_names = plan["pending_names"]
    batch_names = plan["batch_names"]
    changed_paths = plan["changed_paths"]
    normalized_paths = plan["normalized_paths"]
    ignored_paths = plan["ignored_paths"]
    strict_campaign_state = plan["strict_campaign_state"]
    strict_campaign = plan["strict_campaign"]
    changed_only = plan["changed_only"]

    preflight_error = _dependency_preflight(root, cmd_prefix)
    if preflight_error:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": preflight_error,
            "summary": "dependency preflight failed",
            "meta_sanitize": sanitize,
            "baseline": baseline,
        }

    _apply_max_children(cmd, batch_names=batch_names, max_children=max_children)
    print(f"Running: {' '.join(cmd)} (cwd={root})", file=sys.stderr)
    result = _run_cmd(cmd, root, compact_progress=not include_raw_output)
    result = _normalize_changed_only_selector_miss(result=result, changed_only=changed_only, changed_paths=changed_paths)
    result = _augment_paths_selector_miss(result=result, normalized_paths=normalized_paths)

    _mark_strict_campaign_attempted(
        root=root,
        result=result,
        strict_campaign=strict_campaign,
        strict_campaign_state=strict_campaign_state,
        batch_names=batch_names,
    )

    stale_marked, result, strict_campaign_state = _maybe_mark_strict_stale(
        root=root,
        result=result,
        strict_campaign=strict_campaign,
        strict_campaign_state=strict_campaign_state,
        batch_names=batch_names,
    )

    result, batch_names = _maybe_retry_batched_stale(
        root=root,
        result=result,
        strict_campaign=strict_campaign,
        cmd_prefix=cmd_prefix,
        batch_names=batch_names,
        max_children=max_children,
    )

    if batch_names:
        context = "strict_campaign_batch" if strict_campaign else "batch"
        stale_names = set(batch_names) if stale_marked else set()
        _record_ledger_outcomes(
            root,
            batch_names,
            run_output=str(result.get("stdout", "")),
            stale_names=stale_names,
            context=context,
        )
    elif paths and all("__mutmut_" in p for p in paths):
        _record_ledger_outcomes(
            root,
            paths,
            run_output=str(result.get("stdout", "")),
            context="explicit_selectors",
        )

    result = _augment_zero_mutation_hint(result=result)

    return _attach_common_result_fields(
        root=root,
        result=result,
        strict_campaign=strict_campaign,
        strict_campaign_state=strict_campaign_state,
        pending_names=pending_names,
        batch_names=batch_names,
        changed_only=changed_only,
        changed_paths=changed_paths,
        normalized_paths=normalized_paths,
        ignored_paths=ignored_paths,
        sanitize=sanitize,
        baseline=baseline,
    )


def strict_campaign_status(project_root: Path | None = None) -> dict[str, object]:
    root = _project_root_or_cwd(project_root)
    campaign_path = _strict_campaign_path(root)
    if not campaign_path.exists():
        return {
            "path": str(campaign_path),
            "exists": False,
            "campaign_total": 0,
            "campaign_attempted": 0,
            "campaign_stale": 0,
            "remaining_not_checked": 0,
        }
    campaign = _init_or_load_strict_campaign(root)
    return {
        "path": str(campaign_path),
        "exists": True,
        "campaign_total": len(campaign["names"]),
        "campaign_attempted": len(campaign["attempted"]),
        "campaign_stale": len(campaign["stale"]),
        "remaining_not_checked": len(_strict_remaining_names(root, campaign)),
    }


def reset_strict_campaign(project_root: Path | None = None) -> bool:
    root = _project_root_or_cwd(project_root)
    campaign_path = _strict_campaign_path(root)
    if not campaign_path.exists():
        return False
    campaign_path.unlink()
    return True


def kill_stuck_mutmut(project_root: Path | None = None) -> dict[str, Any]:
    """Kill stuck mutmut/pytest workers related to mutation runs."""
    root = _project_root_or_cwd(project_root)
    if shutil.which("pkill") is None:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "pkill is not available on this system",
            "summary": "cleanup unavailable",
        }

    patterns = [f"{root}/mutants", "python -m mutmut", "mutmut run", "MUTANT_UNDER_TEST"]
    details: list[dict[str, object]] = []
    killed_any = False
    for pattern in patterns:
        result = subprocess.run(  # noqa: S603  # nosec
            ["pkill", "-f", pattern],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
        )
        killed = result.returncode == 0
        killed_any = killed_any or killed
        details.append({"pattern": pattern, "killed": killed, "returncode": result.returncode})

    return {"ok": True, "killed_any": killed_any, "details": details}
