# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from pymutant import ledger


def test_project_root_or_cwd_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert ledger._project_root_or_cwd(None) == tmp_path


def test_ledger_path(tmp_path: Path) -> None:
    assert ledger._ledger_path(tmp_path) == tmp_path / ledger.LEDGER_FILE


def test_load_ledger_missing_file(tmp_path: Path) -> None:
    assert ledger.load_ledger(tmp_path) == {"events": []}


def test_load_ledger_bad_json(tmp_path: Path) -> None:
    (tmp_path / ledger.LEDGER_FILE).write_text("{")
    assert ledger.load_ledger(tmp_path) == {"events": []}


def test_load_ledger_filters_invalid_events(tmp_path: Path) -> None:
    (tmp_path / ledger.LEDGER_FILE).write_text(
        '{"events":[1, {"timestamp":"t","context":"c","mutants":{"a":"killed","b":1}}, {"timestamp":"x","mutants":{}}]}'
    )
    out = ledger.load_ledger(tmp_path)
    assert len(out["events"]) == 2
    assert out["events"][0]["mutants"] == {"a": "killed"}


def test_load_ledger_non_dict_root(tmp_path: Path) -> None:
    (tmp_path / ledger.LEDGER_FILE).write_text("[]")
    assert ledger.load_ledger(tmp_path) == {"events": []}


def test_load_ledger_non_list_events(tmp_path: Path) -> None:
    (tmp_path / ledger.LEDGER_FILE).write_text('{"events":{}}')
    assert ledger.load_ledger(tmp_path) == {"events": []}


def test_load_ledger_skips_event_with_non_dict_mutants(tmp_path: Path) -> None:
    (tmp_path / ledger.LEDGER_FILE).write_text('{"events":[{"mutants":[]}] }')
    assert ledger.load_ledger(tmp_path) == {"events": []}


def test_append_ledger_event_ignores_empty(tmp_path: Path) -> None:
    ledger.append_ledger_event({}, context="x", project_root=tmp_path)
    assert not (tmp_path / ledger.LEDGER_FILE).exists()


def test_append_ledger_event_writes_and_appends(tmp_path: Path) -> None:
    ledger.append_ledger_event({"m1": "killed", "m2": "survived"}, context="batch", project_root=tmp_path)
    ledger.append_ledger_event({"m3": "not_checked"}, context="batch", project_root=tmp_path)
    data = ledger.load_ledger(tmp_path)
    assert len(data["events"]) == 2
    assert data["events"][0]["context"] == "batch"
    assert data["events"][1]["mutants"]["m3"] == "not_checked"


def test_append_ledger_event_filters_invalid_types(tmp_path: Path) -> None:
    ledger.append_ledger_event({"ok": "killed", "bad": 1}, context="ctx", project_root=tmp_path)  # type: ignore[arg-type]
    data = ledger.load_ledger(tmp_path)
    assert data["events"][0]["mutants"] == {"ok": "killed"}


def test_append_ledger_event_all_invalid_filtered(tmp_path: Path) -> None:
    ledger.append_ledger_event({"bad": 1}, context="ctx", project_root=tmp_path)  # type: ignore[arg-type]
    assert not (tmp_path / ledger.LEDGER_FILE).exists()


def test_resolve_latest_statuses_prefers_terminal_and_keeps_previous(tmp_path: Path) -> None:
    ledger.append_ledger_event({"m1": "not_checked", "m2": "killed"}, context="a", project_root=tmp_path)
    ledger.append_ledger_event({"m1": "survived", "m2": "not_checked"}, context="b", project_root=tmp_path)
    statuses = ledger.resolve_latest_statuses(tmp_path)
    assert statuses["m1"] == "survived"
    assert statuses["m2"] == "killed"


def test_ledger_status_and_reset(tmp_path: Path) -> None:
    before = ledger.ledger_status(tmp_path)
    assert before["exists"] is False
    ledger.append_ledger_event({"m1": "killed"}, context="x", project_root=tmp_path)
    after = ledger.ledger_status(tmp_path)
    assert after["exists"] is True
    assert after["events"] == 1
    assert after["counts"]["killed"] == 1
    assert ledger.reset_ledger(tmp_path) is True
    assert ledger.reset_ledger(tmp_path) is False
