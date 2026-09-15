
"""
Tests for the GraphQL Value Completion Engine.

Verifies spec-compliant behavior per GraphQL Specification (Oct 2021)
Section 6.4.3 (Value Completion) including:
  - Non-Null error propagation to the nearest nullable ancestor
  - Scalar result coercion (Int 32-bit boundaries, Float finite checks, ID integer acceptance)
  - Error path tracking through nested objects and list indices
  - List + NonNull type combinations
"""

import json
import subprocess
import pytest
from typing import Any

CLI_CMD = ["npx", "--yes", "tsx", "/app/src/cli.ts"]


def run_engine(root_type: dict, resolved_values: dict) -> dict:
    """Run the engine CLI with the given type and values, return parsed JSON response."""
    input_data = json.dumps({"rootType": root_type, "resolvedValues": resolved_values})
    result = subprocess.run(
        CLI_CMD,
        input=input_data,
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/app",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Engine exited with code {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return json.loads(result.stdout.strip())


# ─── Type Descriptor Helpers ───────────────────────────────────────

def t_scalar(name: str) -> dict:
    return {"kind": "Scalar", "name": name}

def t_enum(name: str, values: list[str]) -> dict:
    return {"kind": "Enum", "name": name, "values": values}

def t_list(of_type: dict) -> dict:
    return {"kind": "List", "ofType": of_type}

def t_nonnull(of_type: dict) -> dict:
    return {"kind": "NonNull", "ofType": of_type}

def t_object(name: str, fields: dict[str, dict]) -> dict:
    return {
        "kind": "Object",
        "name": name,
        "fields": {k: {"type": v} for k, v in fields.items()},
    }

def field_error(msg: str) -> dict:
    return {"__error__": msg}


# ═══════════════════════════════════════════════════════════════════
# 1. BASIC NULLABLE / NON-NULL FIELDS
# ═══════════════════════════════════════════════════════════════════

class TestBasicNullability:
    """Test basic nullable and non-nullable field behavior."""

    def test_nullable_field_returns_value(self):
        root = t_object("Query", {"greeting": t_scalar("String")})
        resp = run_engine(root, {"greeting": "hello"})
        assert resp["data"] == {"greeting": "hello"}
        assert "errors" not in resp

    def test_nullable_field_returns_null(self):
        root = t_object("Query", {"greeting": t_scalar("String")})
        resp = run_engine(root, {"greeting": None})
        assert resp["data"] == {"greeting": None}
        assert "errors" not in resp

    def test_nonnull_field_returns_value(self):
        root = t_object("Query", {"greeting": t_nonnull(t_scalar("String"))})
        resp = run_engine(root, {"greeting": "hello"})
        assert resp["data"] == {"greeting": "hello"}
        assert "errors" not in resp

    def test_nonnull_field_returns_null_nulls_root(self):
        """When a top-level NonNull field resolves to null, data must be null."""
        root = t_object("Query", {"greeting": t_nonnull(t_scalar("String"))})
        resp = run_engine(root, {"greeting": None})
        assert resp["data"] is None
        assert len(resp["errors"]) == 1
        assert resp["errors"][0]["path"] == ["greeting"]
        assert "non-nullable" in resp["errors"][0]["message"].lower() or \
               "non-null" in resp["errors"][0]["message"].lower()


# ═══════════════════════════════════════════════════════════════════
# 2. NON-NULL ERROR PROPAGATION
# ═══════════════════════════════════════════════════════════════════

class TestNonNullPropagation:
    """Test that NonNull violations propagate to the nearest nullable ancestor."""

    def test_nullable_parent_nonnull_child_returns_null(self):
        """A nullable object containing a NonNull field that returns null:
        the entire parent must be nulled."""
        inner = t_object("Inner", {"value": t_nonnull(t_scalar("String"))})
        root = t_object("Query", {"nest": inner})
        resp = run_engine(root, {"nest": {"value": None}})
        assert resp["data"] == {"nest": None}
        assert len(resp["errors"]) == 1
        err = resp["errors"][0]
        assert err["path"] == ["nest", "value"]

    def test_deep_nonnull_chain_propagates_to_first_nullable(self):
        """Deep chain: Query.nest?(Inner1!.inner2!(Inner2!.leaf!))
        When leaf resolves null, propagation nulls 'nest' (first nullable)."""
        inner2 = t_object("Inner2", {"leaf": t_nonnull(t_scalar("String"))})
        inner1 = t_object("Inner1", {"inner2": t_nonnull(inner2)})
        root = t_object("Query", {"nest": inner1})
        resp = run_engine(root, {"nest": {"inner2": {"leaf": None}}})
        assert resp["data"] == {"nest": None}
        assert len(resp["errors"]) == 1
        assert resp["errors"][0]["path"] == ["nest", "inner2", "leaf"]

    def test_nonnull_sibling_propagates_parent_null(self):
        """Object with a NonNull field that errors and a nullable field.
        The entire parent object must be nulled, losing the sibling value."""
        inner = t_object("DataType", {
            "ok": t_scalar("String"),
            "bad": t_nonnull(t_scalar("String")),
        })
        root = t_object("Query", {"nest": inner})
        resp = run_engine(root, {"nest": {"ok": "fine", "bad": None}})
        assert resp["data"] == {"nest": None}
        assert len(resp["errors"]) == 1
        assert resp["errors"][0]["path"] == ["nest", "bad"]

    def test_all_root_nonnull_fields_error(self):
        """When all root fields are NonNull and all error, data must be null."""
        root = t_object("Query", {
            "a": t_nonnull(t_scalar("String")),
            "b": t_nonnull(t_scalar("Int")),
        })
        resp = run_engine(root, {"a": None, "b": None})
        assert resp["data"] is None
        assert len(resp["errors"]) >= 1

    def test_field_error_at_nonnull_propagates(self):
        """A FieldError at a NonNull field propagates to nullable parent."""
        inner = t_object("DataType", {
            "value": t_nonnull(t_scalar("String")),
        })
        root = t_object("Query", {"nest": inner})
        resp = run_engine(root, {"nest": {"value": field_error("resolver failed")}})
        assert resp["data"] == {"nest": None}
        assert len(resp["errors"]) == 1
        assert resp["errors"][0]["message"] == "resolver failed"
        assert resp["errors"][0]["path"] == ["nest", "value"]


# ═══════════════════════════════════════════════════════════════════
# 3. LIST COMPLETION & LIST + NONNULL COMBINATIONS
# ═══════════════════════════════════════════════════════════════════

class TestListCompletion:
    """Test list value completion including NonNull item types."""

    def test_nullable_list_items(self):
        """[String] with some null items — nulls are fine, no errors."""
        root = t_object("Query", {"items": t_list(t_scalar("String"))})
        resp = run_engine(root, {"items": ["a", None, "c"]})
        assert resp["data"] == {"items": ["a", None, "c"]}
        assert "errors" not in resp

    def test_nonnull_list_items_one_null(self):
        """[String!] where one item is null — entire list must become null."""
        root = t_object("Query", {"items": t_list(t_nonnull(t_scalar("String")))})
        resp = run_engine(root, {"items": ["a", None, "c"]})
        assert resp["data"] == {"items": None}
        assert len(resp["errors"]) == 1

    def test_nonnull_list_nonnull_items_one_null(self):
        """[String!]! where one item is null — list nulls, propagates to parent."""
        root = t_object("Query", {
            "items": t_nonnull(t_list(t_nonnull(t_scalar("String")))),
        })
        resp = run_engine(root, {"items": ["a", None, "c"]})
        assert resp["data"] is None
        assert len(resp["errors"]) >= 1

    def test_error_path_includes_list_index(self):
        """Error paths in list items must include the numeric index."""
        root = t_object("Query", {
            "items": t_list(t_nonnull(t_scalar("String"))),
        })
        resp = run_engine(root, {"items": ["ok", None, "ok"]})
        assert resp["data"] == {"items": None}
        assert len(resp["errors"]) == 1
        # The error path must include the index 1
        assert 1 in resp["errors"][0]["path"]

    def test_list_field_error_with_index(self):
        """FieldError in a nullable list item — error path includes index."""
        root = t_object("Query", {
            "items": t_list(t_scalar("String")),
        })
        resp = run_engine(root, {"items": ["ok", field_error("item failed"), "ok"]})
        assert resp["data"]["items"] == ["ok", None, "ok"]
        assert len(resp["errors"]) == 1
        err = resp["errors"][0]
        assert err["message"] == "item failed"
        assert err["path"] == ["items", 1]

    def test_nested_list_of_objects_with_nonnull(self):
        """[Inner!] where Inner has a NonNull field that fails.
        The object nulls, causing the NonNull item to null, causing the list to null."""
        inner = t_object("Inner", {"val": t_nonnull(t_scalar("String"))})
        root = t_object("Query", {
            "items": t_list(t_nonnull(inner)),
        })
        values = {"items": [{"val": "ok"}, {"val": None}, {"val": "ok"}]}
        resp = run_engine(root, values)
        assert resp["data"] == {"items": None}
        assert len(resp["errors"]) == 1
        assert resp["errors"][0]["path"] == ["items", 1, "val"]


# ═══════════════════════════════════════════════════════════════════
# 4. SCALAR RESULT COERCION
# ═══════════════════════════════════════════════════════════════════

class TestIntCoercion:
    """Int scalar: 32-bit signed integer, reject non-integer and out-of-range."""

    def test_valid_int(self):
        root = t_object("Query", {"n": t_scalar("Int")})
        resp = run_engine(root, {"n": 42})
        assert resp["data"] == {"n": 42}
        assert "errors" not in resp

    def test_int_from_boolean(self):
        root = t_object("Query", {"n": t_scalar("Int")})
        resp = run_engine(root, {"n": True})
        assert resp["data"] == {"n": 1}

    def test_int_from_string(self):
        root = t_object("Query", {"n": t_scalar("Int")})
        resp = run_engine(root, {"n": "123"})
        assert resp["data"] == {"n": 123}

    def test_int_rejects_float(self):
        root = t_object("Query", {"n": t_scalar("Int")})
        resp = run_engine(root, {"n": 1.5})
        assert resp["data"] == {"n": None}
        assert len(resp["errors"]) == 1

    def test_int_rejects_above_max(self):
        """Int must reject values > 2^31 - 1 (2147483647)."""
        root = t_object("Query", {"n": t_scalar("Int")})
        resp = run_engine(root, {"n": 2147483648})
        assert resp["data"] == {"n": None}
        assert len(resp["errors"]) == 1

    def test_int_rejects_below_min(self):
        """Int must reject values < -2^31 (-2147483648)."""
        root = t_object("Query", {"n": t_scalar("Int")})
        resp = run_engine(root, {"n": -2147483649})
        assert resp["data"] == {"n": None}
        assert len(resp["errors"]) == 1

    def test_int_accepts_boundary_max(self):
        """Int must accept 2^31 - 1 (2147483647)."""
        root = t_object("Query", {"n": t_scalar("Int")})
        resp = run_engine(root, {"n": 2147483647})
        assert resp["data"] == {"n": 2147483647}
        assert "errors" not in resp

    def test_int_accepts_boundary_min(self):
        """Int must accept -2^31 (-2147483648)."""
        root = t_object("Query", {"n": t_scalar("Int")})
        resp = run_engine(root, {"n": -2147483648})
        assert resp["data"] == {"n": -2147483648}
        assert "errors" not in resp


class TestFloatCoercion:
    """Float scalar: IEEE 754 double, reject NaN and Infinity."""

    def test_valid_float(self):
        root = t_object("Query", {"f": t_scalar("Float")})
        resp = run_engine(root, {"f": 3.14})
        assert resp["data"]["f"] == pytest.approx(3.14)
        assert "errors" not in resp

    def test_float_rejects_nan(self):
        """Float must reject NaN as a non-finite value."""
        root = t_object("Query", {"f": t_scalar("Float")})
        # NaN in JSON becomes null, so we use a string "NaN" scenario instead.
        # Actually, we can test via a coercion path: a string "NaN" should fail.
        # But more importantly, we test number NaN via a computation.
        # Since JSON can't represent NaN, we'll test via a NonNull path
        # where the engine computes NaN internally (through string coercion).
        resp = run_engine(root, {"f": "not_a_number"})
        assert resp["data"] == {"f": None}
        assert len(resp["errors"]) == 1

    def test_float_from_integer(self):
        root = t_object("Query", {"f": t_scalar("Float")})
        resp = run_engine(root, {"f": 42})
        assert resp["data"]["f"] == 42.0
        assert "errors" not in resp

    def test_float_from_boolean(self):
        root = t_object("Query", {"f": t_scalar("Float")})
        resp = run_engine(root, {"f": True})
        assert resp["data"]["f"] == 1.0


class TestIDCoercion:
    """ID scalar: accepts both string and integer, serializes as string."""

    def test_id_from_string(self):
        root = t_object("Query", {"id": t_scalar("ID")})
        resp = run_engine(root, {"id": "abc-123"})
        assert resp["data"] == {"id": "abc-123"}
        assert "errors" not in resp

    def test_id_from_integer(self):
        """ID must accept integer values and serialize them as strings."""
        root = t_object("Query", {"id": t_scalar("ID")})
        resp = run_engine(root, {"id": 42})
        assert resp["data"] == {"id": "42"}
        assert "errors" not in resp

    def test_id_from_negative_integer(self):
        root = t_object("Query", {"id": t_scalar("ID")})
        resp = run_engine(root, {"id": -7})
        assert resp["data"] == {"id": "-7"}
        assert "errors" not in resp


class TestStringCoercion:
    def test_string_from_number(self):
        root = t_object("Query", {"s": t_scalar("String")})
        resp = run_engine(root, {"s": 123})
        assert resp["data"] == {"s": "123"}

    def test_string_from_boolean(self):
        root = t_object("Query", {"s": t_scalar("String")})
        resp = run_engine(root, {"s": True})
        assert resp["data"] == {"s": "true"}


class TestBooleanCoercion:
    def test_boolean_true(self):
        root = t_object("Query", {"b": t_scalar("Boolean")})
        resp = run_engine(root, {"b": True})
        assert resp["data"] == {"b": True}

    def test_boolean_from_nonzero(self):
        root = t_object("Query", {"b": t_scalar("Boolean")})
        resp = run_engine(root, {"b": 42})
        assert resp["data"] == {"b": True}

    def test_boolean_from_zero(self):
        root = t_object("Query", {"b": t_scalar("Boolean")})
        resp = run_engine(root, {"b": 0})
        assert resp["data"] == {"b": False}


class TestEnumCoercion:
    def test_valid_enum(self):
        root = t_object("Query", {"status": t_enum("Status", ["ACTIVE", "INACTIVE"])})
        resp = run_engine(root, {"status": "ACTIVE"})
        assert resp["data"] == {"status": "ACTIVE"}
        assert "errors" not in resp

    def test_invalid_enum(self):
        root = t_object("Query", {"status": t_enum("Status", ["ACTIVE", "INACTIVE"])})
        resp = run_engine(root, {"status": "DELETED"})
        assert resp["data"] == {"status": None}
        assert len(resp["errors"]) == 1


# ═══════════════════════════════════════════════════════════════════
# 5. COMPLEX / INTEGRATION SCENARIOS
# ═══════════════════════════════════════════════════════════════════

class TestComplexScenarios:
    """Multi-layer tests combining NonNull propagation, lists, and scalars."""

    def test_complex_tree_nullable_fields(self):
        """Complex tree of nullable fields all returning null — no errors."""
        inner = t_object("Inner", {
            "a": t_scalar("String"),
            "b": t_scalar("Int"),
        })
        root = t_object("Query", {
            "nest1": inner,
            "nest2": inner,
        })
        values = {
            "nest1": {"a": None, "b": None},
            "nest2": {"a": None, "b": None},
        }
        resp = run_engine(root, values)
        assert resp["data"] == {
            "nest1": {"a": None, "b": None},
            "nest2": {"a": None, "b": None},
        }
        assert "errors" not in resp

    def test_mixed_nullable_nonnull_fields_with_error(self):
        """Object with both nullable and NonNull fields. NonNull field errors.
        The entire parent nulls, but the error is only for the NonNull field."""
        inner = t_object("DataType", {
            "sync": t_scalar("String"),
            "syncNonNull": t_nonnull(t_scalar("String")),
        })
        root = t_object("Query", {"syncNest": inner})
        resp = run_engine(root, {"syncNest": {"sync": "hello", "syncNonNull": None}})
        assert resp["data"] == {"syncNest": None}
        assert len(resp["errors"]) == 1
        assert resp["errors"][0]["path"] == ["syncNest", "syncNonNull"]

    def test_multiple_nonnull_errors_in_parallel_branches(self):
        """Two sibling nullable objects each with NonNull child errors.
        Both parents null, each with its own error."""
        inner = t_object("DataType", {
            "required": t_nonnull(t_scalar("String")),
        })
        root = t_object("Query", {
            "branch1": inner,
            "branch2": inner,
        })
        values = {
            "branch1": {"required": None},
            "branch2": {"required": field_error("boom")},
        }
        resp = run_engine(root, values)
        assert resp["data"] == {"branch1": None, "branch2": None}
        assert len(resp["errors"]) == 2
        paths = [tuple(e["path"]) for e in resp["errors"]]
        assert ("branch1", "required") in paths
        assert ("branch2", "required") in paths

    def test_nonnull_int_boundary_in_list(self):
        """[Int!] with one value exceeding 32-bit boundary.
        Coercion fails → null → NonNull item violation → list nulls."""
        root = t_object("Query", {
            "nums": t_list(t_nonnull(t_scalar("Int"))),
        })
        resp = run_engine(root, {"nums": [1, 2147483648, 3]})
        assert resp["data"] == {"nums": None}
        assert len(resp["errors"]) >= 1
        # Error path must include the index
        err_paths = [e["path"] for e in resp["errors"]]
        assert any(1 in p for p in err_paths)

    def test_deeply_nested_propagation_with_field_error(self):
        """Three-level nesting: Query.a?(A.b!(B.c!(C.val!)))
        val resolves to FieldError → propagates all the way to 'a' becoming null.
        Only the original FieldError message appears in errors."""
        c_type = t_object("C", {"val": t_nonnull(t_scalar("String"))})
        b_type = t_object("B", {"c": t_nonnull(c_type)})
        a_type = t_object("A", {"b": t_nonnull(b_type)})
        root = t_object("Query", {"a": a_type})
        values = {"a": {"b": {"c": {"val": field_error("deep failure")}}}}
        resp = run_engine(root, values)
        assert resp["data"] == {"a": None}
        assert len(resp["errors"]) == 1
        assert resp["errors"][0]["message"] == "deep failure"
        assert resp["errors"][0]["path"] == ["a", "b", "c", "val"]

    def test_list_of_objects_partial_errors(self):
        """[Inner] (nullable items) where some objects have errors in nullable fields.
        Items with errors get null fields but the item and list survive."""
        inner = t_object("Inner", {"val": t_scalar("String")})
        root = t_object("Query", {"items": t_list(inner)})
        values = {
            "items": [
                {"val": "ok"},
                {"val": field_error("oops")},
                {"val": "also ok"},
            ]
        }
        resp = run_engine(root, values)
        assert resp["data"]["items"][0] == {"val": "ok"}
        assert resp["data"]["items"][1] == {"val": None}
        assert resp["data"]["items"][2] == {"val": "also ok"}
        assert len(resp["errors"]) == 1
        assert resp["errors"][0]["path"] == ["items", 1, "val"]
