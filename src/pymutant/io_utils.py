# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace path with content using a temp file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(tmp_name)
