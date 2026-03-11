# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import time
from pathlib import Path
from typing import Any, TypeAlias

from .baseline import baseline_status
from .ledger import resolve_latest_statuses
from .mutmut_cmd import mutmut_cmd_prefix

StatusMap: TypeAlias = dict[int | None, str]
STRICT_CAMPAIGN_FILE = ".pymutant-strict-campaign.json"

# Canonical mutmut 3.5.x exit-code mapping normalized to MCP status names.
# Source: mutmut.__main__.status_by_exit_code
EXIT_CODE_STATUS: StatusMap = {
    1: "killed",
    3: "killed",
    0: "survived",
    5: "no_tests",
    33: "no_tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    24: "timeout",
    152: "timeout",
    255: "timeout",
    -24: "timeout",
    37: "typecheck_failed",
    2: "interrupted",
    -11: "segfault",
    -9: "segfault",
    None: "not_checked",
}


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _meta_dir(project_root: Path) -> Path:
    return project_root / "mutants"


def _load_meta_json(meta_file: Path, retries: int = 3, retry_delay_seconds: float = 0.05) -> dict[str, Any] | None:
    for attempt in range(retries):
        try:
            data = json.loads(meta_file.read_text())
        except json.JSONDecodeError:
            if attempt < retries - 1:
                time.sleep(retry_delay_seconds)
                continue
            return None
        except OSError:
            return None
        if isinstance(data, dict):
            return data
        return None
    return None


def _strict_campaign_progress(project_root: Path) -> dict[str, object]:
    campaign_path = project_root / STRICT_CAMPAIGN_FILE
    if not campaign_path.exists():
        return {
            "exists": False,
            "valid": False,
            "path": str(campaign_path),
            "campaign_total": 0,
            "campaign_attempted": 0,
            "campaign_stale": 0,
            "remaining_not_checked": 0,
        }
    try:
        campaign = json.loads(campaign_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {
            "exists": True,
            "valid": False,
            "path": str(campaign_path),
            "campaign_total": 0,
            "campaign_attempted": 0,
            "campaign_stale": 0,
            "remaining_not_checked": 0,
        }

    names = campaign.get("names", [])
    attempted = set(campaign.get("attempted", []))
    stale = set(campaign.get("stale", []))
    if not isinstance(names, list):
        names = []
    remaining = len([name for name in names if name not in attempted and name not in stale])
    return {
        "exists": True,
        "valid": True,
        "path": str(campaign_path),
        "campaign_total": len(names),
        "campaign_attempted": len(attempted),
        "campaign_stale": len(stale),
        "remaining_not_checked": remaining,
    }


def load_all_meta_files(project_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load all .meta files from the mutants/ directory."""
    root = _project_root_or_cwd(project_root)
    meta_dir = _meta_dir(root)
    results: dict[str, dict[str, Any]] = {}
    if not meta_dir.exists():
        return results
    for meta_file in meta_dir.rglob("*.meta"):
        data = _load_meta_json(meta_file)
        if data is not None:
            results[str(meta_file.relative_to(root))] = data
    return results


def _key_to_source_file(key: str, project_root: Path | None = None) -> str:
    """Derive source file path from mutant key like 'src.module.func__mutmut_1'."""
    name_part = key.split("__mutmut_")[0]
    parts = name_part.split(".")

    if project_root is not None:
        for idx in range(len(parts), 0, -1):
            candidate = (project_root / Path(*parts[:idx])).with_suffix(".py")
            if candidate.is_file():
                return candidate.relative_to(project_root).as_posix()

    # Fallback for missing/deleted source files.
    naive_parts = name_part.rsplit(".", 1)
    module_path = naive_parts[0] if len(naive_parts) > 1 else name_part
    return module_path.replace(".", "/") + ".py"


def get_results(
    include_killed: bool = False,
    file_filter: str | None = None,
    use_ledger: bool = True,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Return structured mutation results from all .meta files."""
    root = _project_root_or_cwd(project_root)
    baseline = baseline_status(project_root=root, command_mode="results")
    reasons = [str(reason) for reason in baseline.get("reasons", [])]
    if not baseline["valid"] and reasons != ["missing_baseline"]:
        empty_counts: dict[str, int] = {status: 0 for status in set(EXIT_CODE_STATUS.values()) | {"stale"}}
        return {
            "mutants": [],
            "counts": empty_counts,
            "total": 0,
            "progress": {
                "source": "baseline_invalid",
                "not_checked_effective": 0,
                "strict_campaign": _strict_campaign_progress(root),
            },
            "baseline": baseline,
        }

    meta_files = load_all_meta_files(root)

    all_mutants: list[dict[str, Any]] = []
    counts: dict[str, int] = {status: 0 for status in set(EXIT_CODE_STATUS.values()) | {"stale"}}
    status_by_key: dict[str, str] = {}
    duration_by_key: dict[str, float | None] = {}
    meta_path_by_key: dict[str, str] = {}

    for meta_path, meta_data in meta_files.items():
        exit_codes: dict[str, int | None] = meta_data.get("exit_code_by_key", {})
        durations: dict[str, float] = meta_data.get("durations_by_key", {})

        for key, exit_code in exit_codes.items():
            status_by_key[key] = EXIT_CODE_STATUS.get(exit_code, "suspicious")
            duration_by_key[key] = durations.get(key)
            meta_path_by_key[key] = meta_path

    if use_ledger:
        for key, status in resolve_latest_statuses(root).items():
            status_by_key[key] = status

    for key in sorted(status_by_key.keys()):
        status = status_by_key[key]
        counts[status] = counts.get(status, 0) + 1

        if not include_killed and status == "killed":
            continue

        source_file = _key_to_source_file(key, root)
        if file_filter and file_filter not in source_file:
            continue

        all_mutants.append(
            {
                "name": key,
                "status": status,
                "source_file": source_file,
                "meta_path": meta_path_by_key.get(key),
                "duration": duration_by_key.get(key),
            }
        )

    campaign = _strict_campaign_progress(root)
    if bool(campaign["exists"]) and bool(campaign["valid"]):
        remaining = campaign["remaining_not_checked"]
        not_checked_effective = int(remaining) if isinstance(remaining, int) else 0
        progress_source = "strict_campaign"
    else:
        not_checked_effective = counts.get("not_checked", 0)
        progress_source = "meta"

    return {
        "mutants": all_mutants,
        "counts": counts,
        "total": sum(counts.values()),
        "progress": {
            "source": progress_source,
            "not_checked_effective": not_checked_effective,
            "strict_campaign": campaign,
        },
        "baseline": baseline,
    }


def get_mutant_diff(mutant_name: str, project_root: Path | None = None) -> str:
    """Return unified diff for a single mutant via `mutmut show <name>`."""
    root = _project_root_or_cwd(project_root)
    cmd = [*mutmut_cmd_prefix(root), "show", mutant_name]
    try:
        result = subprocess.run(  # noqa: S603  # nosec
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return "ERROR: mutmut show timed out after 30 seconds"
    except FileNotFoundError:
        return "ERROR: mutmut not found — install it in the target project with `uv add mutmut --dev`"

    output = result.stdout or result.stderr
    if result.returncode != 0:
        return f"ERROR: mutmut show failed for {mutant_name}: {output.strip()}"
    return output


def get_surviving_mutants(
    file_filter: str | None = None,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return surviving mutants with diffs, grouped by source file."""
    root = _project_root_or_cwd(project_root)
    data = get_results(include_killed=False, file_filter=file_filter, project_root=root)
    survivors = [m for m in data["mutants"] if m["status"] == "survived"]

    for mutant in survivors:
        diff = get_mutant_diff(mutant["name"], root)
        mutant["diff"] = diff
        mutant["diff_error"] = diff.startswith("ERROR:")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for mutant in survivors:
        source_file = mutant["source_file"]
        grouped.setdefault(source_file, []).append(mutant)

    return [{"source_file": f, "mutants": ms} for f, ms in grouped.items()]
