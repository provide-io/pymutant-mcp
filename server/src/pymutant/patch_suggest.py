# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _test_path_from_source(root: Path, source_file: str) -> Path:
    stem = Path(source_file).stem
    return root / "tests" / f"test_{stem}_mutants.py"


def suggest_pytest_patch(
    *,
    mutant_name: str,
    source_file: str,
    diff: str,
    apply: bool = False,
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = _project_root_or_cwd(project_root)
    target = _test_path_from_source(root, source_file)
    fn = mutant_name.replace(".", "_").replace("__", "_").replace("-", "_")
    test_fn = f"test_kill_{fn}".replace("__", "_")
    snippet = (
        f"def {test_fn}() -> None:\n"
        f"    \"\"\"Auto-generated suggestion for {mutant_name}.\"\"\"\n"
        "    # Replace this with a behavior assertion that kills the mutant.\n"
        f"    mutant_diff_excerpt = {diff[:80]!r}\n"
        "    assert mutant_diff_excerpt != \"\"\n"
    )
    patch = f"# target: {target}\n\n{snippet}"

    applied = False
    reason = "suggestion_only"
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        current = target.read_text() if target.exists() else ""
        if test_fn in current:
            reason = "already_present"
        else:
            new_content = current + ("\n" if current and not current.endswith("\n") else "") + snippet
            target.write_text(new_content)
            applied = True
            reason = "applied"

    return {
        "mutant_name": mutant_name,
        "target_file": str(target),
        "patch": patch,
        "applied": applied,
        "reason": reason,
    }
