# Operator Runbook

## Scope

This runbook covers day-to-day operation of `pymutant` mutation checks in local dev and CI.

## Standard Verification

Run the canonical gate:

```bash
uv run verify
```

This enforces Ruff, MyPy, Bandit, docs checks, schema checks, and `pytest` with 100% statement+branch coverage.

## Zero-Survivor Sweep

Use the sweep wrapper to kill survivors with retry/time budgets:

```bash
uv run mutation-sweep --max-rounds 4 --max-seconds 900 --max-interruptions 8 --json-out dist/mutation-gate.json
```

Inspect the artifact for `final_survivors`, `interruptions`, and `elapsed_seconds`.

## Reducing `not_checked` Deterministically

Use strict campaign mode to process a fixed snapshot of pending selectors:

```bash
PYMUTANT_BATCH_SIZE=25 uv run python -c "from pymutant import runner; print(runner.run_mutations(strict_campaign=True, max_children=1))"
uv run python -c "from pymutant import runner; print(runner.strict_campaign_status())"
```

- Campaign state file: `.pymutant-strict-campaign.json`
- Reset campaign state if needed: `runner.reset_strict_campaign()`

## Execution Baseline

`pymutant` maintains runtime baseline state at `.pymutant-state/baseline.json`.
- Use `pymutant_baseline_status` to inspect validity and drift reasons.
- Use `pymutant_baseline_refresh` to force-reset runtime mutation artifacts and write a fresh baseline.
- `pymutant_run` auto-resets runtime mutation state on baseline drift and reports this in `data.baseline.auto_reset_applied`.

## Stuck mutmut Recovery

If runs hang or return interruption codes (`-15`, `-9`):

```bash
uv run python -c "from pymutant import runner; print(runner.kill_stuck_mutmut())"
```

The mutation gate also performs this cleanup automatically up to `--max-interruptions`.

## Local CI With act

Use Colima socket and run CI locally:

```bash
export DOCKER_HOST=unix:///Users/tim/.colima/default/docker.sock #4.
act pull_request -W .github/workflows/ci.yml --container-architecture linux/amd64 --container-daemon-socket -
```

In `act` mode, only `verify` is executed; mutation benchmark/build jobs are skipped to avoid QEMU timing and remote fetch drift.
