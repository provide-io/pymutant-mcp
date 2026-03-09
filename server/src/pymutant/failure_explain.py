# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any


def explain_failure(run_result: dict[str, Any]) -> dict[str, Any]:
    stderr = str(run_result.get("stderr", ""))
    summary = str(run_result.get("summary", ""))
    code = int(run_result.get("returncode", 0))
    text = f"{summary}\n{stderr}".lower()

    if "dependency preflight failed" in text or "cannot import" in text:
        category = "environment/dependency"
        confidence = 0.95
        remedy = "run `uv sync` in the target repo and retry"
        evidence = ["import failure in preflight"]
    elif "pyproject" in text or "paths_to_mutate" in text or "tests_dir" in text:
        category = "setup/config"
        confidence = 0.9
        remedy = "fix mutmut config and rerun `pymutant_check_setup`"
        evidence = ["configuration token found in error output"]
    elif "timed out" in text or "stalled" in text or code in (-15, -9):
        category = "test-harness"
        confidence = 0.8
        remedy = "reduce worker count, kill stuck workers, and rerun in strict campaign"
        evidence = ["timeout/stall/interruption markers"]
    elif "survived" in text or "mutation" in text:
        category = "mutant-behavior"
        confidence = 0.75
        remedy = "add/strengthen assertions for survivor behavior"
        evidence = ["mutation execution completed but mutant survived"]
    else:
        category = "unknown"
        confidence = 0.5
        remedy = "inspect stderr/stdout and run setup checks"
        evidence = ["no known classifier matched"]

    return {
        "category": category,
        "confidence": confidence,
        "evidence": evidence,
        "recommended_action": remedy,
    }
