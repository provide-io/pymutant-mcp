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
- `pymutant_rank_survivors`
- `pymutant_explain_failure`
- `pymutant_policy_check`
- `pymutant_trend_report`
- `pymutant_suggest_pytest_patch`
- `pymutant_render_report`
- `pymutant_baseline_status`
- `pymutant_baseline_refresh`

## Error Shape

Tool wrappers return structured envelope objects instead of raising exceptions at the tool boundary.

Common keys:

- `ok`: boolean success flag
- `data`: tool-specific payload
- `error`: object or `null` (`type`, `message`, `details`)
- `schema_version`: schema tag for downstream parsers
- `generated_at`: UTC timestamp

Mutation execution and scoring tools also include a `baseline` block:

- `valid`: whether runtime baseline matches current execution context
- `reasons`: machine-readable drift reasons
- `fingerprint_id`: active baseline fingerprint hash
- `auto_reset_applied`: whether runtime state was auto-reset before execution

For setup/layout checks, `data.checks` includes per-check details.

## `pymutant_run` Notes

`pymutant_run` supports these targeting modes:
- explicit `paths`
- `strict_campaign=true` (snapshot-based selector progression)
- `changed_only=true` with optional `base_ref` for git-diff-based file targeting
