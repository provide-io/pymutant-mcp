# /mutation-analyze

Analyze existing mutation results without re-running mutations.

## Usage

```
/mutation-analyze [file_filter]
```

**Arguments:**
- `file_filter` — optional substring to filter results by source file path

## Workflow

### Step 1: Load results

Call `pymutant_results` with `include_killed=False` and any `file_filter`. If no results exist (empty mutants returned and no `mutants/` directory), advise the user to run `/mutation-run` first.

### Step 2: Compute score

Call `pymutant_compute_score`. Display:

```
Mutation score: 78.3% (47 killed / 60 total)
Survived: 13   No-tests: 2   Timeout: 0
```

### Step 3: Show survivors with analysis

Call `pymutant_surviving_mutants` (with `file_filter` if provided). For each surviving mutant:

1. Show the diff
2. Explain in plain English what behavior is untested
3. Suggest a specific test (without writing it) — describe what to assert

Example output:
```
## src/auth.py — 3 survivors

### auth.check_token__mutmut_7
Diff: `expiry > now` → `expiry >= now`
Analysis: No test checks a token with expiry == now. A token expiring exactly
at the current time should be treated as expired.
Suggested test: `assert check_token(token_expiring_now) is False`
```

### Step 4: Score trend (if history exists)

Call `pymutant_score_history`. If history has ≥ 2 entries, show a trend:

```
Score history:
  2026-03-01  65.0%  (baseline)
  2026-03-05  71.2%  (+6.2%)
  2026-03-07  78.3%  (+7.1%)  ← current
```

### Step 5: Prioritized recommendations

List the top 3–5 files with the most surviving mutants, ranked by survivor count. Recommend which file to tackle first based on:
- Number of survivors
- Complexity/risk of the code
- Whether no-test mutants indicate untested modules

## Notes

- This command reads existing results — it never triggers a new mutation run
- If `mutants/` doesn't exist, explain that `/mutation-run` must be run first
- Suggestions are descriptive — use `/mutation-run` to have Claude write the actual tests
