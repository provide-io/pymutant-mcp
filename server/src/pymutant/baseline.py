# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess  # nosec B404
import sys
import tomllib
from pathlib import Path
from typing import Any

from .mutmut_cmd import mutmut_cmd_prefix
from .profiles import resolve_profile
from .schema import with_schema

STATE_DIR = ".pymutant-state"
BASELINE_FILE = "baseline.json"
STRICT_CAMPAIGN_FILE = ".pymutant-strict-campaign.json"
LEDGER_FILE = ".pymutant-ledger.json"


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _baseline_path(project_root: Path) -> Path:
    return project_root / STATE_DIR / BASELINE_FILE


def _runtime_state_paths(project_root: Path) -> dict[str, Path]:
    return {
        "mutants_dir": project_root / "mutants",
        "strict_campaign": project_root / STRICT_CAMPAIGN_FILE,
        "ledger": project_root / LEDGER_FILE,
    }


def _read_pyproject_mutmut(project_root: Path) -> dict[str, Any]:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    try:
        data = tomllib.loads(pyproject.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return {}
    cfg = data.get("tool", {}).get("mutmut", {})
    return cfg if isinstance(cfg, dict) else {}


def _normalize_paths(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _resolve_paths(project_root: Path, paths: list[str]) -> list[str]:
    resolved: list[str] = []
    for path in paths:
        candidate = (project_root / path).resolve()
        resolved.append(str(candidate))
    return sorted(set(resolved))


def _git_head(project_root: Path) -> str:
    if shutil.which("git") is None:
        return "unknown"
    try:
        result = subprocess.run(  # nosec
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    value = result.stdout.strip()
    return value if value else "unknown"


def _mutmut_version(project_root: Path) -> str:
    cmd = [*mutmut_cmd_prefix(project_root), "--version"]
    try:
        result = subprocess.run(  # noqa: S603  # nosec
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    output = (stdout or stderr).strip()
    if not output:
        return "unknown"
    return output.splitlines()[0].strip()


def _meta_snapshot(project_root: Path) -> dict[str, Any]:
    paths = _runtime_state_paths(project_root)
    mutants_dir = paths["mutants_dir"]
    meta_count = len(list(mutants_dir.rglob("*.meta"))) if mutants_dir.exists() else 0
    return {
        "meta_count": meta_count,
        "campaign_exists": paths["strict_campaign"].exists(),
        "ledger_exists": paths["ledger"].exists(),
    }


def _profile_block(project_root: Path, profile: str | None, config_path: str | None) -> dict[str, Any]:
    resolved = resolve_profile(profile=profile, config_path=config_path, project_root=project_root)
    canonical = json.dumps(resolved["profile"], sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {
        "name": resolved["profile"].get("name", "default"),
        "config_path": resolved["config_path"],
        "hash": digest,
    }


def _build_context(
    project_root: Path,
    *,
    command_mode: str,
    profile: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    mutmut_cfg = _read_pyproject_mutmut(project_root)
    mutation_roots = _resolve_paths(project_root, _normalize_paths(mutmut_cfg.get("paths_to_mutate", [])))
    tests_roots = _resolve_paths(project_root, _normalize_paths(mutmut_cfg.get("tests_dir", [])))
    return {
        "git_head": _git_head(project_root),
        "python_version": ".".join(str(part) for part in sys.version_info[:3]),
        "mutmut_version": _mutmut_version(project_root),
        "mutation_roots": mutation_roots,
        "tests_roots": tests_roots,
        "profile": _profile_block(project_root, profile, config_path),
        "command_mode": command_mode,
        "meta_snapshot": _meta_snapshot(project_root),
    }


def _fingerprint_id(context: dict[str, Any]) -> str:
    payload = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_state(project_root: Path) -> dict[str, Any] | None:
    path = _baseline_path(project_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_state(project_root: Path, context: dict[str, Any], fingerprint_id: str) -> dict[str, Any]:
    payload = with_schema(
        {
            "fingerprint_id": fingerprint_id,
            "context": context,
        }
    )
    path = _baseline_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def _drift_reasons(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    if previous is None:
        return ["missing_baseline"]
    previous_ctx = previous.get("context")
    if not isinstance(previous_ctx, dict):
        return ["invalid_baseline_payload"]

    reasons: list[str] = []
    fields = (
        ("git_head", "git_head_changed"),
        ("python_version", "python_version_changed"),
        ("mutmut_version", "mutmut_version_changed"),
        ("mutation_roots", "mutation_roots_changed"),
        ("tests_roots", "tests_roots_changed"),
    )
    for key, reason in fields:
        if previous_ctx.get(key) != current.get(key):
            reasons.append(reason)

    prev_profile = previous_ctx.get("profile", {}) if isinstance(previous_ctx.get("profile"), dict) else {}
    cur_profile = current.get("profile", {}) if isinstance(current.get("profile"), dict) else {}
    if prev_profile.get("name") != cur_profile.get("name"):
        reasons.append("profile_name_changed")
    if prev_profile.get("config_path") != cur_profile.get("config_path"):
        reasons.append("profile_config_changed")
    if prev_profile.get("hash") != cur_profile.get("hash"):
        reasons.append("profile_hash_changed")

    return reasons


def reset_runtime_state(project_root: Path) -> dict[str, Any]:
    paths = _runtime_state_paths(project_root)
    removed_meta = 0
    mutants_dir = paths["mutants_dir"]
    if mutants_dir.exists():
        for meta_file in mutants_dir.rglob("*.meta"):
            try:
                meta_file.unlink()
                removed_meta += 1
            except OSError:
                continue

    removed_campaign = False
    campaign_path = paths["strict_campaign"]
    if campaign_path.exists():
        campaign_path.unlink()
        removed_campaign = True

    removed_ledger = False
    ledger_path = paths["ledger"]
    if ledger_path.exists():
        ledger_path.unlink()
        removed_ledger = True

    return {
        "removed_meta_files": removed_meta,
        "removed_campaign": removed_campaign,
        "removed_ledger": removed_ledger,
    }


def baseline_status(
    *,
    project_root: Path | None = None,
    command_mode: str,
    profile: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    root = _project_root_or_cwd(project_root)
    current = _build_context(root, command_mode=command_mode, profile=profile, config_path=config_path)
    current_fingerprint = _fingerprint_id(current)
    previous = _load_state(root)
    reasons = _drift_reasons(previous, current)
    valid = len(reasons) == 0
    return with_schema(
        {
            "valid": valid,
            "was_invalid": not valid,
            "reasons": reasons,
            "fingerprint_id": current_fingerprint,
            "auto_reset_applied": False,
            "state_path": str(_baseline_path(root)),
            "context": current,
        }
    )


def ensure_runtime_baseline(
    *,
    project_root: Path | None = None,
    command_mode: str,
    profile: str | None = None,
    config_path: str | None = None,
    auto_reset: bool = True,
) -> dict[str, Any]:
    root = _project_root_or_cwd(project_root)
    status = baseline_status(
        project_root=root,
        command_mode=command_mode,
        profile=profile,
        config_path=config_path,
    )
    if status["valid"]:
        return status

    if not auto_reset:
        return status

    reset = reset_runtime_state(root)
    context = _build_context(root, command_mode=command_mode, profile=profile, config_path=config_path)
    fingerprint = _fingerprint_id(context)
    _write_state(root, context, fingerprint)
    return with_schema(
        {
            "valid": True,
            "was_invalid": True,
            "reasons": status["reasons"],
            "fingerprint_id": fingerprint,
            "auto_reset_applied": True,
            "state_path": str(_baseline_path(root)),
            "context": context,
            "reset": reset,
        }
    )


def refresh_baseline(
    *,
    project_root: Path | None = None,
    command_mode: str = "manual_refresh",
    profile: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    root = _project_root_or_cwd(project_root)
    reset = reset_runtime_state(root)
    context = _build_context(root, command_mode=command_mode, profile=profile, config_path=config_path)
    fingerprint = _fingerprint_id(context)
    _write_state(root, context, fingerprint)
    return with_schema(
        {
            "valid": True,
            "was_invalid": False,
            "reasons": [],
            "fingerprint_id": fingerprint,
            "auto_reset_applied": True,
            "state_path": str(_baseline_path(root)),
            "context": context,
            "reset": reset,
        }
    )
