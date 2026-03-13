# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from .io_utils import atomic_write_text

LEDGER_FILE = ".pymutant-ledger.json"
TERMINAL_STATUSES = {
    "killed",
    "survived",
    "no_tests",
    "timeout",
    "segfault",
    "skipped",
    "suspicious",
    "typecheck_failed",
    "interrupted",
    "stale",
}


class LedgerEvent(TypedDict):
    timestamp: str
    context: str
    mutants: dict[str, str]


class LedgerData(TypedDict):
    events: list[LedgerEvent]


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _ledger_path(project_root: Path | None = None) -> Path:
    return _project_root_or_cwd(project_root) / LEDGER_FILE


def load_ledger(project_root: Path | None = None) -> LedgerData:
    path = _ledger_path(project_root)
    if not path.exists():
        return {"events": []}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"events": []}
    if not isinstance(data, dict):
        return {"events": []}
    events = data.get("events")
    if not isinstance(events, list):
        return {"events": []}
    normalized: list[LedgerEvent] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        mutants_raw = event.get("mutants")
        if not isinstance(mutants_raw, dict):
            continue
        mutants = {k: v for k, v in mutants_raw.items() if isinstance(k, str) and isinstance(v, str)}
        normalized.append(
            {
                "timestamp": str(event.get("timestamp", "")),
                "context": str(event.get("context", "unknown")),
                "mutants": mutants,
            }
        )
    return {"events": normalized}


def append_ledger_event(
    mutant_status_by_name: dict[str, str],
    context: str,
    project_root: Path | None = None,
) -> None:
    if not mutant_status_by_name:
        return
    data = load_ledger(project_root)
    filtered = {k: v for k, v in mutant_status_by_name.items() if isinstance(k, str) and isinstance(v, str)}
    if not filtered:
        return
    data["events"].append(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "context": context,
            "mutants": filtered,
        }
    )
    atomic_write_text(_ledger_path(project_root), json.dumps(data, indent=2) + "\n")


def resolve_latest_statuses(project_root: Path | None = None) -> dict[str, str]:
    statuses: dict[str, str] = {}
    data = load_ledger(project_root)
    for event in data["events"]:
        for name, status in event["mutants"].items():
            if status in TERMINAL_STATUSES:
                statuses[name] = status
            elif name not in statuses:
                statuses[name] = "not_checked"
    return statuses


def ledger_status(project_root: Path | None = None) -> dict[str, object]:
    path = _ledger_path(project_root)
    data = load_ledger(project_root)
    statuses = resolve_latest_statuses(project_root)
    counts: dict[str, int] = {}
    for status in statuses.values():
        counts[status] = counts.get(status, 0) + 1
    return {
        "path": str(path),
        "exists": path.exists(),
        "events": len(data["events"]),
        "mutants_tracked": len(statuses),
        "counts": counts,
    }


def reset_ledger(project_root: Path | None = None) -> bool:
    path = _ledger_path(project_root)
    if not path.exists():
        return False
    path.unlink()
    return True
