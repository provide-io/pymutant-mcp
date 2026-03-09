# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from pymutant import init, results, setup

IDENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]*", fullmatch=True)


@given(mod_parts=st.lists(IDENT, min_size=1, max_size=5), func=IDENT, idx=st.integers(min_value=1, max_value=999))
def test_key_to_source_file_property(mod_parts: list[str], func: str, idx: int) -> None:
    key = f"{'.'.join(mod_parts)}.{func}__mutmut_{idx}"
    expected = "/".join(mod_parts) + ".py"
    assert results._key_to_source_file(key) == expected


@given(text=st.text())
def test_normalize_to_list_string_property(text: str) -> None:
    converted, note = setup._normalize_to_list(text)
    assert converted == [text]
    assert note is not None
    assert "legacy string" in note


@given(items=st.lists(st.text().filter(lambda s: '"' not in s), max_size=8))
def test_fmt_toml_list_shape_property(items: list[str]) -> None:
    rendered = init._fmt_toml_list(items)
    assert rendered.startswith("[")
    assert rendered.endswith("]")
    if not items:
        assert rendered == "[]"
