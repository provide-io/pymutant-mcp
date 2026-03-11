# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path

ENV_PROJECT_ROOT = "PYMUTANT_PROJECT_ROOT"
ENV_BATCH_SIZE = "PYMUTANT_BATCH_SIZE"
ENV_PROFILE = "PYMUTANT_PROFILE"
ENV_PROFILE_CONFIG = "PYMUTANT_PROFILE_CONFIG"

DEFAULT_PROFILE_FILE = ".ci/pymutant-profiles.json"


def get_env_project_root() -> str | None:
    return os.environ.get(ENV_PROJECT_ROOT)


def set_env_project_root(path: Path) -> None:
    os.environ[ENV_PROJECT_ROOT] = str(path)


def get_env_profile_name() -> str | None:
    return os.environ.get(ENV_PROFILE)


def get_env_profile_config() -> str | None:
    return os.environ.get(ENV_PROFILE_CONFIG)


def get_env_batch_size(default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(ENV_BATCH_SIZE)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def set_env_batch_size(batch_size: int) -> str | None:
    previous = os.environ.get(ENV_BATCH_SIZE)
    os.environ[ENV_BATCH_SIZE] = str(batch_size)
    return previous


def restore_env_batch_size(previous: str | None) -> None:
    if previous is None:
        os.environ.pop(ENV_BATCH_SIZE, None)
    else:
        os.environ[ENV_BATCH_SIZE] = previous
