# mutmut Status Codes

## Exit Code → Status Mapping

| Exit Code | Status | Meaning | What Claude Should Do |
|-----------|--------|---------|----------------------|
| `0` | **survived** | Tests passed with this mutant — the mutation was not detected | Write a test that kills this mutant |
| `1` | **killed** | Tests failed with this mutant — the mutation was detected | Nothing needed; test suite is working |
| `5` | **no_tests** | No tests cover this code path at all | Write tests to cover this code, not just kill the mutant |
| `34` | **skipped** | Mutant was skipped (e.g. excluded by config) | Investigate config if unexpected |
| `36` | **timeout** | Test run timed out for this mutant | Investigate slow tests; may indicate infinite loops or heavy I/O |
| `null` | **not_checked** | mutmut run was interrupted before reaching this mutant | Re-run mutations to get full results |

## Prioritization

When deciding which surviving mutants to tackle first:

1. **no_tests** (exit code 5): Highest priority — entire code paths have zero test coverage
2. **survived** (exit code 0): Standard priority — code is covered but the specific condition isn't tested
3. **timeout** (exit code 36): Investigate separately — may indicate test infrastructure issues
4. **not_checked** (null): Re-run mutations before analyzing

## Score Calculation

The mutation score formula used by this plugin:

```
score = killed / (killed + survived + timeout + crash)
```

**Excluded from denominator:**
- `no_tests` — can't kill a mutant with no tests; fix coverage first
- `skipped` — excluded by config, not a quality indicator
- `not_checked` — incomplete run, shouldn't penalize the score
- `crash` is included in the denominator because crashing mutants are not killed

## Interpreting Common Scenarios

### High survived count, low no_tests
Tests exist but aren't specific enough. Add boundary/edge case assertions.

### High no_tests count
Large portions of code are completely untested. Prioritize adding basic coverage before worrying about mutation score.

### High timeout count
Tests may be slow or have hanging I/O. Look for tests that don't mock external services.

### Score stuck below 60%
Usually means tests assert on happy-path only. Need to add negative cases, boundary values, and error path tests.

### Score above 85%
Strong test suite. Remaining survivors are often in hard-to-test edge cases (logging, error handling stubs).
