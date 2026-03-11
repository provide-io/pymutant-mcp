# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from pymutant import baseline


def test_baseline_status_missing_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        baseline,
        "_build_context",
        lambda *_args, **_kwargs: {
            "git_head": "a",
            "python_version": "3.11.0",
            "mutmut_version": "mutmut 3.5.0",
            "mutation_roots": [],
            "tests_roots": [],
            "profile": {"name": "default", "config_path": "x", "hash": "h"},
            "command_mode": "run",
            "meta_snapshot": {"meta_count": 0, "campaign_exists": False, "ledger_exists": False},
        },
    )
    out = baseline.baseline_status(project_root=tmp_path, command_mode="run")
    assert out["valid"] is False
    assert out["reasons"] == ["missing_baseline"]
    assert out["fingerprint_id"]


def test_baseline_status_detects_drift(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / baseline.STATE_DIR / baseline.BASELINE_FILE
    path.parent.mkdir(parents=True)
    previous = {
        "schema_version": "1.0",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "fingerprint_id": "old",
        "context": {
            "git_head": "old",
            "python_version": "3.11.0",
            "mutmut_version": "mutmut 3.5.0",
            "mutation_roots": ["/x"],
            "tests_roots": ["/t"],
            "profile": {"name": "default", "config_path": "x", "hash": "h1"},
            "command_mode": "run",
            "meta_snapshot": {"meta_count": 0, "campaign_exists": False, "ledger_exists": False},
        },
    }
    path.write_text(json.dumps(previous))
    monkeypatch.setattr(
        baseline,
        "_build_context",
        lambda *_args, **_kwargs: {
            "git_head": "new",
            "python_version": "3.11.1",
            "mutmut_version": "mutmut 3.5.1",
            "mutation_roots": ["/y"],
            "tests_roots": ["/t2"],
            "profile": {"name": "ci", "config_path": "y", "hash": "h2"},
            "command_mode": "strict_campaign",
            "meta_snapshot": {"meta_count": 1, "campaign_exists": True, "ledger_exists": True},
        },
    )
    out = baseline.baseline_status(project_root=tmp_path, command_mode="strict_campaign")
    assert out["valid"] is False
    assert "git_head_changed" in out["reasons"]
    assert "profile_hash_changed" in out["reasons"]
    assert "command_mode_changed" not in out["reasons"]


def test_reset_runtime_state_removes_runtime_files(tmp_path: Path) -> None:
    meta = tmp_path / "mutants" / "src" / "a.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}")
    data = tmp_path / "mutants" / "src" / "cached.data"
    data.write_text("cached")
    (tmp_path / baseline.STRICT_CAMPAIGN_FILE).write_text("{}")
    (tmp_path / baseline.LEDGER_FILE).write_text("{}")

    out = baseline.reset_runtime_state(tmp_path)
    assert out["removed_meta_files"] == 1
    assert out["removed_mutants_dir"] is True
    assert out["removed_campaign"] is True
    assert out["removed_ledger"] is True
    assert not meta.exists()
    assert not data.exists()


def test_ensure_runtime_baseline_auto_resets_and_writes(monkeypatch, tmp_path: Path) -> None:
    meta = tmp_path / "mutants" / "src" / "a.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}")
    (tmp_path / baseline.STRICT_CAMPAIGN_FILE).write_text("{}")
    (tmp_path / baseline.LEDGER_FILE).write_text("{}")

    monkeypatch.setattr(
        baseline,
        "_build_context",
        lambda *_args, **_kwargs: {
            "git_head": "a",
            "python_version": "3.11.0",
            "mutmut_version": "mutmut 3.5.0",
            "mutation_roots": ["/x"],
            "tests_roots": ["/t"],
            "profile": {"name": "default", "config_path": "x", "hash": "h"},
            "command_mode": "run",
            "meta_snapshot": {"meta_count": 0, "campaign_exists": False, "ledger_exists": False},
        },
    )
    out = baseline.ensure_runtime_baseline(project_root=tmp_path, command_mode="run", auto_reset=True)
    assert out["valid"] is True
    assert out["was_invalid"] is True
    assert out["auto_reset_applied"] is True
    assert out["reasons"] == ["missing_baseline"]
    assert not meta.exists()
    assert (tmp_path / baseline.STATE_DIR / baseline.BASELINE_FILE).exists()


def test_refresh_baseline_forces_reset(monkeypatch, tmp_path: Path) -> None:
    meta = tmp_path / "mutants" / "x.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}")
    monkeypatch.setattr(
        baseline,
        "_build_context",
        lambda *_args, **_kwargs: {
            "git_head": "a",
            "python_version": "3.11.0",
            "mutmut_version": "mutmut 3.5.0",
            "mutation_roots": [],
            "tests_roots": [],
            "profile": {"name": "default", "config_path": "x", "hash": "h"},
            "command_mode": "manual_refresh",
            "meta_snapshot": {"meta_count": 0, "campaign_exists": False, "ledger_exists": False},
        },
    )
    out = baseline.refresh_baseline(project_root=tmp_path)
    assert out["valid"] is True
    assert out["auto_reset_applied"] is True
    assert not meta.exists()


def test_ensure_runtime_baseline_no_auto_reset(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        baseline,
        "_build_context",
        lambda *_args, **_kwargs: {
            "git_head": "a",
            "python_version": "3.11.0",
            "mutmut_version": "mutmut 3.5.0",
            "mutation_roots": [],
            "tests_roots": [],
            "profile": {"name": "default", "config_path": "x", "hash": "h"},
            "command_mode": "run",
            "meta_snapshot": {"meta_count": 0, "campaign_exists": False, "ledger_exists": False},
        },
    )
    out = baseline.ensure_runtime_baseline(project_root=tmp_path, command_mode="run", auto_reset=False)
    assert out["valid"] is False
    assert out["auto_reset_applied"] is False


def test_read_pyproject_mutmut_variants(tmp_path: Path, monkeypatch) -> None:
    assert baseline._read_pyproject_mutmut(tmp_path) == {}

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[")
    assert baseline._read_pyproject_mutmut(tmp_path) == {}

    pyproject.write_text("[tool.mutmut]\npaths_to_mutate='src'\n")
    assert baseline._read_pyproject_mutmut(tmp_path) == {"paths_to_mutate": "src"}

    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(OSError("denied")))
    assert baseline._read_pyproject_mutmut(tmp_path) == {}


def test_normalize_paths_and_resolve(tmp_path: Path) -> None:
    assert baseline._normalize_paths("src") == ["src"]
    assert baseline._normalize_paths(3) == []
    assert baseline._normalize_paths(["", " src ", 2]) == ["src", "2"]
    assert baseline._resolve_paths(tmp_path, ["a", "a", "b"]) == [
        str((tmp_path / "a").resolve()),
        str((tmp_path / "b").resolve()),
    ]


def test_git_head_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(baseline.shutil, "which", lambda _name: None)
    assert baseline._git_head(tmp_path) == "unknown"

    monkeypatch.setattr(baseline.shutil, "which", lambda _name: "/usr/bin/git")

    def _raise(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=1)

    monkeypatch.setattr(baseline.subprocess, "run", _raise)
    assert baseline._git_head(tmp_path) == "unknown"

    class Done:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(baseline.subprocess, "run", lambda *_a, **_k: Done(1, "x"))
    assert baseline._git_head(tmp_path) == "unknown"
    monkeypatch.setattr(baseline.subprocess, "run", lambda *_a, **_k: Done(0, ""))
    assert baseline._git_head(tmp_path) == "unknown"


def test_mutmut_version_paths(monkeypatch, tmp_path: Path) -> None:
    def _raise(*_a, **_k):
        raise OSError("nope")

    monkeypatch.setattr(baseline.subprocess, "run", _raise)
    assert baseline._mutmut_version(tmp_path) == "unknown"

    class Done:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(baseline.subprocess, "run", lambda *_a, **_k: Done())
    assert baseline._mutmut_version(tmp_path) == "unknown"

    class Done2:
        stdout = None
        stderr = "mutmut 9.9\nextra"

    monkeypatch.setattr(baseline.subprocess, "run", lambda *_a, **_k: Done2())
    assert baseline._mutmut_version(tmp_path) == "mutmut 9.9"


def test_load_state_invalid_payloads(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / baseline.STATE_DIR / baseline.BASELINE_FILE
    state.parent.mkdir(parents=True)
    state.write_text("[1,2]")
    assert baseline._load_state(tmp_path) is None

    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(OSError("denied")))
    assert baseline._load_state(tmp_path) is None


def test_drift_reasons_invalid_context_and_profile_shape() -> None:
    assert baseline._drift_reasons({"context": 1}, {"git_head": "a"}) == ["invalid_baseline_payload"]
    previous = {"context": {"git_head": "a", "profile": "bad"}}
    current = {"git_head": "a", "profile": {"name": "default", "config_path": None, "hash": "h"}}
    reasons = baseline._drift_reasons(previous, current)
    assert "profile_name_changed" in reasons


def test_drift_reasons_profile_unchanged_paths() -> None:
    current = {
        "git_head": "a",
        "python_version": "3.11.0",
        "mutmut_version": "mutmut 1",
        "mutation_roots": ["/x"],
        "tests_roots": ["/t"],
        "command_mode": "run",
        "profile": {"name": "default", "config_path": "p", "hash": "h"},
    }
    previous = {"context": dict(current)}
    assert baseline._drift_reasons(previous, current) == []


def test_reset_runtime_state_ignores_meta_unlink_error(monkeypatch, tmp_path: Path) -> None:
    meta = tmp_path / "mutants" / "a.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}")
    (tmp_path / baseline.STRICT_CAMPAIGN_FILE).write_text("{}")
    (tmp_path / baseline.LEDGER_FILE).write_text("{}")

    original_unlink = Path.unlink

    def _unlink(self: Path, *args, **kwargs) -> None:  # type: ignore[override]
        if self.name == "a.meta":
            raise OSError("busy")
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(baseline.shutil, "rmtree", lambda _path: (_ for _ in ()).throw(OSError("busy")))
    monkeypatch.setattr(Path, "unlink", _unlink)
    out = baseline.reset_runtime_state(tmp_path)
    assert out["removed_meta_files"] == 0
    assert out["removed_mutants_dir"] is False
    assert out["removed_campaign"] is True
    assert out["removed_ledger"] is True


def test_reset_runtime_state_when_mutants_dir_missing(tmp_path: Path) -> None:
    out = baseline.reset_runtime_state(tmp_path)
    assert out == {"removed_meta_files": 0, "removed_mutants_dir": False, "removed_campaign": False, "removed_ledger": False}


def test_reset_runtime_state_fallback_unlinks_meta_when_rmtree_fails(monkeypatch, tmp_path: Path) -> None:
    meta = tmp_path / "mutants" / "a.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}")
    monkeypatch.setattr(baseline.shutil, "rmtree", lambda _path: (_ for _ in ()).throw(OSError("busy")))
    out = baseline.reset_runtime_state(tmp_path)
    assert out["removed_mutants_dir"] is False
    assert out["removed_meta_files"] == 1


def test_ensure_runtime_baseline_returns_valid_status_without_reset(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        baseline,
        "baseline_status",
        lambda **_kwargs: {"valid": True, "was_invalid": False, "reasons": [], "auto_reset_applied": False},
    )
    out = baseline.ensure_runtime_baseline(project_root=tmp_path, command_mode="run", auto_reset=True)
    assert out["valid"] is True
    assert out["auto_reset_applied"] is False
