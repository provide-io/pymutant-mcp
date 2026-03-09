# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .ledger import load_ledger
from .results import get_results


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _file_churn(root: Path, source_file: str) -> float:
    try:
        result = subprocess.run(  # noqa: S603  # nosec
            ["git", "log", "--oneline", "--", source_file],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    if result.returncode != 0:
        return 0.0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return float(len(lines))


def rank_survivors(project_root: Path | None = None, top_n: int = 50) -> dict[str, Any]:
    root = _project_root_or_cwd(project_root)
    all_data = get_results(include_killed=True, project_root=root)
    survivors = [m for m in all_data["mutants"] if m["status"] == "survived"]
    if not survivors:
        return {"weights": {"impact": 0.5, "frequency": 0.3, "churn": 0.2}, "survivors": []}

    survivors_by_file: dict[str, int] = {}
    mutants_by_file: dict[str, int] = {}
    for mutant in all_data["mutants"]:
        source = str(mutant["source_file"])
        mutants_by_file[source] = mutants_by_file.get(source, 0) + 1
        if mutant["status"] == "survived":
            survivors_by_file[source] = survivors_by_file.get(source, 0) + 1

    ledger = load_ledger(root)
    survived_frequency: dict[str, int] = {}
    for event in ledger["events"]:
        for name, status in event["mutants"].items():
            if status == "survived":
                survived_frequency[name] = survived_frequency.get(name, 0) + 1

    raw_rows: list[dict[str, Any]] = []
    for mutant in survivors:
        name = str(mutant["name"])
        source = str(mutant["source_file"])
        impact = survivors_by_file.get(source, 0) / max(mutants_by_file.get(source, 1), 1)
        freq = float(survived_frequency.get(name, 0))
        churn = _file_churn(root, source)
        raw_rows.append({"name": name, "source_file": source, "impact": impact, "frequency": freq, "churn": churn})

    max_freq = max(r["frequency"] for r in raw_rows) or 1.0
    max_churn = max(r["churn"] for r in raw_rows) or 1.0

    ranked: list[dict[str, Any]] = []
    for row in raw_rows:
        norm_freq = row["frequency"] / max_freq
        norm_churn = row["churn"] / max_churn
        priority = round(0.5 * row["impact"] + 0.3 * norm_freq + 0.2 * norm_churn, 4)
        ranked.append(
            {
                "name": row["name"],
                "source_file": row["source_file"],
                "impact": round(row["impact"], 4),
                "frequency": row["frequency"],
                "churn": row["churn"],
                "priority": priority,
            }
        )

    ranked.sort(key=lambda x: (-x["priority"], -x["impact"], -x["frequency"], x["source_file"], x["name"]))
    return {
        "weights": {"impact": 0.5, "frequency": 0.3, "churn": 0.2},
        "survivors": ranked[: max(1, top_n)],
    }
