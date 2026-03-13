# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .io_utils import atomic_write_text
from .schema import now_iso, with_schema

QUARANTINE_FILE = ".pymutant-quarantine.json"
TRANSIENT_MARKERS = (
    "timed out",
    "stalled",
    "no new output",
    "filtered for specific mutants, but nothing matches",
    "interrupted",
)


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _path(project_root: Path | None = None) -> Path:
    return _project_root_or_cwd(project_root) / QUARANTINE_FILE


def load_quarantine(project_root: Path | None = None) -> dict[str, Any]:
    path = _path(project_root)
    if not path.exists():
        return with_schema({"entries": []})
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return with_schema({"entries": []})
    if not isinstance(data, dict):
        return with_schema({"entries": []})
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    return with_schema({"entries": [e for e in entries if isinstance(e, dict)]})


def classify_transient_failure(run_result: dict[str, Any]) -> tuple[bool, str]:
    summary = str(run_result.get("summary", "")).lower()
    stderr = str(run_result.get("stderr", "")).lower()
    code = int(run_result.get("returncode", 0))
    text = f"{summary}\n{stderr}"
    if code in (-15, -9, -1):
        return True, "interruption_or_timeout"
    if any(marker in text for marker in TRANSIENT_MARKERS):
        return True, "transient_runtime"
    return False, "non_transient"


def confidence_score(*, repeatability: float, consistency: float, cleanup_success: float) -> float:
    raw = 0.5 * repeatability + 0.3 * consistency + 0.2 * cleanup_success
    return round(max(0.0, min(1.0, raw)), 4)


def record_quarantine(
    mutant_names: list[str],
    *,
    reason: str,
    repeatability: float,
    consistency: float,
    cleanup_success: float,
    project_root: Path | None = None,
) -> dict[str, Any]:
    data = load_quarantine(project_root)
    confidence = confidence_score(
        repeatability=repeatability,
        consistency=consistency,
        cleanup_success=cleanup_success,
    )
    entry = {
        "timestamp": now_iso(),
        "reason": reason,
        "confidence": confidence,
        "mutants": sorted(set(mutant_names)),
    }
    data["entries"].append(entry)
    atomic_write_text(_path(project_root), json.dumps(with_schema(data), indent=2) + "\n")
    return entry
