# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess  # nosec B404
import sys
import time
import tomllib
from pathlib import Path
from typing import TypedDict

from .io_utils import atomic_write_text
from .ledger import append_ledger_event
from .mutmut_cmd import mutmut_cmd_prefix, preferred_python
from .results import EXIT_CODE_STATUS

MUTMUT_TIMEOUT = 30 * 60  # 30 minutes in seconds
MUTMUT_NO_PROGRESS_TIMEOUT = 5 * 60  # 5 minutes with no new output
DEFAULT_MUTANT_BATCH_SIZE = 10
DEFAULT_BATCH_MAX_CHILDREN = 2
_PENDING_CURSOR_BY_ROOT: dict[str, int] = {}
STRICT_CAMPAIGN_FILE = ".pymutant-strict-campaign.json"
RESULT_ICON_STATUS = {
    "🎉": "killed",
    "🙁": "survived",
    "⏰": "timeout",
    "🫥": "no_tests",
    "🤔": "suspicious",
    "🔇": "skipped",
    "🧙": "typecheck_failed",
}


class StrictCampaign(TypedDict):
    names: list[str]
    stale: list[str]
    attempted: list[str]


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _extract_summary(output: str) -> str:
    """Extract the last meaningful line from mutmut output."""
    lines = [l.strip() for l in output.strip().splitlines() if l.strip()]  # noqa: E741
    for line in reversed(lines):
        if any(word in line.lower() for word in ["killed", "survived", "mutant", "mutation"]):
            return line
    return lines[-1] if lines else ""


def _preferred_python(root: Path) -> str | None:
    return preferred_python(root)


def _mutmut_cmd_prefix(root: Path) -> list[str]:
    return mutmut_cmd_prefix(root)


def _batch_size() -> int:
    raw = os.environ.get("PYMUTANT_BATCH_SIZE")
    if raw is None:
        return DEFAULT_MUTANT_BATCH_SIZE
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MUTANT_BATCH_SIZE
    return max(1, value)


def _configured_mutation_roots(root: Path) -> list[str]:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return []
    try:
        data = tomllib.loads(pyproject.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return []
    paths = data.get("tool", {}).get("mutmut", {}).get("paths_to_mutate", [])
    if isinstance(paths, str):
        paths = [paths]
    if not isinstance(paths, list):
        return []
    roots = [str(p).strip().rstrip("/") for p in paths if str(p).strip()]
    return roots


def _filter_changed_python_paths(root: Path, candidates: list[str]) -> list[str]:
    mutation_roots = _configured_mutation_roots(root)
    normalized: set[str] = set()
    for raw in candidates:
        candidate = raw.strip().replace("\\", "/")
        if not candidate.endswith(".py"):
            continue
        if candidate.startswith("/"):
            continue
        file_path = (root / candidate).resolve()
        if not file_path.exists() or not file_path.is_file():
            continue
        rel = str(file_path.relative_to(root.resolve())).replace("\\", "/")
        if mutation_roots:
            in_roots = any(rel == p or rel.startswith(f"{p}/") for p in mutation_roots)
            if not in_roots:
                continue
        normalized.add(rel)
    return sorted(normalized)


def _resolve_changed_paths_for_mutation(root: Path, base_ref: str | None = None) -> tuple[list[str], str | None]:
    if shutil.which("git") is None:
        return [], "git is not available on this system"

    diff_ref = f"{base_ref}...HEAD" if base_ref else "HEAD"
    commands = [
        ["git", "diff", "--name-only", "--diff-filter=AM", diff_ref],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    candidates: list[str] = []
    for cmd in commands:
        try:
            result = subprocess.run(  # noqa: S603  # nosec
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [], f"failed to run {' '.join(cmd)}: {exc}"
        if result.returncode != 0:
            return [], f"failed to detect changed files: {' '.join(cmd)}"
        candidates.extend(line.strip() for line in result.stdout.splitlines() if line.strip())
    return _filter_changed_python_paths(root, candidates), None


def _load_not_checked_mutants(root: Path) -> list[str]:
    meta_dir = root / "mutants"
    if not meta_dir.exists():
        return []
    names: list[str] = []
    for meta_file in meta_dir.rglob("*.meta"):
        try:
            data = json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for name, exit_code in data.get("exit_code_by_key", {}).items():
            if exit_code is None:
                names.append(name)
    return sorted(names)


def _strict_campaign_path(root: Path) -> Path:
    return root / STRICT_CAMPAIGN_FILE


def _load_exit_codes_by_key(root: Path) -> dict[str, int | None]:
    meta_dir = root / "mutants"
    if not meta_dir.exists():
        return {}
    exit_codes: dict[str, int | None] = {}
    for meta_file in meta_dir.rglob("*.meta"):
        try:
            data = json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for name, code in data.get("exit_code_by_key", {}).items():
            exit_codes[name] = code
    return exit_codes


def _record_ledger_outcomes(
    root: Path,
    mutant_names: list[str],
    *,
    run_output: str = "",
    stale_names: set[str] | None = None,
    context: str,
) -> None:
    if not mutant_names:
        return
    exit_codes = _load_exit_codes_by_key(root)
    parsed_statuses = _parse_mutmut_result_lines(run_output)
    stale = stale_names if stale_names is not None else set()
    outcomes: dict[str, str] = {}
    for name in mutant_names:
        if name in stale:
            outcomes[name] = "stale"
        elif name in parsed_statuses:
            outcomes[name] = parsed_statuses[name]
        else:
            outcomes[name] = EXIT_CODE_STATUS.get(exit_codes.get(name), "suspicious")
    append_ledger_event(outcomes, context=context, project_root=root)


def _parse_mutmut_result_lines(output: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        first, _, rest = line.partition(" ")
        if first not in RESULT_ICON_STATUS:
            continue
        name = rest.strip()
        if "__mutmut_" not in name:
            continue
        parsed[name] = RESULT_ICON_STATUS[first]
    return parsed


def _init_or_load_strict_campaign(root: Path) -> StrictCampaign:
    campaign_path = _strict_campaign_path(root)
    if campaign_path.exists():
        try:
            data = json.loads(campaign_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
        if isinstance(data, dict):
            names = data.get("names")
            stale = data.get("stale", [])
            attempted = data.get("attempted", [])
            if isinstance(names, list) and all(isinstance(n, str) for n in names):
                if not isinstance(stale, list) or not all(isinstance(n, str) for n in stale):
                    stale = []
                if not isinstance(attempted, list) or not all(isinstance(n, str) for n in attempted):
                    attempted = []
                return {"names": names, "stale": stale, "attempted": attempted}

    names = _load_not_checked_mutants(root)
    campaign: StrictCampaign = {"names": names, "stale": [], "attempted": []}
    atomic_write_text(campaign_path, json.dumps(campaign, indent=2) + "\n")
    return campaign


def _save_strict_campaign(root: Path, campaign: StrictCampaign) -> None:
    atomic_write_text(_strict_campaign_path(root), json.dumps(campaign, indent=2) + "\n")


def _strict_remaining_names(root: Path, campaign: StrictCampaign) -> list[str]:
    names = campaign["names"]
    attempted = set(campaign["attempted"])
    _ = _load_exit_codes_by_key(root)
    return [name for name in names if name not in attempted]


def _select_batch_names(pending_names: list[str], root: Path, batch_size: int) -> list[str]:
    if not pending_names:
        return []
    batch_take = min(batch_size, len(pending_names))
    root_key = str(root.resolve())
    cursor = _PENDING_CURSOR_BY_ROOT.get(root_key, 0)
    start = cursor % len(pending_names)
    end = start + batch_take
    if end <= len(pending_names):
        batch = pending_names[start:end]
    else:
        batch = pending_names[start:] + pending_names[: end - len(pending_names)]
    _PENDING_CURSOR_BY_ROOT[root_key] = cursor + batch_take
    return batch


def _requires_mcp_dependency(root: Path) -> bool:
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            mutmut_cfg = data.get("tool", {}).get("mutmut", {})
            paths = mutmut_cfg.get("paths_to_mutate", [])
            if isinstance(paths, str):
                paths = [paths]
            if isinstance(paths, list) and any(str(p).startswith("server/src") for p in paths):
                return True
        except (tomllib.TOMLDecodeError, OSError):
            pass

    tests_dir = root / "tests"
    if not tests_dir.exists():
        return False
    for test_file in tests_dir.rglob("test_*.py"):
        try:
            content = test_file.read_text()
            if "pymutant" in content:
                return True
        except OSError:
            continue
    return False


def _dependency_preflight(root: Path, cmd_prefix: list[str]) -> str | None:
    if len(cmd_prefix) < 2 or cmd_prefix[1] != "-m":
        return None

    python_bin = cmd_prefix[0]
    checks = ["import mutmut"]
    if _requires_mcp_dependency(root):
        checks.append("import mcp")

    for check in checks:
        result = subprocess.run(  # noqa: S603  # nosec
            [python_bin, "-c", check],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            module = check.replace("import ", "")
            return (
                f"Dependency preflight failed: cannot import {module!r} in {python_bin}. Run `uv sync` in this project."
            )
    return None


def _terminate_process_tree(proc: subprocess.Popen[str], grace_seconds: int = 3) -> None:
    if proc.poll() is not None:
        return

    if os.name != "nt":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            proc.terminate()
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
    else:
        proc.terminate()
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()


def _run_cmd(cmd: list[str], root: Path) -> dict[str, object]:
    try:
        proc = subprocess.Popen(  # noqa: S603,S607  # nosec
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "mutmut not found — install it in the target project with `uv add mutmut`",
            "summary": "mutmut not found",
        }

    start = time.monotonic()
    last_output = start
    out_seen = ""
    err_seen = ""

    while True:
        try:
            stdout, stderr = proc.communicate(timeout=1)
            break
        except subprocess.TimeoutExpired as exc:
            now = time.monotonic()
            partial_out_obj = exc.output or ""
            partial_err_obj = exc.stderr or ""
            partial_out = (
                partial_out_obj.decode(errors="replace") if isinstance(partial_out_obj, bytes) else partial_out_obj
            )
            partial_err = (
                partial_err_obj.decode(errors="replace") if isinstance(partial_err_obj, bytes) else partial_err_obj
            )

            if len(partial_out) > len(out_seen) or len(partial_err) > len(err_seen):
                last_output = now
                out_seen = partial_out
                err_seen = partial_err

            if now - start >= MUTMUT_TIMEOUT:
                _terminate_process_tree(proc)
                return {
                    "returncode": -1,
                    "stdout": out_seen,
                    "stderr": "mutmut run timed out after 30 minutes",
                    "summary": "Timed out",
                }

            if now - last_output >= MUTMUT_NO_PROGRESS_TIMEOUT:
                _terminate_process_tree(proc)
                return {
                    "returncode": -1,
                    "stdout": out_seen,
                    "stderr": (
                        "mutmut run stalled with no new output for "
                        f"{MUTMUT_NO_PROGRESS_TIMEOUT} seconds; terminated process tree"
                    ),
                    "summary": "Stalled",
                }
        except FileNotFoundError:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": "mutmut not found — install it in the target project with `uv add mutmut`",
                "summary": "mutmut not found",
            }

    combined = stdout + stderr
    return {
        "returncode": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "summary": _extract_summary(combined),
    }


def run_mutations(
    paths: list[str] | None = None,
    max_children: int | None = None,
    strict_campaign: bool = False,
    changed_only: bool = False,
    base_ref: str | None = None,
    project_root: Path | None = None,
) -> dict:
    """Run `mutmut run` and return structured output."""
    root = _project_root_or_cwd(project_root)
    cmd_prefix = _mutmut_cmd_prefix(root)
    preflight_error = _dependency_preflight(root, cmd_prefix)
    if preflight_error:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": preflight_error,
            "summary": "dependency preflight failed",
        }

    pending_names: list[str] = []
    batch_names: list[str] = []
    changed_paths: list[str] = []
    strict_campaign_state: StrictCampaign | None = None
    cmd = cmd_prefix + ["run"]
    if paths:
        cmd.extend(paths)
        strict_campaign = False
        changed_only = False
    elif changed_only:
        changed_paths, changed_error = _resolve_changed_paths_for_mutation(root, base_ref=base_ref)
        if changed_error:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": changed_error,
                "summary": "changed file detection failed",
                "changed_only": True,
            }
        if not changed_paths:
            return {
                "returncode": 0,
                "stdout": "",
                "stderr": "",
                "summary": "no changed python files under mutation roots",
                "batched": False,
                "batch_size": 0,
                "strict_campaign": False,
                "remaining_not_checked": 0,
                "changed_only": True,
                "changed_paths": [],
            }
        cmd.extend(changed_paths)
        strict_campaign = False
    else:
        if strict_campaign:
            strict_campaign_state = _init_or_load_strict_campaign(root)
            pending_names = _strict_remaining_names(root, strict_campaign_state)
            if not pending_names:
                return {
                    "returncode": 0,
                    "stdout": "",
                    "stderr": "",
                    "summary": "strict campaign complete; nothing to run",
                    "batched": False,
                    "batch_size": 0,
                    "strict_campaign": True,
                    "campaign_total": len(strict_campaign_state["names"]),
                    "campaign_attempted": len(strict_campaign_state["attempted"]),
                    "campaign_stale": len(strict_campaign_state["stale"]),
                    "remaining_not_checked": 0,
                }
            batch_names = pending_names[: _batch_size()]
            cmd.extend(batch_names)
        else:
            pending_names = _load_not_checked_mutants(root)
            if pending_names:
                batch_names = _select_batch_names(pending_names, root, _batch_size())
                cmd.extend(batch_names)
    if max_children is not None:
        cmd.extend(["--max-children", str(max_children)])
    elif batch_names:
        cmd.extend(["--max-children", str(DEFAULT_BATCH_MAX_CHILDREN)])

    print(f"Running: {' '.join(cmd)} (cwd={root})", file=sys.stderr)  # MCP-safe log
    result = _run_cmd(cmd, root)
    if strict_campaign and strict_campaign_state is not None and batch_names:
        if isinstance(result.get("returncode"), int) and result["returncode"] != -1:
            attempted = sorted(set(strict_campaign_state["attempted"]).union(batch_names))
            strict_campaign_state["attempted"] = attempted
            _save_strict_campaign(root, strict_campaign_state)

    # mutmut can regenerate mutant keys between runs; refresh once if selectors went stale.
    stale_filter = "Filtered for specific mutants, but nothing matches"
    returncode = result.get("returncode")
    stale_marked = False
    if (
        strict_campaign
        and strict_campaign_state is not None
        and batch_names
        and isinstance(returncode, int)
        and returncode != 0
        and stale_filter in str(result.get("stderr", ""))
    ):
        merged_stale = sorted(set(strict_campaign_state["stale"]).union(batch_names))
        strict_campaign_state["stale"] = merged_stale
        _save_strict_campaign(root, strict_campaign_state)
        stale_marked = True
        result["returncode"] = 0
        result["summary"] = "strict campaign skipped stale selectors"
        err = str(result.get("stderr", "")).strip()
        result["stderr"] = f"{err}\nMarked stale selectors and continuing strict campaign.".strip()
        returncode = 0

    if (
        not strict_campaign
        and batch_names
        and isinstance(returncode, int)
        and returncode != 0
        and stale_filter in str(result.get("stderr", ""))
    ):
        pending_names = _load_not_checked_mutants(root)
        if pending_names:
            batch_names = _select_batch_names(pending_names, root, _batch_size())
            cmd = cmd_prefix + ["run", *batch_names]
            if max_children is not None:
                cmd.extend(["--max-children", str(max_children)])
            else:
                cmd.extend(["--max-children", str(DEFAULT_BATCH_MAX_CHILDREN)])
            print(f"Retrying with refreshed batch: {' '.join(cmd)} (cwd={root})", file=sys.stderr)
            result = _run_cmd(cmd, root)
            returncode = result.get("returncode")

    # Last-resort recovery: selector IDs can still go stale after refresh.
    # Fall back to unfiltered `mutmut run` once to re-anchor progress.
    if (
        not strict_campaign
        and batch_names
        and isinstance(returncode, int)
        and returncode != 0
        and stale_filter in str(result.get("stderr", ""))
    ):
        cmd = cmd_prefix + ["run"]
        if max_children is not None:
            cmd.extend(["--max-children", str(max_children)])
        else:
            cmd.extend(["--max-children", str(DEFAULT_BATCH_MAX_CHILDREN)])
        print(f"Falling back to unfiltered run: {' '.join(cmd)} (cwd={root})", file=sys.stderr)
        result = _run_cmd(cmd, root)

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

    result["batched"] = bool(batch_names)
    result["batch_size"] = len(batch_names)
    if strict_campaign and strict_campaign_state is not None:
        campaign_remaining = _strict_remaining_names(root, strict_campaign_state)
        result["strict_campaign"] = True
        result["campaign_total"] = len(strict_campaign_state["names"])
        result["campaign_attempted"] = len(strict_campaign_state["attempted"])
        result["campaign_stale"] = len(strict_campaign_state["stale"])
        result["remaining_not_checked"] = len(campaign_remaining)
    else:
        result["strict_campaign"] = False
        result["remaining_not_checked"] = max(0, len(pending_names) - len(batch_names))
    result["changed_only"] = changed_only
    if changed_only:
        result["changed_paths"] = changed_paths
    return result


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
    root_key = str(root.resolve())
    _PENDING_CURSOR_BY_ROOT.pop(root_key, None)
    campaign_path = _strict_campaign_path(root)
    if not campaign_path.exists():
        return False
    campaign_path.unlink()
    return True


def kill_stuck_mutmut(project_root: Path | None = None) -> dict:
    """Kill stuck mutmut/pytest workers related to mutation runs."""
    root = _project_root_or_cwd(project_root)
    if shutil.which("pkill") is None:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "pkill is not available on this system",
            "summary": "cleanup unavailable",
        }

    patterns = [
        f"{root}/mutants",
        "python -m mutmut",
        "mutmut run",
        "MUTANT_UNDER_TEST",
    ]
    details: list[dict[str, object]] = []
    killed_any = False
    for pattern in patterns:
        result = subprocess.run(  # noqa: S603  # nosec
            ["pkill", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=5,
        )
        killed = result.returncode == 0
        killed_any = killed_any or killed
        details.append(
            {
                "pattern": pattern,
                "killed": killed,
                "returncode": result.returncode,
            }
        )

    return {
        "ok": True,
        "killed_any": killed_any,
        "details": details,
    }
