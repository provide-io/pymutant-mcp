# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import shutil
import signal
import subprocess  # nosec B404

from pymutant.baseline import ensure_runtime_baseline
from pymutant.ledger import append_ledger_event

from . import api, helpers
from .api import kill_stuck_mutmut, reset_strict_campaign, run_mutations, strict_campaign_status
from .helpers import (
    DEFAULT_BATCH_MAX_CHILDREN,
    DEFAULT_MUTANT_BATCH_SIZE,
    MAX_CMD_OUTPUT_CHARS,
    MUTMUT_NO_PROGRESS_TIMEOUT,
    MUTMUT_TIMEOUT,
    RESULT_ICON_STATUS,
    STRICT_CAMPAIGN_FILE,
    MetaSanitizeSummary,
    StrictCampaign,
    _batch_size,
    _configured_mutation_roots,
    _dependency_preflight,
    _extract_summary,
    _filter_changed_python_paths,
    _init_or_load_strict_campaign,
    _load_exit_codes_by_key,
    _load_not_checked_mutants,
    _mutmut_cmd_prefix,
    _normalize_path_selectors,
    _parse_mutmut_result_lines,
    _preferred_python,
    _project_root_or_cwd,
    _record_ledger_outcomes,
    _refresh_strict_campaign_names,
    _requires_mcp_dependency,
    _resolve_changed_paths_for_mutation,
    _run_cmd,
    _sanitize_cmd_output,
    _sanitize_mutant_meta_files,
    _select_batch_names,
    _strict_remaining_names,
    _terminate_process_tree,
)

__all__ = [
    "DEFAULT_BATCH_MAX_CHILDREN",
    "DEFAULT_MUTANT_BATCH_SIZE",
    "MAX_CMD_OUTPUT_CHARS",
    "MUTMUT_NO_PROGRESS_TIMEOUT",
    "MUTMUT_TIMEOUT",
    "RESULT_ICON_STATUS",
    "STRICT_CAMPAIGN_FILE",
    "MetaSanitizeSummary",
    "StrictCampaign",
    "_batch_size",
    "_configured_mutation_roots",
    "_dependency_preflight",
    "_extract_summary",
    "_filter_changed_python_paths",
    "_init_or_load_strict_campaign",
    "_load_exit_codes_by_key",
    "_load_not_checked_mutants",
    "_mutmut_cmd_prefix",
    "_normalize_path_selectors",
    "_parse_mutmut_result_lines",
    "_preferred_python",
    "_project_root_or_cwd",
    "_record_ledger_outcomes",
    "_refresh_strict_campaign_names",
    "_requires_mcp_dependency",
    "_resolve_changed_paths_for_mutation",
    "_run_cmd",
    "_sanitize_cmd_output",
    "_sanitize_mutant_meta_files",
    "_select_batch_names",
    "_strict_remaining_names",
    "_terminate_process_tree",
    "api",
    "append_ledger_event",
    "ensure_runtime_baseline",
    "helpers",
    "kill_stuck_mutmut",
    "os",
    "reset_strict_campaign",
    "run_mutations",
    "shutil",
    "signal",
    "strict_campaign_status",
    "subprocess",
]
