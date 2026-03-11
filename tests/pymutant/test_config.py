# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path

from pymutant import config


def test_project_root_env_roundtrip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(config.ENV_PROJECT_ROOT, raising=False)
    assert config.get_env_project_root() is None
    config.set_env_project_root(tmp_path)
    assert config.get_env_project_root() == str(tmp_path)


def test_profile_env_accessors(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(config.ENV_PROFILE, raising=False)
    monkeypatch.delenv(config.ENV_PROFILE_CONFIG, raising=False)
    assert config.get_env_profile_name() is None
    assert config.get_env_profile_config() is None

    monkeypatch.setenv(config.ENV_PROFILE, "strict")
    monkeypatch.setenv(config.ENV_PROFILE_CONFIG, str(tmp_path / "profiles.json"))
    assert config.get_env_profile_name() == "strict"
    assert config.get_env_profile_config() == str(tmp_path / "profiles.json")


def test_get_env_batch_size_default_and_invalid(monkeypatch) -> None:
    monkeypatch.delenv(config.ENV_BATCH_SIZE, raising=False)
    assert config.get_env_batch_size(10) == 10
    monkeypatch.setenv(config.ENV_BATCH_SIZE, "bad")
    assert config.get_env_batch_size(10) == 10


def test_get_env_batch_size_honors_minimum(monkeypatch) -> None:
    monkeypatch.setenv(config.ENV_BATCH_SIZE, "0")
    assert config.get_env_batch_size(10) == 1
    assert config.get_env_batch_size(10, minimum=3) == 3
    monkeypatch.setenv(config.ENV_BATCH_SIZE, "8")
    assert config.get_env_batch_size(10, minimum=3) == 8


def test_batch_size_env_set_restore(monkeypatch) -> None:
    monkeypatch.delenv(config.ENV_BATCH_SIZE, raising=False)
    previous = config.set_env_batch_size(12)
    assert previous is None
    assert os.environ[config.ENV_BATCH_SIZE] == "12"
    config.restore_env_batch_size(previous)
    assert config.ENV_BATCH_SIZE not in os.environ

    monkeypatch.setenv(config.ENV_BATCH_SIZE, "7")
    previous = config.set_env_batch_size(9)
    assert previous == "7"
    config.restore_env_batch_size(previous)
    assert os.environ[config.ENV_BATCH_SIZE] == "7"
