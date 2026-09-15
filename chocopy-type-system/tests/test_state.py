#!/usr/bin/env python3
"""
Tests for ChocoPy type system implementation.

"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, "/app")
from chocopy_types import ChocoPyTypeSystem  # noqa: E402


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture(scope="module")
def ts():
    """Primary type system backed by /app/hierarchy.json."""
    return ChocoPyTypeSystem("/app/hierarchy.json")


@pytest.fixture(scope="module")
def ts2():
    """Secondary type system with a different hierarchy, for robustness."""
    hierarchy = {
        "classes": {
            "object": {"super": None, "attrs": {}, "methods": {
                "__init__": {"params": ["object"], "return": "<None>"}
            }},
            "int": {"super": "object", "attrs": {}, "methods": {
                "__init__": {"params": ["object"], "return": "<None>"}
            }},
            "bool": {"super": "object", "attrs": {}, "methods": {
                "__init__": {"params": ["object"], "return": "<None>"}
            }},
            "str": {"super": "object", "attrs": {}, "methods": {
                "__init__": {"params": ["object"], "return": "<None>"}
            }},
            "P": {"super": "object", "attrs": {"p_val": "int"}, "methods": {
                "__init__": {"params": ["P"], "return": "<None>"},
                "act": {"params": ["P", "int"], "return": "str"}
            }},
            "Q": {"super": "P", "attrs": {"q_val": "str"}, "methods": {
                "__init__": {"params": ["Q"], "return": "<None>"},
                "act": {"params": ["Q", "int"], "return": "str"}
            }},
            "R": {"super": "P", "attrs": {}, "methods": {
                "__init__": {"params": ["R"], "return": "<None>"},
                "act": {"params": ["R", "str"], "return": "str"}
            }},
            "S": {"super": "Q", "attrs": {"s_flag": "bool"}, "methods": {
                "__init__": {"params": ["S"], "return": "<None>"},
                "extra": {"params": ["S"], "return": "int"}
            }},
            "T": {"super": "Q", "attrs": {}, "methods": {
                "__init__": {"params": ["T"], "return": "<None>"}
            }},
        }
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, dir="/tmp"
    ) as f:
        json.dump(hierarchy, f)
        path = f.name
    ts = ChocoPyTypeSystem(path)
    yield ts
    os.unlink(path)


# ================================================================
# 0. Hierarchy Reconstruction
# ================================================================

class TestHierarchy:
    def test_hierarchy_exists(self):
        assert os.path.exists("/app/hierarchy.json"), \
            "hierarchy.json must be created at /app/hierarchy.json"

    def test_hierarchy_all_classes_present(self):
        with open("/app/hierarchy.json") as f:
            data = json.load(f)
        expected = {"object", "int", "bool", "str", "A", "B", "C", "D", "E", "F", "G"}
        assert set(data["classes"].keys()) == expected

    def test_hierarchy_superclasses(self):
        with open("/app/hierarchy.json") as f:
            data = json.load(f)
        classes = data["classes"]
        assert classes["object"]["super"] is None
        assert classes["int"]["super"] == "object"
        assert classes["bool"]["super"] == "object"
        assert classes["str"]["super"] == "object"
        assert classes["A"]["super"] == "object"
        assert classes["B"]["super"] == "A"
        assert classes["C"]["super"] == "A"
        assert classes["D"]["super"] == "B"
        assert classes["E"]["super"] == "B"
        assert classes["F"]["super"] == "object"
        assert classes["G"]["super"] == "F"

    def test_hierarchy_attrs(self):
        with open("/app/hierarchy.json") as f:
            data = json.load(f)
        classes = data["classes"]
        assert classes["object"]["attrs"] == {}
        assert classes["int"]["attrs"] == {}
        assert classes["bool"]["attrs"] == {}
        assert classes["str"]["attrs"] == {}
        assert classes["A"]["attrs"] == {"x": "int"}
        assert classes["B"]["attrs"] == {"y": "bool"}
        assert classes["C"]["attrs"] == {"z": "str"}
        assert classes["D"]["attrs"] == {"w": "int"}
        assert classes["E"]["attrs"] == {}
        assert classes["F"]["attrs"] == {"val": "int"}
        assert classes["G"]["attrs"] == {"name": "str"}

    def test_hierarchy_methods(self):
        with open("/app/hierarchy.json") as f:
            data = json.load(f)
        classes = data["classes"]
        assert classes["A"]["methods"]["foo"] == {"params": ["A", "int"], "return": "str"}
        assert classes["A"]["methods"]["bar"] == {"params": ["A"], "return": "object"}
        assert classes["B"]["methods"]["foo"] == {"params": ["B", "int"], "return": "str"}
        assert classes["B"]["methods"]["baz"] == {"params": ["B", "str"], "return": "int"}
        assert classes["C"]["methods"]["bar"] == {"params": ["C"], "return": "object"}
        assert classes["D"]["methods"]["qux"] == {"params": ["D", "A"], "return": "bool"}
        assert classes["E"]["methods"]["baz"] == {"params": ["E", "str"], "return": "int"}
        assert classes["F"]["methods"]["compute"] == {"params": ["F", "int", "int"], "return": "int"}
        assert classes["G"]["methods"]["compute"] == {"params": ["G", "int", "int"], "return": "int"}

    def test_type_tag_ordering(self):
        """User-defined class order must match assembly prototype type tags."""
        with open("/app/hierarchy.json") as f:
            data = json.load(f)
        user_classes = [
            k for k in data["classes"]
            if k not in ("object", "int", "bool", "str")
        ]
        assert user_classes == ["A", "C", "F", "B", "G", "D", "E"], \
            "Class order must match compiler_output.s type tags: A=4,C=5,F=6,B=7,G=8,D=9,E=10"


# ================================================================
# 1. Conformance  (t1 <= t2)
# ================================================================

class TestConforms:
    def test_reflexive_class(self, ts):
        assert ts.conforms("A", "A") is True

    def test_reflexive_int(self, ts):
        assert ts.conforms("int", "int") is True

    def test_direct_subclass(self, ts):
        assert ts.conforms("B", "A") is True

    def test_transitive_subclass(self, ts):
        assert ts.conforms("D", "A") is True

    def test_wrong_direction(self, ts):
        assert ts.conforms("A", "B") is False

    def test_unrelated_classes(self, ts):
        assert ts.conforms("B", "F") is False

    def test_siblings(self, ts):
        assert ts.conforms("B", "C") is False

    def test_builtin_to_object(self, ts):
        assert ts.conforms("int", "object") is True
        assert ts.conforms("bool", "object") is True
        assert ts.conforms("str", "object") is True

    def test_list_to_object(self, ts):
        assert ts.conforms("[int]", "object") is True
        assert ts.conforms("[[str]]", "object") is True

    def test_list_reflexive(self, ts):
        assert ts.conforms("[int]", "[int]") is True
        assert ts.conforms("[[A]]", "[[A]]") is True

    def test_list_not_covariant(self, ts):
        """[Dog] does NOT conform to [Animal] -- list types are invariant."""
        assert ts.conforms("[B]", "[A]") is False
        assert ts.conforms("[int]", "[bool]") is False

    def test_nested_list_unrelated(self, ts):
        assert ts.conforms("[[int]]", "[[str]]") is False
        assert ts.conforms("[[int]]", "[int]") is False

    def test_none_conforms(self, ts):
        assert ts.conforms("<None>", "<None>") is True
        assert ts.conforms("<None>", "object") is True
        assert ts.conforms("<None>", "int") is False
        assert ts.conforms("<None>", "A") is False
        assert ts.conforms("<None>", "[int]") is False

    def test_empty_conforms(self, ts):
        assert ts.conforms("<Empty>", "<Empty>") is True
        assert ts.conforms("<Empty>", "object") is True
        assert ts.conforms("<Empty>", "[int]") is False
        assert ts.conforms("<Empty>", "A") is False

    def test_deep_chain(self, ts):
        """D -> B -> A -> object"""
        assert ts.conforms("D", "object") is True
        assert ts.conforms("D", "B") is True

    # --- Secondary hierarchy ---
    def test_second_hierarchy_basic(self, ts2):
        assert ts2.conforms("S", "Q") is True
        assert ts2.conforms("S", "P") is True
        assert ts2.conforms("S", "object") is True
        assert ts2.conforms("S", "R") is False
        assert ts2.conforms("T", "S") is False


# ================================================================
# 2. Assignment Compatibility  (t1 <=_a t2)
# ================================================================

class TestAssignable:
    def test_via_conformance(self, ts):
        assert ts.is_assignable("D", "A") is True
        assert ts.is_assignable("int", "int") is True

    def test_none_to_user_class(self, ts):
        assert ts.is_assignable("<None>", "A") is True
        assert ts.is_assignable("<None>", "B") is True

    def test_none_to_object(self, ts):
        assert ts.is_assignable("<None>", "object") is True

    def test_none_to_primitives(self, ts):
        """<None> cannot be assigned to int, bool, str."""
        assert ts.is_assignable("<None>", "int") is False
        assert ts.is_assignable("<None>", "bool") is False
        assert ts.is_assignable("<None>", "str") is False

    def test_none_to_list(self, ts):
        assert ts.is_assignable("<None>", "[int]") is True
        assert ts.is_assignable("<None>", "[A]") is True
        assert ts.is_assignable("<None>", "[[str]]") is True

    def test_empty_to_list(self, ts):
        assert ts.is_assignable("<Empty>", "[int]") is True
        assert ts.is_assignable("<Empty>", "[A]") is True
        assert ts.is_assignable("<Empty>", "[[int]]") is True

    def test_empty_to_non_list(self, ts):
        assert ts.is_assignable("<Empty>", "int") is False
        assert ts.is_assignable("<Empty>", "A") is False
        assert ts.is_assignable("<Empty>", "object") is True  # via <=

    def test_list_none_to_list_class(self, ts):
        """[<None>] <=_a [A] because <None> <=_a A."""
        assert ts.is_assignable("[<None>]", "[A]") is True

    def test_list_none_to_list_int(self, ts):
        """[<None>] NOT <=_a [int] because <None> NOT <=_a int."""
        assert ts.is_assignable("[<None>]", "[int]") is False

    def test_list_none_to_list_list(self, ts):
        """[<None>] <=_a [[int]] because <None> <=_a [int]."""
        assert ts.is_assignable("[<None>]", "[[int]]") is True

    def test_list_types_not_covariant(self, ts):
        """[Dog] NOT <=_a [Animal], because rule 4 only works with [<None>]."""
        assert ts.is_assignable("[B]", "[A]") is False
        assert ts.is_assignable("[int]", "[bool]") is False

    def test_wrong_direction(self, ts):
        assert ts.is_assignable("A", "D") is False

    def test_none_to_none(self, ts):
        assert ts.is_assignable("<None>", "<None>") is True

    def test_none_to_empty(self, ts):
        assert ts.is_assignable("<None>", "<Empty>") is True  # rule 2

    def test_empty_to_none(self, ts):
        assert ts.is_assignable("<Empty>", "<None>") is False

    # --- Secondary hierarchy ---
    def test_second_assignable(self, ts2):
        assert ts2.is_assignable("<None>", "P") is True
        assert ts2.is_assignable("<Empty>", "[P]") is True
        assert ts2.is_assignable("[<None>]", "[P]") is True
        assert ts2.is_assignable("[<None>]", "[int]") is False


# ================================================================
# 3. Join  (t1 ⊔ t2)
# ================================================================

class TestJoin:
    def test_same_type(self, ts):
        assert ts.join("A", "A") == "A"
        assert ts.join("int", "int") == "int"

    def test_subtype(self, ts):
        assert ts.join("B", "A") == "A"
        assert ts.join("D", "A") == "A"

    def test_siblings(self, ts):
        """B and C are siblings under A."""
        assert ts.join("B", "C") == "A"

    def test_cousins(self, ts):
        """D (B's child) and C (A's child)."""
        assert ts.join("D", "C") == "A"

    def test_deep_cousins(self, ts):
        """D and E are siblings under B."""
        assert ts.join("D", "E") == "B"

    def test_unrelated_trees(self, ts):
        """B (under A) and F (under object)."""
        assert ts.join("B", "F") == "object"

    def test_builtins(self, ts):
        assert ts.join("int", "str") == "object"
        assert ts.join("int", "bool") == "object"

    def test_list_types_unrelated(self, ts):
        """List types are not covariant -- join is object."""
        assert ts.join("[int]", "[str]") == "object"
        assert ts.join("[A]", "[B]") == "object"

    def test_none_with_class(self, ts):
        assert ts.join("<None>", "A") == "A"
        assert ts.join("A", "<None>") == "A"

    def test_none_with_int(self, ts):
        """<None> NOT <=_a int, so join is object."""
        assert ts.join("<None>", "int") == "object"

    def test_none_with_list(self, ts):
        assert ts.join("<None>", "[int]") == "[int]"

    def test_empty_with_list(self, ts):
        assert ts.join("<Empty>", "[int]") == "[int]"
        assert ts.join("[A]", "<Empty>") == "[A]"

    def test_empty_with_class(self, ts):
        """<Empty> NOT <=_a A, A NOT <=_a <Empty>. LCA = object."""
        assert ts.join("<Empty>", "A") == "object"

    def test_none_and_empty(self, ts):
        """<None> <=_a <Empty> (rule 2), so join = <Empty>."""
        assert ts.join("<None>", "<Empty>") == "<Empty>"

    def test_list_none_and_list_class(self, ts):
        """[<None>] <=_a [A], so join = [A]."""
        assert ts.join("[<None>]", "[A]") == "[A]"

    def test_list_none_and_list_int(self, ts):
        """[<None>] NOT <=_a [int], so join = object."""
        assert ts.join("[<None>]", "[int]") == "object"

    # --- Secondary hierarchy ---
    def test_second_join(self, ts2):
        assert ts2.join("S", "T") == "Q"
        assert ts2.join("S", "R") == "P"
        assert ts2.join("Q", "R") == "P"
        assert ts2.join("T", "R") == "P"


# ================================================================
# 4. Method Resolution
# ================================================================

class TestResolveMethod:
    def test_direct_method(self, ts):
        m = ts.resolve_method("B", "baz")
        assert m is not None
        assert m["params"] == ["B", "str"]
        assert m["return"] == "int"
        assert m["defining_class"] == "B"

    def test_inherited_method(self, ts):
        """D inherits bar from A."""
        m = ts.resolve_method("D", "bar")
        assert m is not None
        assert m["defining_class"] == "A"
        assert m["return"] == "object"

    def test_overridden_method(self, ts):
        """B overrides foo from A."""
        m = ts.resolve_method("B", "foo")
        assert m is not None
        assert m["defining_class"] == "B"

    def test_deep_inherited(self, ts):
        """D inherits foo from B (which overrides A)."""
        m = ts.resolve_method("D", "foo")
        assert m is not None
        assert m["defining_class"] == "B"

    def test_nonexistent(self, ts):
        assert ts.resolve_method("A", "nonexistent") is None

    def test_non_class(self, ts):
        assert ts.resolve_method("[int]", "foo") is None


# ================================================================
# 5. Method Override Validation
# ================================================================

class TestMethodOverride:
    def test_valid_override_b_foo(self, ts):
        """B.foo overrides A.foo -- same return and param types."""
        assert ts.check_method_override("B", "foo") is True

    def test_valid_override_c_bar(self, ts):
        assert ts.check_method_override("C", "bar") is True

    def test_valid_override_e_baz(self, ts):
        assert ts.check_method_override("E", "baz") is True

    def test_new_method_not_override(self, ts):
        """D.qux is new (not overriding)."""
        assert ts.check_method_override("D", "qux") is True

    def test_invalid_override_wrong_params(self, ts2):
        """In ts2: R.act has params (R, str) but P.act has params (P, int).
        The param type differs -- invalid override."""
        assert ts2.check_method_override("R", "act") is False

    def test_valid_override_q_act(self, ts2):
        """Q.act matches P.act signature (except self)."""
        assert ts2.check_method_override("Q", "act") is True


# ================================================================
# 6. Binary Operator Types
# ================================================================

class TestBinaryOp:
    # Arithmetic
    def test_int_arithmetic(self, ts):
        for op in ["+", "-", "*", "//", "%"]:
            assert ts.type_of_binary_op(op, "int", "int") == "int"

    def test_invalid_arithmetic(self, ts):
        assert ts.type_of_binary_op("+", "int", "str") is None
        assert ts.type_of_binary_op("-", "str", "str") is None

    # Comparisons
    def test_int_comparisons(self, ts):
        for op in ["<", "<=", ">", ">="]:
            assert ts.type_of_binary_op(op, "int", "int") == "bool"

    def test_invalid_comparison(self, ts):
        assert ts.type_of_binary_op("<", "str", "str") is None

    # Equality
    def test_equality(self, ts):
        assert ts.type_of_binary_op("==", "int", "int") == "bool"
        assert ts.type_of_binary_op("!=", "bool", "bool") == "bool"
        assert ts.type_of_binary_op("==", "str", "str") == "bool"

    def test_equality_mixed(self, ts):
        """Cannot compare int == str."""
        assert ts.type_of_binary_op("==", "int", "str") is None

    def test_equality_classes(self, ts):
        """== only works on int, bool, str -- not on classes."""
        assert ts.type_of_binary_op("==", "A", "A") is None

    # Logical
    def test_logical(self, ts):
        assert ts.type_of_binary_op("and", "bool", "bool") == "bool"
        assert ts.type_of_binary_op("or", "bool", "bool") == "bool"

    def test_invalid_logical(self, ts):
        assert ts.type_of_binary_op("and", "int", "int") is None

    # String concat
    def test_str_concat(self, ts):
        assert ts.type_of_binary_op("+", "str", "str") == "str"

    # List concat
    def test_list_concat_same(self, ts):
        assert ts.type_of_binary_op("+", "[int]", "[int]") == "[int]"

    def test_list_concat_join(self, ts):
        """[B] + [C] has type [join(B, C)] = [A]."""
        assert ts.type_of_binary_op("+", "[B]", "[C]") == "[A]"

    def test_list_concat_unrelated(self, ts):
        """[int] + [str] has type [join(int, str)] = [object]."""
        assert ts.type_of_binary_op("+", "[int]", "[str]") == "[object]"

    # is
    def test_is_valid(self, ts):
        assert ts.type_of_binary_op("is", "A", "B") == "bool"
        assert ts.type_of_binary_op("is", "<None>", "A") == "bool"
        assert ts.type_of_binary_op("is", "[int]", "<None>") == "bool"

    def test_is_invalid_primitives(self, ts):
        assert ts.type_of_binary_op("is", "int", "int") is None
        assert ts.type_of_binary_op("is", "str", "A") is None
        assert ts.type_of_binary_op("is", "A", "bool") is None


# ================================================================
# 7. Unary Operator Types
# ================================================================

class TestUnaryOp:
    def test_negate(self, ts):
        assert ts.type_of_unary_op("-", "int") == "int"

    def test_not(self, ts):
        assert ts.type_of_unary_op("not", "bool") == "bool"

    def test_invalid(self, ts):
        assert ts.type_of_unary_op("-", "str") is None
        assert ts.type_of_unary_op("not", "int") is None


# ================================================================
# 8. List Display Type
# ================================================================

class TestListDisplay:
    def test_empty(self, ts):
        assert ts.type_of_list_display([]) == "<Empty>"

    def test_homogeneous_int(self, ts):
        assert ts.type_of_list_display(["int", "int", "int"]) == "[int]"

    def test_mixed_siblings(self, ts):
        """[B(), C()] has type [join(B, C)] = [A]."""
        assert ts.type_of_list_display(["B", "C"]) == "[A]"

    def test_mixed_with_none(self, ts):
        """[None, Animal()] has type [join(<None>, A)] = [A]."""
        assert ts.type_of_list_display(["<None>", "A"]) == "[A]"

    def test_mixed_none_int(self, ts):
        """[None, 1] has type [join(<None>, int)] = [object]."""
        assert ts.type_of_list_display(["<None>", "int"]) == "[object]"

    def test_deep_hierarchy(self, ts):
        """[D(), E()] has type [join(D, E)] = [B]."""
        assert ts.type_of_list_display(["D", "E"]) == "[B]"

    def test_single(self, ts):
        assert ts.type_of_list_display(["A"]) == "[A]"

    def test_three_way_join(self, ts):
        """[D(), C(), G()] = [join(join(D, C), G)] = [join(A, G)] = [object]."""
        assert ts.type_of_list_display(["D", "C", "G"]) == "[object]"


# ================================================================
# 9. Conditional Expression Type
# ================================================================

class TestConditional:
    def test_same_type(self, ts):
        assert ts.type_of_conditional("int", "int") == "int"

    def test_subtype(self, ts):
        assert ts.type_of_conditional("B", "A") == "A"

    def test_siblings(self, ts):
        assert ts.type_of_conditional("B", "C") == "A"

    def test_none_and_class(self, ts):
        assert ts.type_of_conditional("<None>", "A") == "A"

    def test_none_and_int(self, ts):
        assert ts.type_of_conditional("<None>", "int") == "object"


# ================================================================
# 10. Method Call Type
# ================================================================

class TestMethodCall:
    def test_simple_call(self, ts):
        """B.baz(str) -> int"""
        result = ts.type_of_method_call("B", "baz", ["str"])
        assert result == "int"

    def test_inherited_call(self, ts):
        """D inherits bar() from A -> object"""
        result = ts.type_of_method_call("D", "bar", [])
        assert result == "object"

    def test_overridden_call(self, ts):
        """D inherits foo(int) from B -> str"""
        result = ts.type_of_method_call("D", "foo", ["int"])
        assert result == "str"

    def test_arg_assignable(self, ts):
        """D.qux takes A param, passing B is OK (B <=_a A)."""
        result = ts.type_of_method_call("D", "qux", ["B"])
        assert result == "bool"

    def test_arg_none_assignable(self, ts):
        """D.qux takes A param, passing <None> is OK."""
        result = ts.type_of_method_call("D", "qux", ["<None>"])
        assert result == "bool"

    def test_wrong_arg_count(self, ts):
        result = ts.type_of_method_call("B", "baz", [])
        assert result is None

    def test_wrong_arg_type(self, ts):
        """B.baz expects str, passing int is invalid."""
        result = ts.type_of_method_call("B", "baz", ["int"])
        assert result is None

    def test_nonexistent_method(self, ts):
        result = ts.type_of_method_call("A", "nonexistent", [])
        assert result is None

    def test_non_class_receiver(self, ts):
        result = ts.type_of_method_call("[int]", "foo", [])
        assert result is None

    def test_multiarg_call(self, ts):
        """F.compute(int, int) -> int"""
        result = ts.type_of_method_call("F", "compute", ["int", "int"])
        assert result == "int"


# ================================================================
# 11. Index Type
# ================================================================

class TestIndex:
    def test_str_index(self, ts):
        assert ts.type_of_index("str", "int") == "str"

    def test_list_index(self, ts):
        assert ts.type_of_index("[int]", "int") == "int"
        assert ts.type_of_index("[A]", "int") == "A"
        assert ts.type_of_index("[[int]]", "int") == "[int]"

    def test_invalid_index_type(self, ts):
        assert ts.type_of_index("[int]", "str") is None

    def test_non_indexable(self, ts):
        assert ts.type_of_index("int", "int") is None
        assert ts.type_of_index("A", "int") is None


# ================================================================
# 12. Attribute Access
# ================================================================

class TestAttrAccess:
    def test_own_attr(self, ts):
        assert ts.type_of_attr_access("A", "x") == "int"

    def test_inherited_attr(self, ts):
        """B inherits x from A."""
        assert ts.type_of_attr_access("B", "x") == "int"

    def test_child_attr(self, ts):
        assert ts.type_of_attr_access("B", "y") == "bool"

    def test_deep_inherited(self, ts):
        """D inherits x from A through B."""
        assert ts.type_of_attr_access("D", "x") == "int"
        assert ts.type_of_attr_access("D", "y") == "bool"
        assert ts.type_of_attr_access("D", "w") == "int"

    def test_nonexistent(self, ts):
        assert ts.type_of_attr_access("A", "nonexistent") is None

    def test_non_class(self, ts):
        assert ts.type_of_attr_access("[int]", "x") is None


# ================================================================
# 13. Constructor Type
# ================================================================

class TestConstructor:
    def test_class(self, ts):
        assert ts.type_of_constructor("A") == "A"
        assert ts.type_of_constructor("D") == "D"
        assert ts.type_of_constructor("int") == "int"

    def test_invalid(self, ts):
        assert ts.type_of_constructor("[int]") is None
        assert ts.type_of_constructor("<None>") is None


# ================================================================
# 14. Type Tags
# ================================================================

class TestTypeTags:
    def test_builtin_tags(self, ts):
        assert ts.get_type_tag("int") == 1
        assert ts.get_type_tag("bool") == 2
        assert ts.get_type_tag("str") == 3

    def test_list_tag(self, ts):
        assert ts.get_type_tag("[int]") == -1
        assert ts.get_type_tag("[[str]]") == -1
        assert ts.get_type_tag("[A]") == -1

    def test_user_defined_tags(self, ts):
        """User-defined classes get sequential tags starting at 4,
        ordered as in hierarchy.json (matching assembly prototype tags)."""
        assert ts.get_type_tag("A") == 4
        assert ts.get_type_tag("C") == 5
        assert ts.get_type_tag("F") == 6
        assert ts.get_type_tag("B") == 7
        assert ts.get_type_tag("G") == 8
        assert ts.get_type_tag("D") == 9
        assert ts.get_type_tag("E") == 10

    def test_second_hierarchy_tags(self, ts2):
        assert ts2.get_type_tag("P") == 4
        assert ts2.get_type_tag("Q") == 5
        assert ts2.get_type_tag("R") == 6
        assert ts2.get_type_tag("S") == 7
        assert ts2.get_type_tag("T") == 8


# ================================================================
# 15. Dispatch Tables
# ================================================================

class TestDispatchTable:
    def test_object_table(self, ts):
        table = ts.get_dispatch_table("object")
        assert table == [("__init__", "object")]

    def test_a_table(self, ts):
        table = ts.get_dispatch_table("A")
        assert table == [
            ("__init__", "A"),
            ("foo", "A"),
            ("bar", "A"),
        ]

    def test_b_table(self, ts):
        """B overrides __init__ and foo, inherits bar, adds baz."""
        table = ts.get_dispatch_table("B")
        assert table == [
            ("__init__", "B"),
            ("foo", "B"),
            ("bar", "A"),
            ("baz", "B"),
        ]

    def test_c_table(self, ts):
        """C overrides __init__ and bar, inherits foo."""
        table = ts.get_dispatch_table("C")
        assert table == [
            ("__init__", "C"),
            ("foo", "A"),
            ("bar", "C"),
        ]

    def test_d_table(self, ts):
        """D overrides __init__, inherits foo/bar/baz from B, adds qux."""
        table = ts.get_dispatch_table("D")
        assert table == [
            ("__init__", "D"),
            ("foo", "B"),
            ("bar", "A"),
            ("baz", "B"),
            ("qux", "D"),
        ]

    def test_e_table(self, ts):
        """E overrides __init__ and baz, inherits foo and bar."""
        table = ts.get_dispatch_table("E")
        assert table == [
            ("__init__", "E"),
            ("foo", "B"),
            ("bar", "A"),
            ("baz", "E"),
        ]

    def test_g_table(self, ts):
        """G overrides __init__ and compute from F."""
        table = ts.get_dispatch_table("G")
        assert table == [
            ("__init__", "G"),
            ("compute", "G"),
        ]

    def test_slot_preservation(self, ts):
        """foo is at index 1 in A, B, C, D, E dispatch tables."""
        for cls in ["A", "B", "C", "D", "E"]:
            table = ts.get_dispatch_table(cls)
            assert table[1][0] == "foo", f"foo not at index 1 for class {cls}"


# ================================================================
# 16. Attribute Layout
# ================================================================

class TestAttrLayout:
    def test_object_no_attrs(self, ts):
        assert ts.get_attr_layout("object") == []

    def test_a_layout(self, ts):
        assert ts.get_attr_layout("A") == [("x", "int")]

    def test_b_layout(self, ts):
        """B inherits x from A, adds y."""
        assert ts.get_attr_layout("B") == [("x", "int"), ("y", "bool")]

    def test_d_layout(self, ts):
        """D inherits x, y from B (via A), adds w."""
        assert ts.get_attr_layout("D") == [
            ("x", "int"),
            ("y", "bool"),
            ("w", "int"),
        ]

    def test_e_layout(self, ts):
        """E inherits from B but adds no new attrs."""
        assert ts.get_attr_layout("E") == [("x", "int"), ("y", "bool")]

    def test_g_layout(self, ts):
        """G inherits val from F, adds name."""
        assert ts.get_attr_layout("G") == [("val", "int"), ("name", "str")]


# ================================================================
# 17. Object Size
# ================================================================

class TestObjectSize:
    def test_object_size(self, ts):
        assert ts.get_object_size("object") == 3  # header only

    def test_a_size(self, ts):
        assert ts.get_object_size("A") == 4  # 3 + 1 attr

    def test_b_size(self, ts):
        assert ts.get_object_size("B") == 5  # 3 + 2 attrs

    def test_d_size(self, ts):
        assert ts.get_object_size("D") == 6  # 3 + 3 attrs

    def test_e_size(self, ts):
        assert ts.get_object_size("E") == 5  # 3 + 2 inherited attrs

    def test_g_size(self, ts):
        assert ts.get_object_size("G") == 5  # 3 + 2 attrs
