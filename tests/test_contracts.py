"""Tests for JSON contract validator."""

import json
import tempfile
from pathlib import Path

import pytest

from agent_governance.contracts import (
    ContractValidationError,
    load_schema,
    validate_json_contract,
)


class TestContractValidator:
    """Tests for the JSON contract validator."""

    def test_valid_object_schema(self):
        schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
        validate_json_contract({"name": "test"}, schema)

    def test_missing_required_field(self):
        schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
        with pytest.raises(ContractValidationError, match="missing required field"):
            validate_json_contract({}, schema)

    def test_wrong_type(self):
        schema = {"type": "object", "required": ["count"], "properties": {"count": {"type": "integer"}}}
        with pytest.raises(ContractValidationError, match="expected type integer"):
            validate_json_contract({"count": "not_int"}, schema)

    def test_enum_validation(self):
        schema = {"type": "object", "required": ["status"], "properties": {"status": {"type": "string", "enum": ["ok", "fail"]}}}
        validate_json_contract({"status": "ok"}, schema)
        with pytest.raises(ContractValidationError, match="expected one of"):
            validate_json_contract({"status": "invalid"}, schema)

    def test_additional_properties_false(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "string"}}}
        with pytest.raises(ContractValidationError, match="additional field is not allowed"):
            validate_json_contract({"a": "ok", "b": "extra"}, schema)

    def test_array_min_items(self):
        schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "minItems": 2, "items": {"type": "string"}}}}
        with pytest.raises(ContractValidationError, match="expected at least 2"):
            validate_json_contract({"items": ["one"]}, schema)

    def test_array_max_items(self):
        schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "maxItems": 1, "items": {"type": "string"}}}}
        validate_json_contract({"items": ["one"]}, schema)
        with pytest.raises(ContractValidationError, match="expected at most 1"):
            validate_json_contract({"items": ["one", "two"]}, schema)

    def test_unique_items(self):
        schema = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "uniqueItems": True, "items": {"type": "string"}}}}
        validate_json_contract({"items": ["a", "b"]}, schema)
        with pytest.raises(ContractValidationError, match="expected unique items"):
            validate_json_contract({"items": ["a", "a"]}, schema)

    def test_string_pattern(self):
        schema = {"type": "object", "required": ["email"], "properties": {"email": {"type": "string", "pattern": "@"}}}
        validate_json_contract({"email": "user@host"}, schema)
        with pytest.raises(ContractValidationError, match="does not match pattern"):
            validate_json_contract({"email": "no_at_sign"}, schema)

    def test_string_length(self):
        schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "string", "minLength": 2, "maxLength": 5}}}
        validate_json_contract({"x": "abc"}, schema)
        with pytest.raises(ContractValidationError, match="expected length >= 2"):
            validate_json_contract({"x": "a"}, schema)
        with pytest.raises(ContractValidationError, match="expected length <= 5"):
            validate_json_contract({"x": "abcdef"}, schema)

    def test_number_range(self):
        schema = {"type": "object", "required": ["age"], "properties": {"age": {"type": "integer", "minimum": 0, "maximum": 150}}}
        validate_json_contract({"age": 42}, schema)
        with pytest.raises(ContractValidationError, match="expected value >= 0"):
            validate_json_contract({"age": -1}, schema)

    def test_boolean_type(self):
        schema = {"type": "object", "required": ["flag"], "properties": {"flag": {"type": "boolean"}}}
        validate_json_contract({"flag": True}, schema)
        validate_json_contract({"flag": False}, schema)
        with pytest.raises(ContractValidationError):
            validate_json_contract({"flag": "not_bool"}, schema)

    def test_null_type(self):
        schema = {"type": "object", "required": ["opt"], "properties": {"opt": {"type": "null"}}}
        validate_json_contract({"opt": None}, schema)

    def test_load_schema_rejects_non_object(self, tmp_path):
        path = tmp_path / "schema.json"
        path.write_text(json.dumps({"type": "string"}))
        with pytest.raises(ContractValidationError, match="must define an object schema"):
            load_schema(path)

    def test_load_schema_valid(self, tmp_path):
        path = tmp_path / "schema.json"
        path.write_text(json.dumps({"type": "object"}))
        schema = load_schema(path)
        assert schema["type"] == "object"
