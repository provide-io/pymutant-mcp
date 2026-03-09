# Repository Guidelines

## Project Structure & Module Organization
- `server/src/pymutant/`: Python server implementation (`main.py`, `runner.py`, `results.py`, `score.py`, setup/init helpers).
- `commands/`: Claude command docs (`mutation-run.md`, `mutation-analyze.md`).
- `skills/pymutant/`: skill definition and references used by Codex/Claude workflows.
- Root `pyproject.toml`: workspace tooling config (Ruff, MyPy, pytest paths).
- `server/pyproject.toml`: package metadata and entrypoint (`pymutant`).

## Build, Test, and Development Commands
- `uv` is the only supported package/tool runner in this repository (`pip` is not supported).
- `uv sync`: install workspace dependencies from lockfile.
- `cd server && uv sync`: install server package dependencies.
- `cd server && uv run python -m pymutant`: run the server over stdio locally.
- `uv run ruff check .`: lint code (line length configured to 120).
- `uv run mypy server/src`: type-check server modules.
- `uv run pytest`: run tests using configured `testpaths`.

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
- For process-running code (`runner.py`), mock subprocess calls instead of invoking real `mutmut` in unit tests.

## Commit & Pull Request Guidelines
- This repository currently has no commit history; use Conventional Commit style going forward (for example, `feat: add mutmut setup validation`).
- Keep commits scoped to one logical change.
- PRs should include:
  - concise problem/solution description,
  - test/lint evidence (`uv run pytest`, `uv run ruff check .`, `uv run mypy server/src`),
  - linked issue (if applicable),
  - sample command output for behavior changes.

## Security & Configuration Tips
- Do not commit local environment artifacts (`.venv`, `mutants/`, generated caches).
- Treat paths and subprocess arguments as untrusted input; validate before shell execution.
