# Unified Policy Tooling Plan (Dedicated Repo, Pre-commit + CI)

## Summary
Create one dedicated **policy repo** with two modules (`pre-commit/` and `ci/`) and make `pymutant-mcp`, `undef-terminal`, and `undef-telemetry` consume it as the single source of truth for quality/security parity.  
Target parity model: **policy parity** (same governance categories), with repo-specific implementation where required.

## Implementation Changes

### 1. Create dedicated policy repo structure
- `pre-commit/`: shared hook definitions + release tagging strategy.
- `ci/`: reusable CI workflows/composite actions mirroring the same policy categories.
- `policy-matrix.yaml`: canonical list of required categories:
  - secrets
  - lint/format
  - typing
  - security
  - complexity
  - dead-code
  - license
  - docs/schema where applicable
  - test gate
  - optional mutation/perf manual hooks

### 2. Pre-commit module design
- Publish shared hooks from the dedicated repo (versioned tags).
- Standardize hook IDs and semantics for common categories across all repos.
- Keep repo-specific hooks as explicit exceptions:
  - frontend-specific hooks in `undef-terminal` (`tsc`, `biome`)
  - repo-specific docs/schema hooks in `pymutant-mcp`
- Keep heavy checks manual by default (mutation/perf).

### 3. CI module design
- Provide reusable workflows (or composite actions) that implement the same policy matrix as pre-commit.
- Ensure each app repo calls the reusable CI module with minimal repo-local overrides:
  - paths
  - language mix
  - mutation strategy

### 4. Adoption/migration in each repo
- Replace duplicated local hook logic with references to dedicated policy repo versions.
- Add a small repo-local “policy overrides” block for unavoidable differences (paths, frontend hooks, docs/schema hooks).
- Pin a version tag from the dedicated repo for deterministic behavior.

### 5. Parity enforcement
- Add a parity-audit command in dedicated repo that checks each consumer repo against `policy-matrix.yaml`.
- Fail CI when a required category is missing (unless explicitly waived in overrides).

## Test Plan / Acceptance

### 1. Dedicated repo validation
- Unit checks for hook/workflow rendering/validation.
- Snapshot tests for generated expected configs (if generator/template path is used).
- Tag/release smoke test for consumer compatibility.

### 2. Consumer repo validation
- In each repo: `pre-commit run --all-files` passes with new shared config references.
- CI reusable workflow passes on each repo’s default branch.
- Heavy hooks remain manual and callable on demand.

### 3. Parity acceptance criteria
- All three repos satisfy the canonical policy categories.
- Documented, explicit exceptions only (no silent drift).
- A single version bump process updates policy behavior across all consumers.

## Assumptions and Defaults
- Chosen defaults:
  - one dedicated policy repo with two modules
  - central team ownership
  - policy parity (not exact command parity)
  - heavy hooks manual
- Default implementation assumption:
  - use a published shared hooks repo model (versioned tags) for pre-commit consumption
- Optional future change:
  - split pre-commit and CI into separate repos only if release cadence or permissions diverge materially.
