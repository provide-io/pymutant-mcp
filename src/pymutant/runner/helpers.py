# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess  # nosec B404
import time
import tomllib
from pathlib import Path
from typing import TypedDict

from pymutant.config import get_env_batch_size
from pymutant.io_utils import atomic_write_text
from pymutant.ledger import append_ledger_event
from pymutant.mutmut_cmd import mutmut_cmd_prefix, preferred_python
from pymutant.results import EXIT_CODE_STATUS

MUTMUT_TIMEOUT = 30 * 60  # 30 minutes in seconds
MUTMUT_NO_PROGRESS_TIMEOUT = 5 * 60  # 5 minutes with no new output
DEFAULT_MUTANT_BATCH_SIZE = 10
DEFAULT_BATCH_MAX_CHILDREN = 2
MAX_CMD_OUTPUT_CHARS = 32_000
STRICT_CAMPAIGN_FILE = ".pymutant-strict-campaign.json"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SPINNER_LINE_RE = re.compile(r"^[\s|/\\\-\u2800-\u28ff]+\d+/\d+")
MUTMUT_PROGRESS_LINE_RE = re.compile(
    r"^(Generating mutants|Running (?:stats|clean tests|mutation tests|forced fail test|forced fail tests))$"
)
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
    return get_env_batch_size(DEFAULT_MUTANT_BATCH_SIZE, minimum=1)


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


def _load_meta_json(meta_file: Path, retries: int = 3, retry_delay_seconds: float = 0.05) -> dict[str, object] | None:
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


def _filter_changed_python_paths(root: Path, candidates: list[str]) -> list[str]:
    mutation_roots = _configured_mutation_roots(root)
    root_variants = [
        (configured_root, (root / configured_root).absolute(), (root / configured_root).resolve())
        for configured_root in mutation_roots
    ]
    normalized: set[str] = set()
    for raw in candidates:
        candidate = raw.strip().replace("\\", "/")
        if not candidate.endswith(".py"):
            continue
        file_path = Path(candidate)
        file_path = (root / file_path).absolute() if not file_path.is_absolute() else file_path.absolute()
        if not file_path.exists() or not file_path.is_file():
            continue
        try:
            rel = str(file_path.relative_to(root.absolute())).replace("\\", "/")
        except ValueError:
            continue
        if not root_variants:
            normalized.add(rel)
            continue

        mapped_paths: list[str] = []
        for configured_root, logical_root, resolved_root in root_variants:
            base_root: Path | None = None
            if file_path == logical_root or logical_root in file_path.parents:
                base_root = logical_root
            elif file_path == resolved_root or resolved_root in file_path.parents:
                base_root = resolved_root
            if base_root is None:
                continue

            suffix = str(file_path.relative_to(base_root)).replace("\\", "/")
            mapped = configured_root.strip().rstrip("/")
            if suffix and suffix != ".":
                mapped = f"{mapped}/{suffix}"
            mapped_paths.append(mapped)

        if mapped_paths:
            normalized.add(sorted(mapped_paths)[0])
    return sorted(normalized)


def _normalize_path_selectors(root: Path, selectors: list[str]) -> tuple[list[str], list[str]]:
    mutation_roots = _configured_mutation_roots(root)
    root_variants = [
        (configured_root, (root / configured_root).absolute(), (root / configured_root).resolve())
        for configured_root in mutation_roots
    ]
    normalized: list[str] = []
    ignored: list[str] = []

    for raw_selector in selectors:
        selector = raw_selector.strip()
        if not selector:
            ignored.append(raw_selector)
            continue
        if "__mutmut_" in selector:
            normalized.append(selector)
            continue
        if not selector.endswith(".py"):
            normalized.append(selector)
            continue

        file_path = Path(selector)
        file_path = (root / file_path).absolute() if not file_path.is_absolute() else file_path.absolute()
        if not file_path.exists() or not file_path.is_file():
            # Keep unresolved file selectors as-is; mutmut may still resolve them.
            normalized.append(selector)
            continue

        if not root_variants:
            try:
                normalized.append(str(file_path.relative_to(root.absolute())).replace("\\", "/"))
            except ValueError:
                normalized.append(selector)
            continue

        mapped_paths: list[str] = []
        for configured_root, logical_root, resolved_root in root_variants:
            base_root: Path | None = None
            if file_path == logical_root or logical_root in file_path.parents:
                base_root = logical_root
            elif file_path == resolved_root or resolved_root in file_path.parents:
                base_root = resolved_root
            if base_root is None:
                continue

            suffix = str(file_path.relative_to(base_root)).replace("\\", "/")
            mapped = configured_root.strip().rstrip("/")
            if suffix and suffix != ".":
                mapped = f"{mapped}/{suffix}"
            mapped_paths.append(mapped)

        if mapped_paths:
            normalized.append(sorted(mapped_paths)[0])
        else:
            normalized.append(selector)

    # Preserve caller intent while avoiding duplicate selectors.
    return list(dict.fromkeys(normalized)), ignored


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
        data = _load_meta_json(meta_file)
        if data is None:
            continue
        exit_code_by_key = data.get("exit_code_by_key", {})
        if not isinstance(exit_code_by_key, dict):
            continue
        for name, exit_code in exit_code_by_key.items():
            if isinstance(name, str) and exit_code is None:
                names.append(name)
    return sorted(names)


def _sanitize_mutant_meta_files(root: Path) -> MetaSanitizeSummary:
    meta_dir = root / "mutants"
    summary: MetaSanitizeSummary = {"scanned": 0, "invalid_removed": 0, "removed_paths": []}
    if not meta_dir.exists():
        return summary

    for meta_file in meta_dir.rglob("*.meta"):
        summary["scanned"] += 1
        if _load_meta_json(meta_file) is not None:
            continue
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
        data = _load_meta_json(meta_file)
        if data is None:
            continue
        exit_code_by_key = data.get("exit_code_by_key", {})
        if not isinstance(exit_code_by_key, dict):
            continue
        for name, code in exit_code_by_key.items():
            exit_codes[str(name)] = code if isinstance(code, int) or code is None else None
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


def _strict_remaining_names(_root: Path, campaign: StrictCampaign) -> list[str]:
    attempted = set(campaign["attempted"])
    stale = set(campaign["stale"])
    return [name for name in campaign["names"] if name not in attempted and name not in stale]


def _select_batch_names(pending_names: list[str], root: Path, batch_size: int) -> list[str]:
    _ = root
    if not pending_names:
        return []
    batch_take = min(max(1, batch_size), len(pending_names))
    return pending_names[:batch_take]


def _requires_mcp_dependency(root: Path) -> bool:
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            mutmut_cfg = data.get("tool", {}).get("mutmut", {})
            paths = mutmut_cfg.get("paths_to_mutate", [])
            if isinstance(paths, str):
                paths = [paths]
            if isinstance(paths, list) and any(str(p).startswith("src/pymutant") for p in paths):
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


def _run_cmd(cmd: list[str], root: Path, *, compact_progress: bool = True) -> dict[str, object]:
    try:
        with subprocess.Popen(  # noqa: S603  # nosec
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        ) as proc:
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
                        partial_out_obj.decode(errors="replace")
                        if isinstance(partial_out_obj, bytes)
                        else partial_out_obj
                    )
                    partial_err = (
                        partial_err_obj.decode(errors="replace")
                        if isinstance(partial_err_obj, bytes)
                        else partial_err_obj
                    )

                    if len(partial_out) > len(out_seen) or len(partial_err) > len(err_seen):
                        last_output = now
                        out_seen = partial_out
                        err_seen = partial_err

                    if now - start >= MUTMUT_TIMEOUT:
                        _terminate_process_tree(proc)
                        out_sanitized = _sanitize_cmd_output(out_seen, compact_progress=compact_progress)
                        return {
                            "returncode": -1,
                            "stdout": out_sanitized,
                            "stderr": "mutmut run timed out after 30 minutes",
                            "summary": "Timed out",
                        }

                    if now - last_output >= MUTMUT_NO_PROGRESS_TIMEOUT:
                        _terminate_process_tree(proc)
                        out_sanitized = _sanitize_cmd_output(out_seen, compact_progress=compact_progress)
                        return {
                            "returncode": -1,
                            "stdout": out_sanitized,
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

            stdout = _sanitize_cmd_output(stdout, compact_progress=compact_progress)
            stderr = _sanitize_cmd_output(stderr, compact_progress=compact_progress)
            combined = stdout + stderr
            return {
                "returncode": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "summary": _extract_summary(combined),
            }
    except FileNotFoundError:
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": "mutmut not found — install it in the target project with `uv add mutmut`",
            "summary": "mutmut not found",
        }


def _compact_progress_lines(lines: list[str]) -> list[str]:
    compacted: list[str] = []
    previous_progress_line: str | None = None
    for line in lines:
        if not line:
            if compacted and compacted[-1]:
                compacted.append(line)
            continue
        if MUTMUT_PROGRESS_LINE_RE.match(line):
            if line == previous_progress_line:
                continue
            previous_progress_line = line
            compacted.append(line)
            continue
        previous_progress_line = None
        compacted.append(line)
    while compacted and compacted[-1] == "":
        compacted.pop()
    return compacted


def _sanitize_cmd_output(output: str, *, compact_progress: bool = True) -> str:
    if not output:
        return ""
    text = output.replace("\r\n", "\n").replace("\r", "\n")
    text = ANSI_ESCAPE_RE.sub("", text)
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if SPINNER_LINE_RE.match(line):
            continue
        cleaned_lines.append(line)
    if compact_progress:
        cleaned_lines = _compact_progress_lines(cleaned_lines)
    compact = "\n".join(cleaned_lines).strip()
    if len(compact) <= MAX_CMD_OUTPUT_CHARS:
        return compact
    reserve = min(120, max(10, MAX_CMD_OUTPUT_CHARS // 2))
    keep = max(1, MAX_CMD_OUTPUT_CHARS - reserve)
    omitted = len(compact) - keep
    return f"{compact[:keep]}\n\n[output truncated: omitted {omitted} characters]"


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
