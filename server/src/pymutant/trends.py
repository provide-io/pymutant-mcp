# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any


def compute_module_scores(mutants: list[dict[str, Any]]) -> dict[str, float]:
    buckets: dict[str, dict[str, int]] = {}
    for mutant in mutants:
        source_file = str(mutant.get("source_file", "unknown.py"))
        module = source_file[:-3] if source_file.endswith(".py") else source_file
        bucket = buckets.setdefault(module, {"killed": 0, "survived": 0, "timeout": 0, "segfault": 0})
        status = str(mutant.get("status", ""))
        if status in bucket:
            bucket[status] += 1

    scores: dict[str, float] = {}
    for module, counts in buckets.items():
        denom = counts["killed"] + counts["survived"] + counts["timeout"] + counts["segfault"]
        scores[module] = round((counts["killed"] / denom) if denom else 0.0, 4)
    return scores


def trend_report(history: dict[str, Any], window: int = 5) -> dict[str, Any]:
    entries = history.get("history", []) if isinstance(history.get("history", []), list) else []
    if len(entries) < 2:
        return {"entries": len(entries), "alerts": [], "drift": 0.0}

    last = entries[-1]
    previous = entries[-2]
    current_score = float(last.get("score", 0.0))
    previous_score = float(previous.get("score", 0.0))
    drift = round(current_score - previous_score, 4)

    alerts: list[dict[str, Any]] = []
    if drift < 0:
        alerts.append({"level": "warn", "type": "global_regression", "drift": drift})

    recent = entries[-window:] if window > 0 else entries
    module_latest = last.get("module_scores", {}) if isinstance(last.get("module_scores", {}), dict) else {}
    module_previous = previous.get("module_scores", {}) if isinstance(previous.get("module_scores", {}), dict) else {}
    for module, score in module_latest.items():
        prev = float(module_previous.get(module, score))
        delta = round(float(score) - prev, 4)
        if delta < 0:
            alerts.append({"level": "warn", "type": "module_regression", "module": module, "drift": delta})

    return {
        "entries": len(entries),
        "window": len(recent),
        "drift": drift,
        "alerts": alerts,
        "latest_score": current_score,
    }
