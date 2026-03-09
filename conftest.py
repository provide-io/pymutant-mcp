"""Root conftest — copied by mutmut to mutants/conftest.py.

When mutmut runs pytest from mutants/, this file ensures that
source imports resolve to the mutated copies rather than the
editable install in .venv.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

if os.environ.get("MUTANT_UNDER_TEST"):
    _here = Path(__file__).resolve().parent  # mutants/ when run by mutmut
    # Prefer src/ first: it contains mutated copies for both repo_verify and
    # the pymutant symlinked package used for mutation key alignment.
    for _rel in ("src", "server/src"):
        _mutated_src = _here / _rel
        if _mutated_src.exists():
            # Prepend mutated source roots so mutant copies win over editable installs.
            sys.path.insert(0, str(_mutated_src))

    # mutmut-generated trampolines import mutmut.__main__.record_trampoline_hit.
    # Importing mutmut.__main__ has process-global side effects (set_start_method),
    # so provide a tiny shim during mutant test execution.
    _main_mod = types.ModuleType("mutmut.__main__")

    def _record_trampoline_hit(name: str) -> None:
        import inspect

        import mutmut

        assert not name.startswith("src."), (
            "Failed trampoline hit. Module name starts with `src.`, which is invalid"
        )
        max_stack_depth = getattr(mutmut.config, "max_stack_depth", -1)
        if max_stack_depth != -1:
            frame = inspect.currentframe()
            remaining = max_stack_depth
            while remaining and frame:
                filename = frame.f_code.co_filename
                if "pytest" in filename or "hammett" in filename or "unittest" in filename:
                    break
                frame = frame.f_back
                remaining -= 1
            if not remaining:
                return
        mutmut._stats.add(name)

    _main_mod.record_trampoline_hit = _record_trampoline_hit  # type: ignore[attr-defined]
    sys.modules.setdefault("mutmut.__main__", _main_mod)
