# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path

_CONFTEST_TEMPLATE = '''\
"""Root conftest — copied by mutmut to mutants/conftest.py.

When mutmut runs pytest from mutants/, this file ensures that
source imports resolve to the mutated copies rather than the
editable install in .venv.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if os.environ.get("MUTANT_UNDER_TEST"):
    _here = Path(__file__).resolve().parent  # mutants/ when run by mutmut
    _mutated_src = _here / "src"
    if _mutated_src.exists():
        # Prepend mutants/src so mutated copies take priority over the editable install.
        sys.path.insert(0, str(_mutated_src))
'''


def _project_root_or_cwd(project_root: Path | str | None) -> Path:
    if project_root is None:
        return Path(os.getcwd())
    return Path(project_root)


def _has_mutmut_section(text: str) -> bool:
    return "[tool.mutmut]" in text


def _fmt_toml_list(items: list[str]) -> str:
    if not items:
        return "[]"
    inner = ", ".join(f'"{i}"' for i in items)
    return f"[{inner}]"


def _build_toml_block(
    paths_to_mutate: list[str],
    tests_dir: list[str],
    also_copy: list[str] | None,
    pytest_add_cli_args: list[str] | None,
) -> str:
    lines = ["", "[tool.mutmut]"]
    lines.append(f"paths_to_mutate = {_fmt_toml_list(paths_to_mutate)}")
    lines.append(f"tests_dir = {_fmt_toml_list(tests_dir)}")
    if also_copy:
        lines.append(f"also_copy = {_fmt_toml_list(also_copy)}")
    if pytest_add_cli_args:
        args_lines = "\n".join(f'    "{a}",' for a in pytest_add_cli_args)
        lines.append(f"pytest_add_cli_args = [\n{args_lines}\n]")
    lines.append("")
    return "\n".join(lines)


def init_project(
    paths_to_mutate: list[str] | None = None,
    tests_dir: list[str] | None = None,
    also_copy: list[str] | None = None,
    pytest_add_cli_args: list[str] | None = None,
    with_conftest: bool = False,
    dry_run: bool = False,
    project_root: Path | None = None,
) -> dict:
    """Scaffold mutmut config in pyproject.toml and optionally create conftest.py.

    Args:
        paths_to_mutate: Override detected paths. Omit to use auto-detected values.
        tests_dir: Override detected test directories.
        also_copy: Extra files/dirs for mutmut to copy alongside source.
        pytest_add_cli_args: Extra pytest CLI args (e.g. --ignore for slow tests).
        with_conftest: If True, write a conftest.py with MUTANT_UNDER_TEST sys.path guard.
        dry_run: If True, show what would be written without modifying any files.
        project_root: Project root directory (defaults to CWD).
    """
    from .setup import detect_layout  # local import to avoid circular at module level

    root = _project_root_or_cwd(project_root)
    layout_info = detect_layout(root)
    suggested = layout_info["suggested_config"]

    _paths = paths_to_mutate or suggested.get("paths_to_mutate", ["src/"])
    _tests = tests_dir or suggested.get("tests_dir", ["tests/"])
    _also: list[str] = also_copy if also_copy is not None else suggested.get("also_copy", [])

    actions: list[str] = []
    warnings: list[str] = list(layout_info.get("notes", []))

    pp_path = root / "pyproject.toml"
    current_text = pp_path.read_text() if pp_path.exists() else ""

    toml_written = False
    if _has_mutmut_section(current_text):
        warnings.append("[tool.mutmut] already exists in pyproject.toml — not overwriting.")
    elif dry_run:
        block = _build_toml_block(_paths, _tests, _also, pytest_add_cli_args)
        actions.append(f"[dry_run] would append to pyproject.toml:\n{block}")
    else:
        block = _build_toml_block(_paths, _tests, _also, pytest_add_cli_args)
        pp_path.write_text(current_text + block)
        toml_written = True
        actions.append("appended [tool.mutmut] to pyproject.toml")

    conftest_written = False
    if with_conftest:
        conftest_path = root / "conftest.py"
        has_guard = conftest_path.exists() and "MUTANT_UNDER_TEST" in conftest_path.read_text()
        if has_guard:
            warnings.append("conftest.py already has MUTANT_UNDER_TEST guard — not overwriting.")
        elif dry_run:
            actions.append("[dry_run] would write conftest.py with MUTANT_UNDER_TEST sys.path guard")
        else:
            conftest_path.write_text(_CONFTEST_TEMPLATE)
            conftest_written = True
            actions.append("wrote conftest.py with MUTANT_UNDER_TEST sys.path guard")

    return {
        "ok": True,
        "layout": layout_info["layout"],
        "actions": actions,
        "warnings": warnings,
        "toml_written": toml_written,
        "conftest_written": conftest_written,
        "config_used": {
            "paths_to_mutate": _paths,
            "tests_dir": _tests,
            "also_copy": _also,
        },
    }
