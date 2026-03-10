<!-- SPDX-FileCopyrightText: Copyright (c) provide.io llc -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Architecture

`pymutant` is a FastMCP server that shells out to `mutmut` and normalizes outcomes for tool consumers.

## Core Modules

- `server/src/pymutant/runner/api.py`: mutation execution entrypoints, batching orchestration, strict campaign flow.
- `server/src/pymutant/runner/helpers.py`: subprocess control, changed-only path resolution, strict campaign persistence/helpers.
- `server/src/pymutant/results.py`: reads mutmut metadata and maps exit codes to statuses.
- `server/src/pymutant/ledger.py`: append-only per-mutant outcome ledger.
- `server/src/pymutant/score.py`: mutation score calculation and history handling.
- `server/src/pymutant/setup.py`: project layout/setup detection and initialization checks.
- `server/src/pymutant/main.py`: MCP tool registration and root resolution.

## Runtime Flow

1. A client calls a `pymutant_*` tool.
2. The server resolves project root and validates dependencies.
3. `runner/api.py` (with `runner/helpers.py`) executes batched or explicit mutmut runs.
4. Results are normalized, then persisted to ledger/history.
5. Tool responses return structured data for downstream automation.
