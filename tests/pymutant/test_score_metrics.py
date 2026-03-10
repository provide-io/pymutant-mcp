# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from pymutant import score


def test_project_root_or_cwd_uses_cwd(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    assert score._project_root_or_cwd(None) == tmp_path


def test_score_file_path(tmp_path: Path) -> None:
    assert score._score_file_path(tmp_path) == tmp_path / "mutation-score.json"


def test_compute_score(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        score,
        "get_results",
        lambda **_: {
            "counts": {
                "killed": 3,
                "survived": 1,
                "no_tests": 2,
                "timeout": 1,
                "segfault": 1,
                "skipped": 2,
                "suspicious": 4,
                "typecheck_failed": 1,
                "interrupted": 1,
                "not_checked": 1,
                "stale": 2,
            },
            "total": 14,
        },
    )

    out = score.compute_score(tmp_path)
    assert out["score"] == 0.5
    assert out["score_pct"] == "50.0%"
    assert out["crash"] == 1
    assert out["segfault"] == 1
    assert out["stale"] == 2
    assert out["suspicious"] == 4
    assert out["total"] == 14
    assert set(out) == {
        "score",
        "score_pct",
        "killed",
        "survived",
        "no_tests",
        "timeout",
        "segfault",
        "crash",
        "skipped",
        "stale",
        "suspicious",
        "typecheck_failed",
        "interrupted",
        "not_checked",
        "total",
        "baseline",
    }


def test_compute_score_zero_denominator(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        score,
        "get_results",
        lambda **_: {"counts": {}, "total": 0},
    )
    out = score.compute_score(tmp_path)
    assert out["score"] == 0.0


def test_compute_score_calls_get_results_with_expected_args(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def _fake_get_results(**kwargs):  # type: ignore[no-untyped-def]
        seen.update(kwargs)
        return {"counts": {}, "total": 0}

    monkeypatch.setattr(score, "get_results", _fake_get_results)
    score.compute_score(tmp_path)
    assert seen["include_killed"] is True
    assert seen["use_ledger"] is True
    assert seen["project_root"] == tmp_path


def test_compute_score_uses_project_root_resolver(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(score, "_project_root_or_cwd", lambda _root: tmp_path)
    monkeypatch.setattr(score, "get_results", lambda **_: {"counts": {}, "total": 0})
    out = score.compute_score(None)
    assert out["total"] == 0


def test_load_score_history_missing(tmp_path: Path) -> None:
    out = score.load_score_history(tmp_path)
    assert out["history"] == []
    assert out["schema_version"] == "1.0"


def test_load_score_history_bad_json(tmp_path: Path) -> None:
    (tmp_path / "mutation-score.json").write_text("broken")
    out = score.load_score_history(tmp_path)
    assert out["history"] == []
    assert out["schema_version"] == "1.0"


def test_load_score_history_non_dict_and_non_list(tmp_path: Path) -> None:
    (tmp_path / "mutation-score.json").write_text("[]")
    out = score.load_score_history(tmp_path)
    assert out["history"] == []
    (tmp_path / "mutation-score.json").write_text(json.dumps({"history": "bad"}))
    out2 = score.load_score_history(tmp_path)
    assert out2["history"] == []


def test_load_score_history_valid_list(tmp_path: Path) -> None:
    (tmp_path / "mutation-score.json").write_text(json.dumps({"history": [{"score": 0.2}]}))
    out = score.load_score_history(tmp_path)
    assert out["history"] == [{"score": 0.2}]


def test_update_score_history_with_label(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        score,
        "compute_score",
        lambda _root: {
            "score": 1.0,
            "killed": 1,
            "survived": 0,
            "no_tests": 0,
            "timeout": 0,
            "total": 1,
        },
    )
    monkeypatch.setattr(score, "get_results", lambda **_: {"mutants": []})
    monkeypatch.setattr(score, "compute_module_scores", lambda _mutants: {})

    out = score.update_score_history(label="run", project_root=tmp_path)
    assert out["history_length"] == 1
    assert out["entry"]["label"] == "run"
    assert out["schema_version"] == "1.0"

    history = json.loads((tmp_path / "mutation-score.json").read_text())
    assert len(history["history"]) == 1
    assert history["schema_version"] == "1.0"


def test_update_score_history_without_label(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        score,
        "compute_score",
        lambda _root: {
            "score": 0.2,
            "killed": 1,
            "survived": 4,
            "no_tests": 0,
            "timeout": 0,
            "total": 5,
        },
    )
    monkeypatch.setattr(score, "get_results", lambda **_: {"mutants": []})
    monkeypatch.setattr(score, "compute_module_scores", lambda _mutants: {"m": 0.5})

    out = score.update_score_history(project_root=tmp_path)
    assert "label" not in out["entry"]
    assert out["entry"]["module_scores"] == {"m": 0.5}


def test_update_score_history_repairs_non_list_history(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "mutation-score.json").write_text(json.dumps({"history": "bad"}))
    monkeypatch.setattr(
        score,
        "compute_score",
        lambda _root: {"score": 0.1, "killed": 0, "survived": 1, "no_tests": 0, "timeout": 0, "total": 1},
    )
    monkeypatch.setattr(score, "get_results", lambda **_: {"mutants": []})
    monkeypatch.setattr(score, "compute_module_scores", lambda _mutants: {})
    out = score.update_score_history(project_root=tmp_path)
    assert out["history_length"] == 1


def test_update_score_history_non_list_from_loader(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        score,
        "compute_score",
        lambda _root: {"score": 0.1, "killed": 0, "survived": 1, "no_tests": 0, "timeout": 0, "total": 1},
    )
    monkeypatch.setattr(score, "get_results", lambda **_: {"mutants": []})
    monkeypatch.setattr(score, "compute_module_scores", lambda _mutants: {})
    monkeypatch.setattr(score, "load_score_history", lambda _root: {"history": "oops"})
    out = score.update_score_history(project_root=tmp_path)
    assert out["history_length"] == 1
