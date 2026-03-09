# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from validate_json_schema import ValidationError, validate_file


REQUIRED = [
    (Path('.ci/pymutant-profiles.json'), Path('schemas/profiles.schema.json')),
    (Path('.ci/pymutant-policy-baseline.json'), Path('schemas/policy-baseline.schema.json')),
]
def main() -> None:
    for data, schema in REQUIRED:
        validate_file(data, schema)

    print('repository schema validation passed')


if __name__ == '__main__':  # pragma: no cover
    try:
        main()
    except (ValidationError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
