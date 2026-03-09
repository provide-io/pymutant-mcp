# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from repo_verify import cli


def test_verify_main_runs_all_steps(monkeypatch) -> None:
    calls: list[tuple[list[str], bool]] = []
    printed: list[tuple[str, bool | None]] = []

    def fake_run(cmd, check):  # type: ignore[no-untyped-def]
        calls.append((cmd, check))
        return SimpleNamespace(returncode=0)

    def fake_print(*args, **kwargs):  # type: ignore[no-untyped-def]
        msg = " ".join(str(x) for x in args)
        printed.append((msg, kwargs.get("flush")))

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(builtins, "print", fake_print)
    cli.main()
    assert printed == [
        ("==> running ruff: ruff check .", True),
        ("==> running mypy: mypy server/src src/repo_verify", True),
        ("==> running bandit: bandit -q -r server/src/pymutant src/repo_verify -ll", True),
        (
            "==> running docs-lint: pymarkdown --config .pymarkdown.json scan README.md AGENTS.md commands skills "
            "server/README.md docs",
            True,
        ),
        ("==> running docs-links: python scripts/check_markdown_links.py --root .", True),
        ("==> running pytest: pytest -q", True),
        ("verification passed", True),
    ]
    assert calls == [
        (["ruff", "check", "."], False),
        (["mypy", "server/src", "src/repo_verify"], False),
        (["bandit", "-q", "-r", "server/src/pymutant", "src/repo_verify", "-ll"], False),
        (
            [
                "pymarkdown",
                "--config",
                ".pymarkdown.json",
                "scan",
                "README.md",
                "AGENTS.md",
                "commands",
                "skills",
                "server/README.md",
                "docs",
            ],
            False,
        ),
        (["python", "scripts/check_markdown_links.py", "--root", "."], False),
        (["pytest", "-q"], False),
    ]


def test_verify_main_fails_on_first_error(monkeypatch) -> None:
    calls: list[tuple[list[str], bool]] = []
    printed: list[tuple[str, bool | None, object | None]] = []

    def fake_run(cmd, check):  # type: ignore[no-untyped-def]
        calls.append((cmd, check))
        code = 1 if len(calls) == 3 else 0
        return SimpleNamespace(returncode=code)

    def fake_print(*args, **kwargs):  # type: ignore[no-untyped-def]
        msg = " ".join(str(x) for x in args)
        printed.append((msg, kwargs.get("flush"), kwargs.get("file")))

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(builtins, "print", fake_print)

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1

    assert printed[0] == ("==> running ruff: ruff check .", True, None)
    assert printed[1] == ("==> running mypy: mypy server/src src/repo_verify", True, None)
    assert printed[2] == ("==> running bandit: bandit -q -r server/src/pymutant src/repo_verify -ll", True, None)
    assert printed[3][0] == "verification failed during bandit"
    assert printed[3][1] is None
    assert printed[3][2] is cli.sys.stderr
    assert calls == [
        (["ruff", "check", "."], False),
        (["mypy", "server/src", "src/repo_verify"], False),
        (["bandit", "-q", "-r", "server/src/pymutant", "src/repo_verify", "-ll"], False),
    ]
