# SPDX-FileCopyrightText: Copyright (c) provide.io llc
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    pass


def _type_ok(expected: str, value: Any) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True


def _validate(schema: dict[str, Any], value: Any, path: str = "$") -> None:
    schema_type = schema.get("type")
    if isinstance(schema_type, str) and not _type_ok(schema_type, value):
        raise ValidationError(f"{path}: expected type {schema_type}")

    if "const" in schema and value != schema["const"]:
        raise ValidationError(f"{path}: expected const {schema['const']!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in value:
                    raise ValidationError(f"{path}: missing required key {key!r}")

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, sub_schema in properties.items():
                if key in value and isinstance(sub_schema, dict):
                    _validate(sub_schema, value[key], f"{path}.{key}")

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate(item_schema, item, f"{path}[{idx}]")


def validate_file(data_path: Path, schema_path: Path) -> None:
    data = json.loads(data_path.read_text())
    schema = json.loads(schema_path.read_text())
    if not isinstance(schema, dict):
        raise ValidationError("schema root must be object")
    _validate(schema, data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    validate_file(Path(args.data), Path(args.schema))
    print("schema validation passed")


if __name__ == "__main__":  # pragma: no cover
    main()
