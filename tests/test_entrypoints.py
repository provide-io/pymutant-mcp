# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import runpy


def test_module_entrypoint_calls_main(monkeypatch) -> None:
    called: list[str] = []

    def fake_main() -> None:
        called.append("ok")

    monkeypatch.setattr("pymutant.main.main", fake_main)
    runpy.run_module("pymutant.__main__", run_name="__main__")
    assert called == ["ok"]


def test_import_init_module() -> None:
    mod = __import__("pymutant")
    assert hasattr(mod, "__name__")
