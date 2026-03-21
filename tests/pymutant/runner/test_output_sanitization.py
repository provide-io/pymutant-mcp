# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pymutant import runner


def test_sanitize_cmd_output_compacts_repeated_mutmut_progress() -> None:
    raw = (
        "Generating mutants\r"
        "Generating mutants\r"
        "Running clean tests\r"
        "Running clean tests\r"
        "actual failure context\r"
    )
    sanitized = runner._sanitize_cmd_output(raw)
    assert sanitized == "Generating mutants\nRunning clean tests\nactual failure context"


def test_sanitize_cmd_output_compacts_spinner_prefixed_progress() -> None:
    raw = (
        "⠋ Generating mutants\r"
        "⠙ Generating mutants\r"
        "⠹ Listing all tests\r"
        "⠸ Listing all tests\r"
        "⠹ Running stats\r"
        "⠸ Running stats\r"
        "actual failure context\r"
    )
    sanitized = runner._sanitize_cmd_output(raw)
    assert sanitized == "Generating mutants\nListing all tests\nRunning stats\nactual failure context"


def test_sanitize_cmd_output_can_preserve_repeated_progress_when_requested() -> None:
    raw = "Generating mutants\rGenerating mutants\ractual failure context\r"
    sanitized = runner._sanitize_cmd_output(raw, compact_progress=False)
    assert sanitized == "Generating mutants\nGenerating mutants\nactual failure context"


def test_sanitize_cmd_output_preserves_spinner_prefixed_progress_when_requested() -> None:
    raw = "⠋ Generating mutants\r⠙ Generating mutants\ractual failure context\r"
    sanitized = runner._sanitize_cmd_output(raw, compact_progress=False)
    assert sanitized == "Generating mutants\nGenerating mutants\nactual failure context"


def test_compact_progress_lines_preserves_single_internal_blank_line() -> None:
    compacted = runner.helpers._compact_progress_lines(["Generating mutants", "", "actual failure context"])
    assert compacted == ["Generating mutants", "", "actual failure context"]


def test_compact_progress_lines_drops_trailing_blank_lines() -> None:
    compacted = runner.helpers._compact_progress_lines(["Generating mutants", ""])
    assert compacted == ["Generating mutants"]


def test_compact_progress_lines_collapses_consecutive_blank_lines() -> None:
    compacted = runner.helpers._compact_progress_lines(["Generating mutants", "", "", "actual failure context"])
    assert compacted == ["Generating mutants", "", "actual failure context"]
