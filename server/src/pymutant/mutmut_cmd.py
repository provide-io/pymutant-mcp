# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path


def preferred_python(root: Path) -> str | None:
    candidate = root / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return None


def mutmut_cmd_prefix(root: Path) -> list[str]:
    preferred = preferred_python(root)
    if preferred:
        return [preferred, "-m", "mutmut"]
    return ["mutmut"]
