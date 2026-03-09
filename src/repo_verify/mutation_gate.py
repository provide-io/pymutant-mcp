# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from pymutant import results, runner
from pymutant.schema import with_schema

INTERRUPTION_CODES = {-15, -9}


def _chunks(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        size = 1
    return [items[i : i + size] for i in range(0, len(items), size)]


def _write_json(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(with_schema(payload), indent=2) + "\n")


def _survivor_names(project_root: Path) -> list[str]:
    data = results.get_results(include_killed=False, project_root=project_root)
    return sorted(m["name"] for m in data["mutants"] if m["status"] == "survived")


def run_mutation_gate(
    *,
    project_root: Path,
    batch_size: int,
    max_rounds: int,
    max_children: int,
    changed_only: bool,
    base_ref: str | None,
    reset_state: bool,
    max_seconds: float = 900.0,
    max_interruptions: int = 6,
) -> tuple[dict[str, Any], list[str]]:
    start = time.monotonic()
    interruptions = 0
    payload: dict[str, Any] = {
        "mode": "changed_only" if changed_only else "full",
        "batch_size": batch_size,
        "max_rounds": max_rounds,
        "max_children": max_children,
        "rounds": [],
        "max_seconds": max_seconds,
        "max_interruptions": max_interruptions,
    }

    if reset_state:
        payload["reset"] = {
            "campaign": runner.reset_strict_campaign(project_root=project_root),
            "ledger": False,
        }

    seed = runner.run_mutations(
        changed_only=changed_only,
        base_ref=base_ref,
        max_children=max_children,
        project_root=project_root,
    )
    payload["seed_run"] = seed

    failures: list[str] = []
    while int(seed.get("returncode", 0)) in INTERRUPTION_CODES and interruptions < max_interruptions:
        payload["seed_cleanup"] = runner.kill_stuck_mutmut(project_root=project_root)
        interruptions += 1
        seed = runner.run_mutations(
            changed_only=changed_only,
            base_ref=base_ref,
            max_children=max_children,
            project_root=project_root,
        )
        payload["seed_run"] = seed

    if int(seed.get("returncode", 0)) in INTERRUPTION_CODES:
        failures.append("seed run interrupted beyond retry budget")
    elif int(seed.get("returncode", 0)) != 0:
        failures.append(f"seed run failed: {seed.get('returncode')}")

    seen_survivor_sets: set[tuple[str, ...]] = set()
    for idx in range(1, max_rounds + 1):
        if time.monotonic() - start > max_seconds:
            failures.append(f"time budget exceeded before round {idx}: {max_seconds}s")
            break
        names_before = _survivor_names(project_root)
        if not names_before:
            break
        before_sig = tuple(names_before)
        if before_sig in seen_survivor_sets:
            failures.append(f"survivor set repeated before round {idx}: {len(names_before)}")
            break
        seen_survivor_sets.add(before_sig)

        round_data: dict[str, Any] = {
            "round": idx,
            "survivors_before": len(names_before),
            "batches": [],
        }

        for batch in _chunks(names_before, batch_size):
            out = runner.run_mutations(paths=batch, max_children=max_children, project_root=project_root)
            batch_info = {
                "size": len(batch),
                "returncode": int(out.get("returncode", -1)),
                "summary": str(out.get("summary", "")),
            }
            while int(out.get("returncode", 0)) in INTERRUPTION_CODES and interruptions < max_interruptions:
                batch_info["cleanup"] = runner.kill_stuck_mutmut(project_root=project_root)
                interruptions += 1
                out = runner.run_mutations(paths=batch, max_children=max_children, project_root=project_root)
                batch_info["returncode"] = int(out.get("returncode", -1))
                batch_info["summary"] = str(out.get("summary", ""))
            if int(out.get("returncode", 0)) in INTERRUPTION_CODES:
                failures.append(f"batch interruption beyond retry budget in round {idx}")
            round_data["batches"].append(batch_info)
            if time.monotonic() - start > max_seconds:
                failures.append(f"time budget exceeded in round {idx}: {max_seconds}s")
                break

        names_after = _survivor_names(project_root)
        after_sig = tuple(names_after)
        round_data["survivors_after"] = len(names_after)
        payload["rounds"].append(round_data)
        if names_after and after_sig in seen_survivor_sets:
            failures.append(f"survivor set repeated in round {idx}: {len(names_after)}")
            break
        seen_survivor_sets.add(after_sig)

        if len(names_after) >= len(names_before):
            failures.append(f"no progress in round {idx}: {len(names_before)} -> {len(names_after)}")
            break
        if time.monotonic() - start > max_seconds:
            break

    final_survivors = _survivor_names(project_root)
    payload["final_survivors"] = len(final_survivors)
    payload["remaining"] = final_survivors
    payload["interruptions"] = interruptions
    payload["elapsed_seconds"] = round(time.monotonic() - start, 3)
    if final_survivors:
        failures.append(f"survivors remain: {len(final_survivors)}")

    return with_schema(payload), failures


def _print_failures(failures: list[str]) -> None:
    for failure in failures:
        print(f"mutation gate failure: {failure}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mutation-gate")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--json-out")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-rounds", type=int, default=8)
    parser.add_argument("--max-children", type=int, default=1)
    parser.add_argument("--changed-only", action="store_true")
    parser.add_argument("--base-ref")
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--max-seconds", type=float, default=900.0)
    parser.add_argument("--max-interruptions", type=int, default=6)
    args = parser.parse_args(argv)

    payload, failures = run_mutation_gate(
        project_root=Path(args.project_root).resolve(),
        batch_size=args.batch_size,
        max_rounds=args.max_rounds,
        max_children=args.max_children,
        changed_only=args.changed_only,
        base_ref=args.base_ref,
        reset_state=not args.no_reset,
        max_seconds=args.max_seconds,
        max_interruptions=args.max_interruptions,
    )
    _write_json(Path(args.json_out) if args.json_out else None, payload)
    print(json.dumps(payload, indent=2), flush=True)
    if failures:
        _print_failures(failures)
        raise SystemExit(1)


if __name__ == "__main__":  # pragma: no cover
    main()
