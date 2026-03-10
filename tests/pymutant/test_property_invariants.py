# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from hypothesis import given
from hypothesis import strategies as st

from pymutant import ledger, results, score, setup

IDENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]*", fullmatch=True)
KNOWN_EXIT_CODES = {code for code in results.EXIT_CODE_STATUS if code is not None}
UNKNOWN_EXIT_CODES = [i for i in range(-1000, 1001) if i not in KNOWN_EXIT_CODES]


@given(codes=st.lists(st.sampled_from(UNKNOWN_EXIT_CODES), max_size=25))
def test_results_unknown_exit_codes_map_to_suspicious_property(codes: list[int]) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        meta_dir = root / "mutants"
        meta_dir.mkdir(parents=True)
        (meta_dir / "x.meta").write_text(
            json.dumps({"exit_code_by_key": {f"pkg.mod.f__mutmut_{i}": code for i, code in enumerate(codes, start=1)}})
        )
        out = results.get_results(include_killed=True, use_ledger=False, project_root=root)
        assert out["counts"]["suspicious"] == len(codes)


@given(
    killed=st.integers(min_value=0, max_value=200),
    survived=st.integers(min_value=0, max_value=200),
    timeout=st.integers(min_value=0, max_value=200),
    segfault=st.integers(min_value=0, max_value=200),
    crash=st.integers(min_value=0, max_value=200),
)
def test_compute_score_formula_property(
    killed: int,
    survived: int,
    timeout: int,
    segfault: int,
    crash: int,
) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        with patch.object(
            score,
            "get_results",
            lambda **_: {
                "counts": {
                    "killed": killed,
                    "survived": survived,
                    "timeout": timeout,
                    "segfault": segfault,
                    "crash": crash,
                },
                "total": killed + survived + timeout + segfault + crash,
            },
        ):
            out = score.compute_score(root)
            denom = killed + survived + timeout + segfault + crash
            expected = 0.0 if denom == 0 else killed / denom
            assert out["score"] == round(expected, 4)
            assert out["segfault"] == segfault + crash
            assert out["crash"] == segfault + crash
            assert 0.0 <= out["score"] <= 1.0


@given(values=st.lists(st.one_of(st.none(), st.booleans(), st.integers(), st.text()), max_size=25))
def test_normalize_to_list_list_values_property(values: list[object]) -> None:
    converted, note = setup._normalize_to_list(values)
    assert converted == [str(v) for v in values]
    assert note is None


@given(
    events=st.lists(
        st.dictionaries(
            keys=IDENT,
            values=st.one_of(st.sampled_from(sorted(ledger.TERMINAL_STATUSES)), st.text(min_size=1, max_size=20)),
            max_size=8,
        ),
        max_size=20,
    )
)
def test_resolve_latest_statuses_matches_reference_property(events: list[dict[str, str]]) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        payload = {
            "events": [
                {"timestamp": f"t{i}", "context": "property", "mutants": event} for i, event in enumerate(events)
            ]
        }
        (root / ledger.LEDGER_FILE).write_text(json.dumps(payload))

        expected: dict[str, str] = {}
        for event in events:
            for name, status in event.items():
                if status in ledger.TERMINAL_STATUSES:
                    expected[name] = status
                elif name not in expected:
                    expected[name] = "not_checked"

        assert ledger.resolve_latest_statuses(root) == expected


@given(
    events=st.lists(st.dictionaries(keys=IDENT, values=st.sampled_from(sorted(ledger.TERMINAL_STATUSES)), max_size=8))
)
def test_ledger_status_count_consistency_property(events: list[dict[str, str]]) -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for event in events:
            ledger.append_ledger_event(event, context="property", project_root=root)
        status = ledger.ledger_status(root)
        assert status["events"] == sum(1 for event in events if event)
        assert sum(status["counts"].values()) == status["mutants_tracked"]


@given(mod_parts=st.lists(IDENT, min_size=1, max_size=5), idx=st.integers(min_value=1, max_value=999))
def test_key_to_source_file_well_formed_mutant_key_property(mod_parts: list[str], idx: int) -> None:
    key = f"{'.'.join(mod_parts)}.fn__mutmut_{idx}"
    assert results._key_to_source_file(key) == "/".join(mod_parts) + ".py"
