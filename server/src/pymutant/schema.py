# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "1.0"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def with_schema(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    enriched.setdefault("schema_version", SCHEMA_VERSION)
    enriched.setdefault("generated_at", now_iso())
    return enriched
