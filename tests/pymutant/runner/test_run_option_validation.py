# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from pymutant import runner


def test_run_mutations_rejects_paths_with_strict_campaign(tmp_path: Path) -> None:
    out = runner.run_mutations(paths=["src/mod.py"], strict_campaign=True, project_root=tmp_path)
    assert out["returncode"] == -1
    assert out["summary"] == "invalid run options"
    assert "strict_campaign" in out["stderr"]


def test_run_mutations_rejects_paths_with_changed_only(tmp_path: Path) -> None:
    out = runner.run_mutations(paths=["src/mod.py"], changed_only=True, project_root=tmp_path)
    assert out["returncode"] == -1
    assert out["summary"] == "invalid run options"
    assert "changed_only" in out["stderr"]


def test_run_mutations_rejects_combined_paths_modes(tmp_path: Path) -> None:
    out = runner.run_mutations(paths=["src/x.py"], strict_campaign=True, changed_only=True, project_root=tmp_path)
    assert out["returncode"] == -1
    assert out["summary"] == "invalid run options"
    assert "strict_campaign" in out["stderr"]
