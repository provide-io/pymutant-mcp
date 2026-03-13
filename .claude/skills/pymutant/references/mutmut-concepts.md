# mutmut Concepts Reference

## What is a Mutant?

A mutant is a copy of your source code with one small change applied — an operator flip, a constant change, a removed branch. mutmut generates these automatically using libcst (a Python AST library) to make syntactically valid transformations.

## Mutant Naming

Mutants are identified by keys like:
```
src.mypackage.mymodule.my_function__mutmut_3
```

The format is: `<dot.separated.module.path>.<function_name>__mutmut_<N>`

The `__mutmut_N` suffix identifies which mutation within the function.

## File Structure

After running mutmut, the project gets a `mutants/` directory:

```
mutants/
├── src/
│   └── mypackage/
│       └── mymodule.py.meta      ← JSON results for mymodule.py
└── mutmut-stats.json             ← overall run statistics
```

### Meta File Format

Each `.meta` file is a JSON object:
```json
{
  "exit_code_by_key": {
    "src.mypackage.mymodule.my_func__mutmut_1": 1,
    "src.mypackage.mymodule.my_func__mutmut_2": 0,
    "src.mypackage.mymodule.my_func__mutmut_3": 5
  },
  "durations_by_key": {
    "src.mypackage.mymodule.my_func__mutmut_1": 0.312
  },
  "type_check_error_by_key": {},
  "estimated_durations_by_key": {}
}
```

Exit codes: `0` = survived, `1` = killed, `5` = no tests, `34` = skipped, `36` = timeout, `null` = not checked.

## Running mutmut

```bash
# Run all mutations
mutmut run

# Run on specific paths
mutmut run src/mymodule.py

# Parallel execution
mutmut run --max-children 4

# Show a mutant's diff
mutmut show src.mypackage.mymodule.my_func__mutmut_3

# HTML report
mutmut html
```

## Trampoline Pattern

mutmut uses a "trampoline" to inject mutations without modifying source files. When running with mutations, it patches the module in memory via a special import hook. Source files are never written to during a test run.

## Parallelism

`--max-children N` controls how many pytest workers run in parallel. Each worker runs the full test suite against one mutant. Setting this too high can cause resource contention; too low slows things down. A reasonable default is `cpu_count - 1`.

## Common Mutation Types

| Mutation | Example |
|----------|---------|
| Arithmetic | `a + b` → `a - b` |
| Comparison | `x > 0` → `x >= 0`, `x < 0`, `x == 0` |
| Boolean | `a and b` → `a or b` |
| Unary | `not x` → `x` |
| Assignment | `x = 1` → `x = 2` (or other constants) |
| Return | `return True` → `return False` |
| String | `"hello"` → `""` or `"XX"` |
| Delete statement | Removes a line entirely |

## Prerequisites for Target Projects

The project being mutation-tested must have:
1. `mutmut` installed (e.g. `uv add mutmut --dev`)
2. A working `pytest` setup
3. A `setup.cfg`, `pyproject.toml`, or `mutmut.toml` configuring `paths_to_mutate` and `tests_dir`

Example `pyproject.toml` config:
```toml
[tool.mutmut]
paths_to_mutate = ["src/"]
tests_dir = ["tests/"]
```
