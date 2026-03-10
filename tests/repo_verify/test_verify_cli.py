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
    expected_printed = [(f"==> running {name}: {' '.join(cmd)}", True) for name, cmd in cli.VERIFY_STEPS]
    expected_printed.append(("verification passed", True))
    assert printed == expected_printed
    assert calls == [(cmd, False) for _, cmd in cli.VERIFY_STEPS]


def test_verify_main_fails_on_first_error(monkeypatch) -> None:
    calls: list[tuple[list[str], bool]] = []
    printed: list[tuple[str, bool | None, object | None]] = []

    fail_name = "mypy"
    fail_index = next(index for index, (name, _) in enumerate(cli.VERIFY_STEPS) if name == fail_name)

    def fake_run(cmd, check):  # type: ignore[no-untyped-def]
        calls.append((cmd, check))
        code = 1 if len(calls) == fail_index + 1 else 0
        return SimpleNamespace(returncode=code)

    def fake_print(*args, **kwargs):  # type: ignore[no-untyped-def]
        msg = " ".join(str(x) for x in args)
        printed.append((msg, kwargs.get("flush"), kwargs.get("file")))

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    monkeypatch.setattr(builtins, "print", fake_print)

    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1

    expected_prefix = [
        (f"==> running {name}: {' '.join(cmd)}", True, None) for name, cmd in cli.VERIFY_STEPS[: fail_index + 1]
    ]
    assert printed[: fail_index + 1] == expected_prefix
    assert printed[fail_index + 1][0] == f"verification failed during {fail_name}"
    assert printed[fail_index + 1][1] is None
    assert printed[fail_index + 1][2] is cli.sys.stderr
    assert calls == [(cmd, False) for _, cmd in cli.VERIFY_STEPS[: fail_index + 1]]
