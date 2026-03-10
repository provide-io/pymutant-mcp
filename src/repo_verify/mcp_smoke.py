# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pymutant.main import (
    pymutant_baseline_status,
    pymutant_check_setup,
    pymutant_run,
    pymutant_set_project_root,
)


def _unwrap(name: str, response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise RuntimeError(f"{name} returned invalid response type")
    if bool(response.get("ok", False)):
        data = response.get("data")
        if isinstance(data, dict):
            return data
        raise RuntimeError(f"{name} returned invalid data payload")
    error = response.get("error")
    message = str(error.get("message", "unknown error")) if isinstance(error, dict) else "unknown error"
    raise RuntimeError(f"{name} failed: {message}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mcp-smoke")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--base-ref", default="HEAD")
    args = parser.parse_args(argv)

    root = Path(args.project_root).resolve()
    try:
        set_root = _unwrap("pymutant_set_project_root", pymutant_set_project_root(str(root)))
        setup = _unwrap("pymutant_check_setup", pymutant_check_setup())
        baseline = _unwrap("pymutant_baseline_status", pymutant_baseline_status(command_mode="smoke"))
        run = _unwrap(
            "pymutant_run",
            pymutant_run(changed_only=False, base_ref=args.base_ref, max_children=1, strict_campaign=True),
        )
    except RuntimeError as exc:
        print(f"mcp smoke failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc

    payload = {
        "project_root": set_root.get("active_project_root"),
        "setup_ok": setup.get("ok"),
        "baseline_valid": baseline.get("valid"),
        "baseline_reasons": baseline.get("reasons", []),
        "run_returncode": run.get("returncode"),
        "run_summary": run.get("summary"),
    }
    print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":  # pragma: no cover
    main()
