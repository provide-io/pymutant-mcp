# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

from .schema import with_schema


def _project_root_or_cwd(project_root: Path | None) -> Path:
    return project_root if project_root is not None else Path(os.getcwd())


def render_html_bundle(
    *,
    score: dict[str, Any],
    results: dict[str, Any],
    policy: dict[str, Any],
    trend: dict[str, Any],
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = _project_root_or_cwd(project_root)
    dist = root / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    path = dist / "pymutant-report.html"

    body = f"""<!doctype html>
<html>
  <head><meta charset=\"utf-8\"><title>pymutant report</title></head>
  <body>
    <h1>pymutant report</h1>
    <h2>Score</h2>
    <pre>{html.escape(json.dumps(score, indent=2))}</pre>
    <h2>Results</h2>
    <pre>{html.escape(json.dumps(results, indent=2)[:20000])}</pre>
    <h2>Policy</h2>
    <pre>{html.escape(json.dumps(policy, indent=2))}</pre>
    <h2>Trend</h2>
    <pre>{html.escape(json.dumps(trend, indent=2))}</pre>
  </body>
</html>
"""
    path.write_text(body)
    return with_schema({"ok": True, "path": str(path)})
