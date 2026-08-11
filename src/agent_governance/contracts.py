"""Stdlib JSON contract validator for governance schemas."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class ContractValidationError(ValueError):
    """Raised when a payload fails one of the governance JSON contracts."""


def load_schema(path: Path) -> dict[str, Any]:
    """Load a JSON schema file, verifying it defines an object schema."""
    with path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if schema.get("type") != "object":
        raise ContractValidationError(f"{path} must define an object schema")
    return schema


def validate_json_contract(payload: Any, schema: dict[str, Any]) -> None:
    """Validate against the conservative schema subset used by this package."""
    _validate(payload, schema, "$")


def _validate(value: Any, schema: dict[str, Any], path: str) -> None:
    if "type" in schema:
        expected = schema["type"]
        if not _matches_type(value, expected):
            raise ContractValidationError(
                f"{path}: expected type {_type_label(expected)}, got {_json_type(value)}"
            )

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(repr(item) for item in schema["enum"])
        raise ContractValidationError(
            f"{path}: expected one of {allowed}, got {value!r}"
        )

    if isinstance(value, dict):
        _validate_object(value, schema, path)
    elif isinstance(value, list):
        _validate_array(value, schema, path)
    elif isinstance(value, str):
        _validate_string(value, schema, path)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _validate_number(value, schema, path)


def _validate_object(value: dict[str, Any], schema: dict[str, Any], path: str) -> None:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in value:
            raise ContractValidationError(f"{path}: missing required field {key!r}")

    additional = schema.get("additionalProperties", True)
    for key, item in value.items():
        child_path = f"{path}.{key}"
        if key in properties:
            _validate(item, properties[key], child_path)
        elif additional is False:
            raise ContractValidationError(f"{child_path}: additional field is not allowed")
        elif isinstance(additional, dict):
            _validate(item, additional, child_path)


def _validate_array(value: list[Any], schema: dict[str, Any], path: str) -> None:
    if "minItems" in schema and len(value) < schema["minItems"]:
        raise ContractValidationError(
            f"{path}: expected at least {schema['minItems']} item(s)"
        )
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        raise ContractValidationError(
            f"{path}: expected at most {schema['maxItems']} item(s)"
        )
    if schema.get("uniqueItems") and len(value) != len(
        {json.dumps(item, sort_keys=True) for item in value}
    ):
        raise ContractValidationError(f"{path}: expected unique items")
    item_schema = schema.get("items")
    if item_schema:
        for index, item in enumerate(value):
            _validate(item, item_schema, f"{path}[{index}]")


def _validate_string(value: str, schema: dict[str, Any], path: str) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        raise ContractValidationError(f"{path}: expected length >= {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        raise ContractValidationError(f"{path}: expected length <= {schema['maxLength']}")
    if "pattern" in schema and not re.search(schema["pattern"], value):
        raise ContractValidationError(
            f"{path}: value does not match pattern {schema['pattern']!r}"
        )


def _validate_number(value: int | float, schema: dict[str, Any], path: str) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        raise ContractValidationError(f"{path}: expected value >= {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        raise ContractValidationError(f"{path}: expected value <= {schema['maximum']}")


def _matches_type(value: Any, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(_matches_type(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ContractValidationError(f"Unsupported schema type: {expected}")


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def _type_label(expected: str | list[str]) -> str:
    if isinstance(expected, list):
        return " or ".join(expected)
    return expected
