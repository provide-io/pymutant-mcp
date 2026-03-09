<!-- SPDX-FileCopyrightText: Copyright (c) provide.io llc -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Tool Contracts

`pymutant` exposes MCP tools with stable names:

- `pymutant_run`
- `pymutant_kill_stuck`
- `pymutant_results`
- `pymutant_show_diff`
- `pymutant_compute_score`
- `pymutant_update_score_history`
- `pymutant_surviving_mutants`
- `pymutant_score_history`
- `pymutant_detect_layout`
- `pymutant_check_setup`
- `pymutant_init`
- `pymutant_ledger_status`
- `pymutant_reset_campaign`

## Error Shape

Tool wrappers return structured objects instead of raising exceptions at the tool boundary.

Common keys:

- `returncode`: process/tool exit code (`0` on success, negative for internal interruption/timeout conditions)
- `summary`: short human-readable status
- `stderr`: diagnostic text when available
- `stdout`: command output when available

For setup/layout checks, responses include `ok` and `checks` arrays with per-check details.

## `pymutant_run` Notes

`pymutant_run` supports these targeting modes:
- explicit `paths`
- `strict_campaign=true` (snapshot-based selector progression)
- `changed_only=true` with optional `base_ref` for git-diff-based file targeting
