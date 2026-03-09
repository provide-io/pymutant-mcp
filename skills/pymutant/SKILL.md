# Mutation Testing Skill

**Triggers:** user mentions "mutation test", "mutant", "mutation score", "surviving mutant", "killed mutant", "test quality score", "mutmut", "test coverage gap", "improve test quality"

## What Mutation Testing Is

Mutation testing measures test suite quality by:
1. Making small code changes ("mutants") — flipped operators, changed values, removed branches
2. Running the test suite against each mutant
3. Counting how many mutants are "killed" (tests fail) vs "survive" (tests pass)

A surviving mutant means your tests don't catch that code change — a gap in test coverage.

**Mutation score** = killed / (killed + survived + timeout + segfault). A score of 80%+ is generally good.

## Tool Chain

All tools are provided by the `pymutant` server. Chain them in this order:

```
pymutant_run           → execute mutations (slow, ~minutes)
pymutant_compute_score → get current score
pymutant_results       → list all mutants with status
pymutant_surviving_mutants → survivors with diffs, grouped by file
pymutant_show_diff     → diff for a single mutant
pymutant_update_score_history → save score snapshot to mutation-score.json
pymutant_score_history → load full score trend
```

## Full Workflow

### When user says "run mutation testing" or uses `/mutation-run`:
1. Call `pymutant_run` (optionally with paths/max_children)
2. Call `pymutant_compute_score` — report score prominently
3. Call `pymutant_surviving_mutants` — get diffs for each survivor
4. For each survivor: read the diff, identify missing test, write a pytest function
5. Call `pymutant_update_score_history` with a descriptive label
6. Summarize tests added

### When user says "analyze" or uses `/mutation-analyze`:
1. Call `pymutant_results` — check if any results exist
2. Call `pymutant_compute_score`
3. Call `pymutant_surviving_mutants`
4. Suggest (don't write) tests for each survivor
5. Call `pymutant_score_history` — show trend if ≥ 2 entries

## Reading a Mutant Diff

A mutant diff looks like:
```diff
--- a/src/mymodule.py
+++ b/src/mymodule.py
@@ -12,7 +12,7 @@
 def validate_age(age: int) -> bool:
-    return age >= 18
+    return age > 18
```

To kill this mutant: test that `validate_age(18)` returns `True`.
The mutant changes `>=` to `>`, so a test asserting the boundary value (18) dies.

## Writing a Killing Test

A killing test must:
1. Exercise the exact code path the mutant changes
2. Assert the expected value so the assertion fails when the mutant is applied

**Template:**
```python
def test_<function>_<what_it_tests>():
    # Kills mutant: <mutant_name>
    # Mutant changes: <original> -> <mutated>
    result = <function_under_test>(<boundary_input>)
    assert result == <expected_original_value>
```

**Operator mutation patterns:**
- `>` → `>=` or `<`: test the boundary value
- `+` → `-`: test with non-zero operands, assert exact result
- `and` → `or`: test both True/False combinations
- `not` removed: test the falsy case explicitly
- String constant changed: assert exact string in output
- Return value changed: assert the return value explicitly

See `references/test-generation-patterns.md` for detailed patterns.

## Common Pitfalls

- **Don't test implementation details** — test observable behavior
- **Don't write trivially True assertions** — `assert True` kills nothing
- **One focused assertion per killing test** — isolate what you're testing
- **Place tests near the code** — in the same test file that already covers this module
- **Check for no_tests mutants** — these indicate completely untested code paths

## Status Codes

See `references/status-codes.md` for full status code table and what each means.

## Concepts Reference

See `references/mutmut-concepts.md` for mutmut internals, file structure, and key concepts.
