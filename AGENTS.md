# Repository Guidelines

## Project Structure & Module Organization

- `src/pymutant/`: Python MCP server implementation (`main.py`, `runner/`, `results.py`, `score.py`, setup/init helpers).
- `src/repo_verify/`: Dev tooling (verify gate, benchmarks, mutation gate).
- `.claude/commands/`: Claude Code command docs (`mutation-run.md`, `mutation-analyze.md`).
- `.claude/skills/pymutant/`: Skill definition and references used by Claude workflows.
- Root `pyproject.toml`: single-package config with dev dependencies in `[dependency-groups]`.

## Build, Test, and Development Commands

- `uv` is the only supported package/tool runner in this repository (`pip` is not supported).
- `uv sync`: install dependencies from lockfile.
- `uv run pymutant --project-root .`: run the MCP server over stdio locally.
- `uv run ruff check .`: lint code (line length configured to 120).
- `uv run mypy src/pymutant src/repo_verify`: type-check modules.
- `uv run pytest`: run tests using configured `testpaths`.
- `uv run verify`: full CQ gate (ruff, max-loc, SPDX, mypy, bandit, docs, schemas, pytest 100%).

## Coding Style & Naming Conventions

- Python 3.11+ features are allowed; keep type hints on public functions.
- Use 4-space indentation and follow PEP 8 naming:
  - modules/functions: `snake_case`
  - classes: `PascalCase`
  - constants: `UPPER_SNAKE_CASE`
- Keep functions focused and return structured dictionaries for tool-facing responses.
- Run Ruff and MyPy before opening a PR.

## Testing Guidelines

- Framework: `pytest` (configured in root `pyproject.toml`).
- Name tests `test_*.py` and test functions `test_*`.
- Prefer fast unit tests around parsing/scoring logic (for example in `results.py` and `score.py`).
- For process-running code (`runner/`), mock subprocess calls instead of invoking real `mutmut` in unit tests.

## Commit & Pull Request Guidelines

- Use Conventional Commit style (for example, `feat: add mutmut setup validation`).
- Keep commits scoped to one logical change.
- PRs should include:
  - concise problem/solution description,
  - test/lint evidence (`uv run pytest`, `uv run ruff check .`, `uv run mypy src/pymutant src/repo_verify`),
  - linked issue (if applicable),
  - sample command output for behavior changes.

## Security & Configuration Tips

- Do not commit local environment artifacts (`.venv`, `mutants/`, generated caches).
- Treat paths and subprocess arguments as untrusted input; validate before shell execution.
