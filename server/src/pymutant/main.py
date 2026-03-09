# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .init import init_project
from .ledger import ledger_status, reset_ledger
from .results import get_mutant_diff, get_results, get_surviving_mutants
from .runner import kill_stuck_mutmut, reset_strict_campaign, run_mutations, strict_campaign_status
from .score import compute_score, load_score_history, update_score_history
from .setup import check_setup, detect_layout

mcp = FastMCP("pymutant")


def _looks_like_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() or (path / ".git").exists()


def _root() -> Path:
    """Return the project root.

    Resolution order:
    1. PYMUTANT_PROJECT_ROOT env var
    2. os.getcwd() when it looks like an active project workspace
    3. .project-root file next to the server's pyproject.toml (fallback only)
    4. os.getcwd()
    """
    env_root = os.environ.get("PYMUTANT_PROJECT_ROOT")
    if env_root:
        return Path(env_root)
    cwd = Path(os.getcwd())
    if _looks_like_project_root(cwd):
        return cwd
    _server_dir = Path(__file__).resolve().parent.parent.parent
    _config = _server_dir / ".project-root"
    if _config.exists():
        configured = _config.read_text().strip()
        if configured:
            return Path(configured)
    return cwd


@mcp.tool()
def pymutant_run(
    paths: list[str] | None = None,
    max_children: int | None = None,
    strict_campaign: bool = False,
) -> dict:
    """Run mutmut mutation testing on the current project.

    Args:
        paths: Optional list of source paths to mutate (e.g. ["src/mymodule.py"]).
        max_children: Number of parallel workers (default: mutmut decides).
        strict_campaign: When True, snapshot pending mutants once and only process that fixed set.
    """
    return run_mutations(
        paths=paths,
        max_children=max_children,
        strict_campaign=strict_campaign,
        project_root=_root(),
    )


@mcp.tool()
def pymutant_kill_stuck() -> dict:
    """Kill stuck mutmut/pytest worker processes related to mutation runs."""
    return kill_stuck_mutmut(project_root=_root())


@mcp.tool()
def pymutant_results(
    include_killed: bool = False,
    file_filter: str | None = None,
) -> dict:
    """Return structured mutation results from the last run.

    Args:
        include_killed: If True, include killed mutants in output (verbose).
        file_filter: Only return mutants whose source_file contains this string.
    """
    return get_results(
        include_killed=include_killed,
        file_filter=file_filter,
        project_root=_root(),
    )


@mcp.tool()
def pymutant_show_diff(mutant_name: str) -> str:
    """Return unified diff for a single mutant.

    Args:
        mutant_name: The mutant key, e.g. "src.mymodule.my_func__mutmut_3".
    """
    return get_mutant_diff(mutant_name, project_root=_root())


@mcp.tool()
def pymutant_compute_score() -> dict:
    """Compute mutation score: killed / (killed + survived + timeout + segfault).

    Returns score, percentage string, and per-status counts.
    """
    return compute_score(project_root=_root())


@mcp.tool()
def pymutant_update_score_history(label: str | None = None) -> dict:
    """Append current score to mutation-score.json in the project root.

    Args:
        label: Optional human-readable label for this snapshot.
    """
    return update_score_history(label=label, project_root=_root())


@mcp.tool()
def pymutant_surviving_mutants(file_filter: str | None = None) -> list[dict]:
    """Return all surviving mutants with diffs, grouped by source file.

    Args:
        file_filter: Only return results for files whose path contains this string.
    """
    return get_surviving_mutants(file_filter=file_filter, project_root=_root())


@mcp.tool()
def pymutant_score_history() -> dict:
    """Return the full score history from mutation-score.json."""
    return load_score_history(_root())


@mcp.tool()
def pymutant_detect_layout() -> dict:
    """Detect the project layout and return a suggested mutmut configuration.

    Identifies flat, flat_src, or monorepo layouts. For monorepo projects,
    explains the key-mismatch problem and the src/ symlink fix required.
    Returns suggested paths_to_mutate, tests_dir, and also_copy values.
    """
    return detect_layout(project_root=_root())


@mcp.tool()
def pymutant_check_setup() -> dict:
    """Run pre-flight checks for mutmut readiness on the project.

    Checks: mutmut installed, pyproject.toml present, [tool.mutmut] config exists,
    paths_to_mutate and tests_dir are lists (not strings), all configured paths exist,
    monorepo key-mismatch detection, and conftest.py MUTANT_UNDER_TEST guard.
    Returns ok=True only if all checks pass.
    """
    return check_setup(project_root=_root())


@mcp.tool()
def pymutant_init(
    paths_to_mutate: list[str] | None = None,
    tests_dir: list[str] | None = None,
    also_copy: list[str] | None = None,
    pytest_add_cli_args: list[str] | None = None,
    with_conftest: bool = False,
    dry_run: bool = False,
) -> dict:
    """Scaffold mutmut config in pyproject.toml and optionally create conftest.py.

    Auto-detects project layout if paths are not provided. Safe to run on existing
    projects — will not overwrite an existing [tool.mutmut] section or conftest.py
    that already has the MUTANT_UNDER_TEST guard.

    Args:
        paths_to_mutate: Override auto-detected mutation paths.
        tests_dir: Override auto-detected test directories.
        also_copy: Extra files/dirs for mutmut to copy alongside source.
        pytest_add_cli_args: Extra pytest args (e.g. ["--ignore=tests/slow_test.py"]).
        with_conftest: Write conftest.py with MUTANT_UNDER_TEST sys.path guard.
        dry_run: Show what would be written without modifying any files.
    """
    return init_project(
        paths_to_mutate=paths_to_mutate,
        tests_dir=tests_dir,
        also_copy=also_copy,
        pytest_add_cli_args=pytest_add_cli_args,
        with_conftest=with_conftest,
        dry_run=dry_run,
        project_root=_root(),
    )


@mcp.tool()
def pymutant_ledger_status() -> dict:
    """Return status for mutation ledger and strict campaign progress."""
    root = _root()
    return {
        "ledger": ledger_status(project_root=root),
        "campaign": strict_campaign_status(project_root=root),
    }


@mcp.tool()
def pymutant_reset_campaign(clear_ledger: bool = False) -> dict:
    """Reset strict-campaign state; optionally clear outcome ledger too."""
    root = _root()
    removed_campaign = reset_strict_campaign(project_root=root)
    removed_ledger = reset_ledger(project_root=root) if clear_ledger else False
    return {
        "ok": True,
        "removed_campaign": removed_campaign,
        "removed_ledger": removed_ledger,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
