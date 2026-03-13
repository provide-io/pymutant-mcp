# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .profiles import resolve_profile
from .schema import with_schema

BASELINE_FILE = ".ci/pymutant-policy-baseline.json"


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _load_baseline(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_baseline_path(root: Path, baseline_path: str | None) -> Path:
    if baseline_path is None:
        return (root / BASELINE_FILE).resolve()
    path = Path(baseline_path).expanduser()
    return path if path.is_absolute() else (root / path).resolve()


def evaluate_policy(
    *,
    current_score: float,
    profile: str | None = None,
    config_path: str | None = None,
    baseline_path: str | None = None,
    runtime_baseline: dict[str, Any] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = _project_root_or_cwd(project_root)
    resolved = resolve_profile(profile=profile, config_path=config_path, project_root=root)
    active = resolved["profile"]
    policy_cfg = active.get("policy", {}) if isinstance(active.get("policy", {}), dict) else {}

    baseline_file = _resolve_baseline_path(root, baseline_path)
    baseline = _load_baseline(baseline_file)
    baseline_profiles = baseline.get("profiles", {}) if isinstance(baseline.get("profiles", {}), dict) else {}
    baseline_score = float(
        baseline_profiles.get(active.get("name", "default"), {}).get("baseline_score", current_score)
        if isinstance(baseline_profiles.get(active.get("name", "default"), {}), dict)
        else current_score
    )

    min_score = float(policy_cfg.get("min_score", 0.0))
    max_drop = float(policy_cfg.get("max_drop_from_baseline", 0.0))
    drop = round(baseline_score - current_score, 4)

    failures: list[str] = []
    runtime_valid = True
    runtime_reasons: list[str] = []
    if isinstance(runtime_baseline, dict):
        runtime_valid = bool(runtime_baseline.get("valid", False))
        reasons = runtime_baseline.get("reasons", [])
        if isinstance(reasons, list):
            runtime_reasons = [str(reason) for reason in reasons]
    if current_score < min_score:
        failures.append(f"score below floor: {current_score} < {min_score}")
    if not runtime_valid:
        reasons_text = ", ".join(runtime_reasons) if runtime_reasons else "unknown"
        failures.append(f"baseline invalid: {reasons_text}")
    if drop > max_drop:
        failures.append(f"score dropped vs baseline: {drop} > {max_drop}")

    return with_schema(
        {
            "ok": not failures,
            "failures": failures,
            "profile": resolved,
            "policy": {
                "baseline_path": str(baseline_file),
                "baseline_score": baseline_score,
                "current_score": current_score,
                "drop": drop,
                "min_score": min_score,
                "max_drop_from_baseline": max_drop,
                "runtime_baseline_valid": runtime_valid,
                "runtime_baseline_reasons": runtime_reasons,
            },
        }
    )
