# /mutation-run

Run mutation testing end-to-end: execute mutations, show survivors, write killing tests.

## Usage

```
/mutation-run [paths...] [--no-rerun] [--max-children N]
```

**Arguments:**
- `paths` — optional source paths to mutate (e.g. `src/mymodule.py`)
- `--no-rerun` — skip running mutations, use existing results
- `--max-children N` — number of parallel workers

## Workflow

### Step 1: Run mutations (unless `--no-rerun`)

Call `pymutant_run` with any provided paths/options. Report the summary line.

If `--no-rerun` is passed and no `mutants/` directory exists, error and ask the user to run without `--no-rerun` first.

### Step 2: Compute and report score

Call `pymutant_compute_score`. Display:

```
Mutation score: 78.3% (47 killed / 60 total)
Survived: 13   No-tests: 2   Timeout: 0
```

### Step 3: Show surviving mutants

Call `pymutant_surviving_mutants`. For each source file with survivors:

```
## src/mymodule.py (3 surviving mutants)

### mymodule.my_func__mutmut_4
- Change: `x > 0` → `x >= 0`
- Missing test: boundary value x=0 is not asserted
```

### Step 4: Write killing tests

For each surviving mutant:

1. Identify the nearest `test_*.py` file (same package, or `tests/` root)
2. Read that test file to understand existing patterns
3. Write a focused pytest function that kills the mutant:
   - Name it `test_<mutant_description>_kills_mutant` or similar
   - Assert the exact boundary/value the mutant changes
   - Keep it minimal — one assertion that kills the mutant
4. Append the function to the test file

Example for a comparison flip (`>` → `>=`):
```python
def test_my_func_rejects_zero():
    # Mutant changes `x > 0` to `x >= 0` — zero must be rejected
    assert my_func(0) is False
```

### Step 5: Update score history

Call `pymutant_update_score_history` with a label summarizing what tests were added.

### Step 6: Summary

Report:
- How many mutants were targeted
- How many test functions were written
- Which files were modified
- New estimated score (note: requires re-running mutations to confirm)

## Notes

- Do not write tests that are trivially True or that test implementation details
- Prefer testing observable behavior (return values, side effects, exceptions)
- If a mutant cannot be killed by a unit test (e.g. it's in dead code), say so explicitly
- If `mutants/` is missing, mutmut has not been run — call `pymutant_run` first
