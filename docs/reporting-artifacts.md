<!-- SPDX-FileCopyrightText: Copyright (c) provide.io llc -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Reporting Artifacts

CI writes generated reports and build outputs under `dist/`.

## Verify Job

- `dist/bandit-report.json`: Bandit JSON output (uploaded as `bandit-report`).

## Benchmark Jobs

- `dist/benchmark-throughput.json`: throughput benchmark metrics (uploaded as `benchmark-throughput`).
- `dist/benchmark-quality.json`: quality benchmark metrics (uploaded as `benchmark-quality` or `release-benchmark-quality`).

## Build Job

- `dist/pymutant-*.whl`
- `dist/pymutant-*.tar.gz`
- `dist/pymutant_dev-*.whl`
- `dist/pymutant_dev-*.tar.gz`
- `dist/SHA256SUMS`

Artifacts are generated in CI and should not be committed.
