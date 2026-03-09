<!-- SPDX-FileCopyrightText: Copyright (c) provide.io llc -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Architecture

`pymutant` is a FastMCP server that shells out to `mutmut` and normalizes outcomes for tool consumers.

## Core Modules

- `server/src/pymutant/runner.py`: mutation execution, batching, strict campaign handling, subprocess resilience.
- `server/src/pymutant/results.py`: reads mutmut metadata and maps exit codes to statuses.
- `server/src/pymutant/ledger.py`: append-only per-mutant outcome ledger.
- `server/src/pymutant/score.py`: mutation score calculation and history handling.
- `server/src/pymutant/setup.py`: project layout/setup detection and initialization checks.
- `server/src/pymutant/main.py`: MCP tool registration and root resolution.

## Runtime Flow

1. A client calls a `pymutant_*` tool.
2. The server resolves project root and validates dependencies.
3. `runner.py` executes batched or explicit mutmut runs.
4. Results are normalized, then persisted to ledger/history.
5. Tool responses return structured data for downstream automation.
