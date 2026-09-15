"""Tests for TypeSim implementation.

Verifies parser correctness, similarity score accuracy, and metric properties.
"""

import json
import sys

import pytest

sys.path.insert(0, "/app")

from typesim.parser import parse_type, TypeNode
from typesim.similarity import type_similarity

# Load test cases
with open("/app/test_cases.json") as f:
    TEST_CASES = json.load(f)

PARAMETRIZED_CASES = [
    (tc["id"], tc["a"], tc["b"], tc["expected"]) for tc in TEST_CASES
]


class TestParser:
    """Tests for the type annotation parser."""

    def test_simple_type(self):
        node = parse_type("int")
        assert node.name == "int"
        assert node.args == []
        assert node.is_variadic is False

    def test_generic_single_arg(self):
        node = parse_type("List[int]")
        assert node.name == "List"
        assert len(node.args) == 1
        assert node.args[0].name == "int"

    def test_generic_multi_arg(self):
        node = parse_type("Dict[str, int]")
        assert node.name == "Dict"
        assert len(node.args) == 2
        assert node.args[0].name == "str"
        assert node.args[1].name == "int"

    def test_nested_generic(self):
        node = parse_type("Dict[str, List[int]]")
        assert node.name == "Dict"
        assert len(node.args) == 2
        assert node.args[0].name == "str"
        assert node.args[1].name == "List"
        assert len(node.args[1].args) == 1
        assert node.args[1].args[0].name == "int"

    def test_nested_generic_multi_arg(self):
        """Nested generic with multiple args requires bracket-aware splitting."""
        node = parse_type("Dict[str, Dict[int, float]]")
        assert node.name == "Dict"
        assert len(node.args) == 2
        assert node.args[0].name == "str"
        assert node.args[1].name == "Dict"
        assert len(node.args[1].args) == 2
        assert node.args[1].args[0].name == "int"
        assert node.args[1].args[1].name == "float"

    def test_deeply_nested(self):
        node = parse_type("List[Dict[str, Tuple[int, ...]]]")
        assert node.name == "List"
        inner = node.args[0]
        assert inner.name == "Dict"
        assert len(inner.args) == 2
        assert inner.args[0].name == "str"
        assert inner.args[1].name == "Tuple"
        assert inner.args[1].is_variadic is True
        assert len(inner.args[1].args) == 1

    def test_optional_normalization(self):
        """Optional[X] must be normalized to Union[X, None]."""
        node = parse_type("Optional[int]")
        assert node.name == "Union", f"Expected Union, got {node.name}"
        assert len(node.args) == 2
        assert node.args[0].name == "int"
        assert node.args[1].name == "None"

    def test_optional_nested(self):
        node = parse_type("Optional[List[int]]")
        assert node.name == "Union"
        assert len(node.args) == 2
        assert node.args[0].name == "List"
        assert node.args[1].name == "None"

    def test_variadic_tuple(self):
        node = parse_type("Tuple[int, ...]")
        assert node.name == "Tuple"
        assert node.is_variadic is True
        assert len(node.args) == 1
        assert node.args[0].name == "int"

    def test_fixed_tuple(self):
        node = parse_type("Tuple[int, str, float]")
        assert node.name == "Tuple"
        assert node.is_variadic is False
        assert len(node.args) == 3

    def test_union(self):
        node = parse_type("Union[int, str]")
        assert node.name == "Union"
        assert len(node.args) == 2

    def test_union_with_generics(self):
        """Union with generic members requires bracket-aware splitting."""
        node = parse_type("Union[Dict[str, int], List[float]]")
        assert node.name == "Union"
        assert len(node.args) == 2
        assert node.args[0].name == "Dict"
        assert len(node.args[0].args) == 2
        assert node.args[1].name == "List"

    def test_union_flattening(self):
        """Nested unions must be flattened: Union[Union[A, B], C] -> Union[A, B, C]."""
        node = parse_type("Union[Union[int, str], float]")
        assert node.name == "Union"
        assert len(node.args) == 3, (
            f"Expected 3 args after flattening, got {len(node.args)}: "
            f"{[str(a) for a in node.args]}"
        )
        names = sorted(a.name for a in node.args)
        assert names == ["float", "int", "str"]

    def test_union_flattening_with_optional(self):
        """Optional[Union[A, B]] must normalize and flatten to Union[A, B, None]."""
        node = parse_type("Optional[Union[int, str]]")
        assert node.name == "Union"
        assert len(node.args) == 3, (
            f"Expected 3 args after normalization+flattening, got {len(node.args)}"
        )
        names = sorted(a.name for a in node.args)
        assert names == ["None", "int", "str"]

    def test_callable_simple(self):
        """Callable[[P], R] must parse correctly with double-bracket syntax."""
        node = parse_type("Callable[[int], bool]")
        assert node.name == "Callable"
        assert str(node) == "Callable[[int], bool]"

    def test_callable_multi_param(self):
        node = parse_type("Callable[[int, str, float], bool]")
        assert node.name == "Callable"
        assert str(node) == "Callable[[int, str, float], bool]"

    def test_callable_no_params(self):
        node = parse_type("Callable[[], None]")
        assert node.name == "Callable"
        assert str(node) == "Callable[[], None]"

    def test_callable_nested_params(self):
        """Callable with generic param types requires bracket-aware parsing."""
        node = parse_type("Callable[[Dict[str, int]], bool]")
        assert node.name == "Callable"
        assert str(node) == "Callable[[Dict[str, int]], bool]"

    def test_callable_nested_return(self):
        """Callable returning Callable."""
        node = parse_type("Callable[[int], Callable[[str], bool]]")
        assert node.name == "Callable"
        assert str(node) == "Callable[[int], Callable[[str], bool]]"

    def test_str_roundtrip(self):
        """str(parse_type(s)) should produce a canonical representation."""
        cases = [
            "int",
            "List[int]",
            "Dict[str, int]",
            "Union[int, str]",
            "Tuple[int, ...]",
            "Callable[[int, str], bool]",
            "Callable[[], None]",
            "Callable[[Dict[str, int]], bool]",
        ]
        for s in cases:
            assert str(parse_type(s)) == s, f"Roundtrip failed for: {s}"


class TestSimilarity:
    """Tests for the type similarity computation."""

    @pytest.mark.parametrize(
        "case_id,a_str,b_str,expected",
        PARAMETRIZED_CASES,
        ids=[f"case_{tc['id']}" for tc in TEST_CASES],
    )
    def test_similarity_score(self, case_id, a_str, b_str, expected):
        a = parse_type(a_str)
        b = parse_type(b_str)
        score = type_similarity(a, b)
        assert abs(score - expected) < 0.001, (
            f"Case {case_id}: sim({a_str}, {b_str}) = {score:.6f}, "
            f"expected {expected:.4f}"
        )

    def test_symmetry(self):
        """type_similarity(a, b) must equal type_similarity(b, a)."""
        pairs = [
            ("int", "Any"),
            ("List[int]", "List[str]"),
            ("Union[int, str]", "int"),
            ("Dict[str, int]", "Dict[int, str]"),
            ("Any", "List[int]"),
            ("Optional[int]", "int"),
            ("Callable[[int], bool]", "Callable[[str], bool]"),
            ("Callable[[int, str], bool]", "Callable[[int], bool]"),
            ("Callable[[int], bool]", "List[int]"),
        ]
        for a_str, b_str in pairs:
            a, b = parse_type(a_str), parse_type(b_str)
            fwd = type_similarity(a, b)
            rev = type_similarity(b, a)
            assert abs(fwd - rev) < 0.0001, (
                f"Symmetry violation: sim({a_str}, {b_str})={fwd:.6f} != "
                f"sim({b_str}, {a_str})={rev:.6f}"
            )

    def test_identity(self):
        """type_similarity(a, a) must be 1.0."""
        types = [
            "int",
            "List[int]",
            "Dict[str, int]",
            "Union[int, str]",
            "Tuple[int, ...]",
            "Dict[str, List[Tuple[int, ...]]]",
            "Callable[[int, str], bool]",
            "Callable[[], None]",
            "Callable[[Dict[str, int]], bool]",
        ]
        for t_str in types:
            a = parse_type(t_str)
            b = parse_type(t_str)
            score = type_similarity(a, b)
            assert score == 1.0, (
                f"Identity violation: sim({t_str}, {t_str}) = {score}"
            )

    def test_score_bounds(self):
        """All similarity scores must be in [0.0, 1.0]."""
        pairs = [
            ("int", "str"),
            ("Any", "int"),
            ("List[int]", "Dict[str, int]"),
            ("Union[int, str, float]", "bool"),
            ("Callable[[int], bool]", "List[int]"),
            ("Callable[[], None]", "None"),
            ("Callable[[Any], Any]", "Callable[[int], str]"),
        ]
        for a_str, b_str in pairs:
            a, b = parse_type(a_str), parse_type(b_str)
            score = type_similarity(a, b)
            assert 0.0 <= score <= 1.0, (
                f"Score out of bounds: sim({a_str}, {b_str}) = {score}"
            )
