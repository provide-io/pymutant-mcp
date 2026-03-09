# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import TypeAlias

from .results import get_results

ScoreEntry: TypeAlias = dict[str, object]
ScoreHistory: TypeAlias = dict[str, list[ScoreEntry]]

SCORE_FILE = "mutation-score.json"


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _score_file_path(project_root: Path | None = None) -> Path:
    return _project_root_or_cwd(project_root) / SCORE_FILE


def compute_score(project_root: Path | None = None) -> dict:
    """Compute mutation score from current meta files.

    Score = killed / (killed + survived + timeout + segfault).
    Excludes no_tests, skipped, not_checked, suspicious from the denominator.
    `crash` is kept as a backward-compatible alias of `segfault`.
    """
    root = _project_root_or_cwd(project_root)
    data = get_results(include_killed=True, use_ledger=True, project_root=root)
    counts = data["counts"]

    killed = counts.get("killed", 0)
    survived = counts.get("survived", 0)
    no_tests = counts.get("no_tests", 0)
    timeout = counts.get("timeout", 0)
    segfault = counts.get("segfault", 0) + counts.get("crash", 0)
    crash = segfault
    skipped = counts.get("skipped", 0)
    stale = counts.get("stale", 0)
    not_checked = counts.get("not_checked", 0)

    denominator = killed + survived + timeout + segfault
    score = killed / denominator if denominator > 0 else 0.0

    return {
        "score": round(score, 4),
        "score_pct": f"{score:.1%}",
        "killed": killed,
        "survived": survived,
        "no_tests": no_tests,
        "timeout": timeout,
        "segfault": segfault,
        "crash": crash,
        "skipped": skipped,
        "stale": stale,
        "suspicious": counts.get("suspicious", 0),
        "typecheck_failed": counts.get("typecheck_failed", 0),
        "interrupted": counts.get("interrupted", 0),
        "not_checked": not_checked,
        "total": data["total"],
    }


def load_score_history(project_root: Path | None = None) -> ScoreHistory:
    """Load score history from mutation-score.json, returning empty history if absent."""
    score_file = _score_file_path(project_root)
    if not score_file.exists():
        return {"history": []}
    try:
        return json.loads(score_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {"history": []}


def update_score_history(
    label: str | None = None,
    project_root: Path | None = None,
) -> dict:
    """Append current score to mutation-score.json and return the new entry."""
    root = _project_root_or_cwd(project_root)
    current = compute_score(root)

    entry: ScoreEntry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "score": current["score"],
        "killed": current["killed"],
        "survived": current["survived"],
        "no_tests": current["no_tests"],
        "timeout": current["timeout"],
        "total": current["total"],
    }
    if label:
        entry["label"] = label

    history = load_score_history(root)
    history["history"].append(entry)

    score_file = _score_file_path(root)
    score_file.write_text(json.dumps(history, indent=2))

    return {"entry": entry, "history_length": len(history["history"])}
