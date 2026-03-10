# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from pymutant.io_utils import atomic_write_text


def test_atomic_write_text_writes_content(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    atomic_write_text(target, '{"ok":true}\n')
    assert target.read_text() == '{"ok":true}\n'


def test_atomic_write_text_cleans_temp_when_replace_fails(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    seen: dict[str, str] = {}
    import os

    def _replace(_src: str, _dst: Path) -> None:  # type: ignore[no-untyped-def]
        raise OSError("boom")

    def _unlink(path: str) -> None:
        seen["tmp"] = path
        os.remove(path)

    monkeypatch.setattr("pymutant.io_utils.os.replace", _replace)
    monkeypatch.setattr("pymutant.io_utils.os.unlink", _unlink)

    with suppress(OSError):
        atomic_write_text(target, "x")

    assert "tmp" in seen
    assert not Path(seen["tmp"]).exists()
