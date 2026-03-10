# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repo_verify import mcp_smoke


def test_unwrap_success() -> None:
    out = mcp_smoke._unwrap("tool", {"ok": True, "data": {"x": 1}})
    assert out == {"x": 1}


def test_unwrap_invalid_response_type() -> None:
    with pytest.raises(RuntimeError, match="invalid response type"):
        mcp_smoke._unwrap("tool", [])  # type: ignore[arg-type]


def test_unwrap_invalid_data_payload() -> None:
    with pytest.raises(RuntimeError, match="invalid data payload"):
        mcp_smoke._unwrap("tool", {"ok": True, "data": []})


def test_unwrap_error_with_message() -> None:
    with pytest.raises(RuntimeError, match="tool failed: boom"):
        mcp_smoke._unwrap("tool", {"ok": False, "error": {"message": "boom"}})


def test_unwrap_error_without_message() -> None:
    with pytest.raises(RuntimeError, match="tool failed: unknown error"):
        mcp_smoke._unwrap("tool", {"ok": False, "error": "bad"})


def test_main_success(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mcp_smoke,
        "pymutant_set_project_root",
        lambda _path: {"ok": True, "data": {"active_project_root": str(tmp_path)}},
    )
    monkeypatch.setattr(mcp_smoke, "pymutant_check_setup", lambda: {"ok": True, "data": {"ok": True}})
    monkeypatch.setattr(
        mcp_smoke,
        "pymutant_baseline_status",
        lambda **_kwargs: {"ok": True, "data": {"valid": True, "reasons": []}},
    )
    monkeypatch.setattr(
        mcp_smoke,
        "pymutant_run",
        lambda **_kwargs: {"ok": True, "data": {"returncode": 0, "summary": "ok"}},
    )

    mcp_smoke.main(["--project-root", str(tmp_path), "--base-ref", "main"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["project_root"] == str(tmp_path)
    assert payload["setup_ok"] is True
    assert payload["baseline_valid"] is True
    assert payload["run_returncode"] == 0


def test_main_failure(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mcp_smoke,
        "pymutant_set_project_root",
        lambda _path: {"ok": False, "error": {"message": "bad root"}},
    )
    with pytest.raises(SystemExit) as exc:
        mcp_smoke.main(["--project-root", str(tmp_path)])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "mcp smoke failed:" in err
