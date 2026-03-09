# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_PROFILE_FILE = ".ci/pymutant-profiles.json"


Profile = dict[str, Any]


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def _load_profile_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _default_profile() -> Profile:
    return {
        "name": "default",
        "mutation_roots": ["src/pymutant/", "src/repo_verify/"],
        "policy": {
            "min_score": 0.0,
            "max_drop_from_baseline": 0.0,
        },
        "packages": {},
    }


def resolve_profile(
    *,
    profile: str | None = None,
    config_path: str | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Resolve active profile using precedence CLI > env > file."""
    root = _project_root_or_cwd(project_root)
    selected = profile or os.environ.get("PYMUTANT_PROFILE") or "default"

    file_path = (
        Path(config_path)
        if config_path
        else Path(os.environ.get("PYMUTANT_PROFILE_CONFIG", "")).expanduser()
        if os.environ.get("PYMUTANT_PROFILE_CONFIG")
        else root / DEFAULT_PROFILE_FILE
    )

    config = _load_profile_file(file_path)
    profiles = config.get("profiles", {}) if isinstance(config.get("profiles", {}), dict) else {}
    active = profiles.get(selected)
    if not isinstance(active, dict):
        active = _default_profile()
    else:
        merged = _default_profile()
        merged.update(active)
        active = merged
        active["name"] = selected

    return {
        "source": "cli" if profile else "env" if os.environ.get("PYMUTANT_PROFILE") else "file",
        "config_path": str(file_path),
        "profile": active,
    }
