# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from pymutant import failure_explain, patch_suggest, policy, prioritization, profiles, quarantine, reporting, schema, trends


def test_schema_helpers() -> None:
    payload = schema.with_schema({"x": 1})
    assert payload["x"] == 1
    assert payload["schema_version"] == "1.0"
    assert "generated_at" in payload


def test_resolve_profile_defaults_and_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    out = profiles.resolve_profile(project_root=tmp_path)
    assert out["profile"]["name"] == "default"

    cfg = tmp_path / ".ci" / "pymutant-profiles.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"profiles": {"ci": {"policy": {"min_score": 0.7}}}}))
    out2 = profiles.resolve_profile(profile="ci", project_root=tmp_path)
    assert out2["source"] == "cli"
    assert out2["profile"]["name"] == "ci"
    assert out2["profile"]["policy"]["min_score"] == 0.7


def test_resolve_profile_env_and_invalid_file(monkeypatch, tmp_path: Path) -> None:
    cfg = tmp_path / "profiles.json"
    cfg.write_text("{")
    monkeypatch.setenv("PYMUTANT_PROFILE", "x")
    monkeypatch.setenv("PYMUTANT_PROFILE_CONFIG", str(cfg))
    out = profiles.resolve_profile(project_root=tmp_path)
    assert out["source"] == "env"
    assert out["profile"]["name"] == "default"


def test_quarantine_load_classify_and_record(tmp_path: Path) -> None:
    assert quarantine.load_quarantine(tmp_path)["entries"] == []

    transient, reason = quarantine.classify_transient_failure({"returncode": -1, "summary": "Timed out", "stderr": ""})
    assert transient is True
    assert reason in {"interruption_or_timeout", "transient_runtime"}

    non_transient = quarantine.classify_transient_failure({"returncode": 0, "summary": "ok", "stderr": ""})
    assert non_transient == (False, "non_transient")

    assert quarantine.confidence_score(repeatability=2, consistency=-1, cleanup_success=0.5) == 0.8

    entry = quarantine.record_quarantine(
        ["m2", "m1", "m1"],
        reason="transient",
        repeatability=0.8,
        consistency=0.9,
        cleanup_success=1.0,
        project_root=tmp_path,
    )
    assert entry["mutants"] == ["m1", "m2"]
    assert 0.0 <= entry["confidence"] <= 1.0


def test_quarantine_load_invalid_json(tmp_path: Path) -> None:
    (tmp_path / ".pymutant-quarantine.json").write_text("{")
    out = quarantine.load_quarantine(tmp_path)
    assert out["entries"] == []


def test_quarantine_load_invalid_shapes_and_marker_path(tmp_path: Path) -> None:
    (tmp_path / ".pymutant-quarantine.json").write_text("[]")
    out = quarantine.load_quarantine(tmp_path)
    assert out["entries"] == []

    (tmp_path / ".pymutant-quarantine.json").write_text(json.dumps({"entries": "bad"}))
    out2 = quarantine.load_quarantine(tmp_path)
    assert out2["entries"] == []

    (tmp_path / ".pymutant-quarantine.json").write_text(json.dumps({"entries": [{"x": 1}, "bad"]}))
    out3 = quarantine.load_quarantine(tmp_path)
    assert out3["entries"] == [{"x": 1}]

    marked = quarantine.classify_transient_failure({"returncode": 0, "summary": "stalled", "stderr": ""})
    assert marked == (True, "transient_runtime")


def test_rank_survivors(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        prioritization,
        "get_results",
        lambda **_kwargs: {
            "mutants": [
                {"name": "m1", "status": "survived", "source_file": "a.py"},
                {"name": "m2", "status": "survived", "source_file": "a.py"},
                {"name": "m3", "status": "killed", "source_file": "a.py"},
                {"name": "m4", "status": "survived", "source_file": "b.py"},
            ]
        },
    )
    monkeypatch.setattr(prioritization, "load_ledger", lambda _root: {"events": [{"mutants": {"m1": "survived"}}]})

    class Done:
        def __init__(self, out: str, returncode: int = 0):
            self.stdout = out
            self.returncode = returncode

    monkeypatch.setattr(prioritization.subprocess, "run", lambda *a, **k: Done("1\n2\n"))
    out = prioritization.rank_survivors(project_root=tmp_path, top_n=2)
    assert out["weights"]["impact"] == 0.5
    assert len(out["survivors"]) == 2
    assert out["survivors"][0]["priority"] >= out["survivors"][1]["priority"]


def test_rank_survivors_no_survivors_and_git_errors(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(prioritization, "get_results", lambda **_kwargs: {"mutants": []})
    assert prioritization.rank_survivors(project_root=tmp_path)["survivors"] == []

    monkeypatch.setattr(
        prioritization,
        "get_results",
        lambda **_kwargs: {"mutants": [{"name": "m1", "status": "survived", "source_file": "a.py"}]},
    )
    monkeypatch.setattr(prioritization, "load_ledger", lambda _root: {"events": []})

    def _raise(*_a, **_k):
        raise TimeoutError

    monkeypatch.setattr(prioritization.subprocess, "run", _raise)
    out = prioritization.rank_survivors(project_root=tmp_path)
    assert out["survivors"][0]["churn"] == 0.0

    class NonZero:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(prioritization.subprocess, "run", lambda *a, **k: NonZero())
    out2 = prioritization.rank_survivors(project_root=tmp_path)
    assert out2["survivors"][0]["churn"] == 0.0

    monkeypatch.setattr(
        prioritization,
        "get_results",
        lambda **_kwargs: {"mutants": [{"name": "m1", "status": "survived", "source_file": "a.py"}, {"name": "m2", "status": "killed", "source_file": "a.py"}]},
    )
    monkeypatch.setattr(prioritization, "load_ledger", lambda _root: {"events": [{"mutants": {"m1": "killed"}}]})
    monkeypatch.setattr(prioritization.subprocess, "run", lambda *a, **k: NonZero())
    out3 = prioritization.rank_survivors(project_root=tmp_path)
    assert out3["survivors"][0]["frequency"] == 0.0


def test_explain_failure_categories() -> None:
    env_dep = failure_explain.explain_failure(
        {"stderr": "cannot import mcp", "summary": "dependency preflight failed", "returncode": -1}
    )
    assert env_dep["category"] == "environment/dependency"
    assert env_dep["confidence"] == 0.95
    assert env_dep["recommended_action"] == "run `uv sync` in the target repo and retry"

    setup_cfg = failure_explain.explain_failure({"stderr": "paths_to_mutate invalid", "summary": "", "returncode": 1})
    assert setup_cfg["category"] == "setup/config"
    assert setup_cfg["confidence"] == 0.9

    harness = failure_explain.explain_failure({"stderr": "", "summary": "timed out", "returncode": -15})
    assert harness["category"] == "test-harness"
    assert harness["confidence"] == 0.8

    mutant = failure_explain.explain_failure({"stderr": "", "summary": "mutation survived", "returncode": 0})
    assert mutant["category"] == "mutant-behavior"
    assert mutant["confidence"] == 0.75
    assert mutant["recommended_action"] == "add/strengthen assertions for survivor behavior"

    unknown = failure_explain.explain_failure({"stderr": "", "summary": "", "returncode": 0})
    assert unknown["category"] == "unknown"
    assert unknown["confidence"] == 0.5


def test_policy_evaluate(tmp_path: Path) -> None:
    baseline = tmp_path / ".ci" / "pymutant-policy-baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps({"profiles": {"default": {"baseline_score": 0.8}}}))
    prof = tmp_path / ".ci" / "pymutant-profiles.json"
    prof.write_text(json.dumps({"profiles": {"default": {"policy": {"min_score": 0.5, "max_drop_from_baseline": 0.2}}}}))

    ok = policy.evaluate_policy(current_score=0.7, project_root=tmp_path)
    assert ok["ok"] is True

    bad = policy.evaluate_policy(current_score=0.4, project_root=tmp_path)
    assert bad["ok"] is False
    assert bad["failures"]


def test_policy_with_custom_paths_and_invalid_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{")
    out = policy.evaluate_policy(current_score=0.9, baseline_path=str(baseline), project_root=tmp_path)
    assert out["ok"] is True


def test_trends() -> None:
    scores = trends.compute_module_scores(
        [
            {"source_file": "a.py", "status": "killed"},
            {"source_file": "a.py", "status": "survived"},
            {"source_file": "b.py", "status": "timeout"},
        ]
    )
    assert scores["a"] == 0.5
    assert scores["b"] == 0.0

    assert trends.trend_report({"history": []})["alerts"] == []
    hist = {
        "history": [
            {"score": 0.8, "module_scores": {"a": 0.8, "b": 0.6}},
            {"score": 0.7, "module_scores": {"a": 0.5, "b": 0.6}},
        ]
    }
    report = trends.trend_report(hist, window=2)
    assert report["drift"] == -0.1
    assert any(a["type"] == "global_regression" for a in report["alerts"])
    assert any(a["type"] == "module_regression" for a in report["alerts"])

    positive = trends.trend_report({"history": [{"score": 0.1, "module_scores": {"a": 0.1}}, {"score": 0.2, "module_scores": {"a": 0.2}}]})
    assert positive["drift"] == 0.1

    scores2 = trends.compute_module_scores([{"source_file": "x.py", "status": "ignored"}])
    assert scores2["x"] == 0.0


def test_patch_suggest(tmp_path: Path) -> None:
    out = patch_suggest.suggest_pytest_patch(
        mutant_name="a.b__mutmut_1",
        source_file="src/a.py",
        diff="hello",
        apply=False,
        project_root=tmp_path,
    )
    assert out["applied"] is False
    assert out["reason"] == "suggestion_only"

    applied = patch_suggest.suggest_pytest_patch(
        mutant_name="a.b__mutmut_2",
        source_file="src/a.py",
        diff="hello",
        apply=True,
        project_root=tmp_path,
    )
    assert applied["applied"] is True
    again = patch_suggest.suggest_pytest_patch(
        mutant_name="a.b__mutmut_2",
        source_file="src/a.py",
        diff="hello",
        apply=True,
        project_root=tmp_path,
    )
    assert again["reason"] == "already_present"


def test_render_html_bundle(tmp_path: Path) -> None:
    out = reporting.render_html_bundle(
        score={"score": 0.5},
        results={"counts": {}},
        policy={"ok": True},
        trend={"alerts": []},
        project_root=tmp_path,
    )
    assert out["ok"] is True
    html_path = Path(out["path"])
    assert html_path.exists()
    assert "pymutant report" in html_path.read_text()
