# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess  # nosec B404
import time
import tomllib
from pathlib import Path
from typing import TypedDict

from pymutant.io_utils import atomic_write_text
from pymutant.ledger import append_ledger_event
from pymutant.mutmut_cmd import mutmut_cmd_prefix, preferred_python
from pymutant.results import EXIT_CODE_STATUS

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


class MetaSanitizeSummary(TypedDict):
    scanned: int
    invalid_removed: int
    removed_paths: list[str]


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
    resolved_mutation_roots = [(root / p).resolve() for p in mutation_roots]
    normalized: set[str] = set()
    for raw in candidates:
        candidate = raw.strip().replace("\\", "/")
        if not candidate.endswith(".py") or candidate.startswith("/"):
            continue
        file_path = (root / candidate).resolve()
        if not file_path.exists() or not file_path.is_file():
            continue
        rel = str(file_path.relative_to(root.resolve())).replace("\\", "/")
        if resolved_mutation_roots:
            in_roots = any(file_path == root_path or root_path in file_path.parents for root_path in resolved_mutation_roots)
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


def _sanitize_mutant_meta_files(root: Path) -> MetaSanitizeSummary:
    meta_dir = root / "mutants"
    summary: MetaSanitizeSummary = {"scanned": 0, "invalid_removed": 0, "removed_paths": []}
    if not meta_dir.exists():
        return summary

    for meta_file in meta_dir.rglob("*.meta"):
        summary["scanned"] += 1
        try:
            json.loads(meta_file.read_text())
        except (json.JSONDecodeError, OSError):
            try:
                meta_file.unlink()
            except OSError:
                continue
            summary["invalid_removed"] += 1
            summary["removed_paths"].append(str(meta_file))
    return summary


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


def _refresh_strict_campaign_names(root: Path, campaign: StrictCampaign) -> StrictCampaign:
    refreshed_names = _load_not_checked_mutants(root)
    refreshed_set = set(refreshed_names)
    return {
        "names": refreshed_names,
        "stale": sorted({name for name in campaign["stale"] if name in refreshed_set}),
        "attempted": sorted({name for name in campaign["attempted"] if name in refreshed_set}),
    }


def _strict_remaining_names(root: Path, campaign: StrictCampaign) -> list[str]:
    attempted = set(campaign["attempted"])
    _ = _load_exit_codes_by_key(root)
    return [name for name in campaign["names"] if name not in attempted]


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
            return f"Dependency preflight failed: cannot import {module!r} in {python_bin}. Run `uv sync` in this project."
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
        proc = subprocess.Popen(  # noqa: S603  # nosec
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
            partial_out = partial_out_obj.decode(errors="replace") if isinstance(partial_out_obj, bytes) else partial_out_obj
            partial_err = partial_err_obj.decode(errors="replace") if isinstance(partial_err_obj, bytes) else partial_err_obj

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


def _noop_payload(summary: str, *, strict_campaign: bool, changed_only: bool = False) -> dict[str, object]:
    return {
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "summary": summary,
        "batched": False,
        "batch_size": 0,
        "strict_campaign": strict_campaign,
        "remaining_not_checked": 0,
        "changed_only": changed_only,
    }
