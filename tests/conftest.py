# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from hypothesis import HealthCheck, settings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "server" / "src"))

settings.register_profile(
    "ci",
    max_examples=80,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "dev",
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci" if os.environ.get("CI") else "dev"))

if os.environ.get("MUTANT_UNDER_TEST"):
    # mutmut trampolines import mutmut.__main__.record_trampoline_hit.
    # Avoid importing mutmut.__main__ itself because it mutates process-wide
    # multiprocessing state and can crash test workers.
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
