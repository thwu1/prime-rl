
"""
Tests for the TypeSim scoring engine.
Verifies parser correctness, similarity scoring, CLI single-pair mode, and batch mode.
"""

import json
import os
import subprocess
import sys
import importlib
import math
import tempfile

import pytest

TOL = 1e-4

# ── Expected similarity scores ──────────────────────────────────────────────
# These are the ground-truth scores computed from the reference algorithm.
EXPECTED_PAIRS = [
    # Identical types
    ("int", "int", 1.0),
    ("str", "str", 1.0),
    ("List[int]", "List[int]", 1.0),
    ("Dict[str, int]", "Dict[str, int]", 1.0),
    ("Tuple[int, str, float]", "Tuple[int, str, float]", 1.0),
    # Primitive mismatches
    ("int", "str", 0.059406),
    ("int", "float", 0.603774),
    ("str", "bytes", 0.790323),
    ("int", "bool", 1.0),
    ("int", "None", 0.02),
    # Container with different element types
    ("List[int]", "List[str]", 0.529703),
    ("List[int]", "Set[int]", 0.581633),
    ("Dict[str, int]", "Dict[str, float]", 0.900943),
    ("List[int]", "Tuple[int]", 0.7),
    # Nested generics
    ("Dict[str, List[int]]", "Dict[str, List[float]]", 0.950472),
    ("Dict[str, List[int]]", "Dict[int, List[int]]", 0.764851),
    ("List[Dict[str, int]]", "List[Dict[str, float]]", 0.950472),
    ("Dict[str, Tuple[int, ...]]", "Dict[str, Tuple[float, ...]]", 0.950472),
    # Depth 3+
    ("List[List[List[int]]]", "List[List[List[str]]]", 0.882426),
    ("Dict[str, Dict[str, List[int]]]", "Dict[str, Dict[str, List[float]]]", 0.987618),
    # Union types
    ("Union[int, str]", "Union[int, str]", 1.0),
    ("Union[int, str]", "Union[str, int]", 1.0),
    ("Union[int, str]", "int", 0.5),
    ("Union[int, str, float]", "Union[int, str]", 0.666667),
    ("Union[int, str]", "Union[float, bytes]", 0.697048),
    # Optional
    ("Optional[int]", "Optional[int]", 1.0),
    ("Optional[int]", "Optional[str]", 0.529703),
    ("Optional[int]", "int", 0.5),
    # One side has args, other doesn't
    ("List[int]", "int", 0.021127),
    ("Dict[str, int]", "str", 0.026667),
    # Callable
    ("Callable[[int, str], bool]", "Callable[[int, str], bool]", 1.0),
    ("Callable[[int], str]", "Callable[[float], str]", 0.900943),
]


# ── Parser tests ────────────────────────────────────────────────────────────

class TestParser:
    """Verify that the parser produces correct type trees."""

    @pytest.fixture(autouse=True)
    def _import(self):
        sys.path.insert(0, "/app")
        self.parser = importlib.import_module("typesim.parser")

    def test_primitive(self):
        t = self.parser.parse_type("int")
        assert t.name == "int"
        assert len(t.args) == 0

    def test_generic_list(self):
        t = self.parser.parse_type("List[int]")
        assert t.name == "list"
        assert len(t.args) == 1
        assert t.args[0].name == "int"

    def test_generic_dict(self):
        t = self.parser.parse_type("Dict[str, int]")
        assert t.name == "dict"
        assert len(t.args) == 2
        assert t.args[0].name == "str"
        assert t.args[1].name == "int"

    def test_nested_generic(self):
        t = self.parser.parse_type("Dict[str, List[int]]")
        assert t.name == "dict"
        assert t.args[1].name == "list"
        assert t.args[1].args[0].name == "int"

    def test_union(self):
        t = self.parser.parse_type("Union[int, str]")
        assert t.is_union
        assert len(t.args) == 2

    def test_optional(self):
        t = self.parser.parse_type("Optional[int]")
        assert t.is_union
        assert len(t.args) == 2
        names = {a.name for a in t.args}
        assert "int" in names
        assert "None" in names

    def test_callable(self):
        t = self.parser.parse_type("Callable[[int, str], bool]")
        assert t.name == "Callable"
        # Should have 3 args: int, str (params) + bool (return)
        assert len(t.args) == 3

    def test_tuple_variadic(self):
        t = self.parser.parse_type("Tuple[int, ...]")
        assert t.name == "tuple"
        # Should have at least 1 real type arg (int)
        real_args = [a for a in t.args if a.name != "..."]
        assert len(real_args) >= 1
        assert real_args[0].name == "int"

    def test_deeply_nested(self):
        t = self.parser.parse_type("List[List[List[int]]]")
        assert t.name == "list"
        assert t.args[0].name == "list"
        assert t.args[0].args[0].name == "list"
        assert t.args[0].args[0].args[0].name == "int"

    def test_frozenset(self):
        t = self.parser.parse_type("FrozenSet[str]")
        assert t.name == "frozenset"
        assert t.args[0].name == "str"


# ── Similarity scoring tests ────────────────────────────────────────────────

class TestSimilarity:
    """Verify that similarity scores match expected values."""

    @pytest.fixture(autouse=True)
    def _import(self):
        sys.path.insert(0, "/app")
        self.parser = importlib.import_module("typesim.parser")
        self.similarity = importlib.import_module("typesim.similarity")

    @pytest.mark.parametrize("a_str,b_str,expected", EXPECTED_PAIRS,
                             ids=[f"{a}_vs_{b}" for a, b, _ in EXPECTED_PAIRS])
    def test_similarity_score(self, a_str, b_str, expected):
        a = self.parser.parse_type(a_str)
        b = self.parser.parse_type(b_str)
        score = self.similarity.get_type_similarity(a, b)
        assert abs(score - expected) < TOL, (
            f"Expected {expected:.6f}, got {score:.6f} "
            f"for similarity({a_str!r}, {b_str!r})"
        )


# ── Symmetry tests ──────────────────────────────────────────────────────────

class TestSymmetry:
    """Verify similarity is symmetric: sim(a,b) == sim(b,a)."""

    @pytest.fixture(autouse=True)
    def _import(self):
        sys.path.insert(0, "/app")
        self.parser = importlib.import_module("typesim.parser")
        self.similarity = importlib.import_module("typesim.similarity")

    SYMMETRY_PAIRS = [
        ("int", "str"),
        ("List[int]", "Set[int]"),
        ("Dict[str, int]", "List[str]"),
        ("Union[int, str]", "float"),
        ("Optional[int]", "str"),
        ("Callable[[int], str]", "Callable[[float], int]"),
        ("Dict[str, List[int]]", "Dict[int, List[str]]"),
    ]

    @pytest.mark.parametrize("a_str,b_str", SYMMETRY_PAIRS)
    def test_symmetric(self, a_str, b_str):
        a = self.parser.parse_type(a_str)
        b = self.parser.parse_type(b_str)
        s1 = self.similarity.get_type_similarity(a, b)
        s2 = self.similarity.get_type_similarity(b, a)
        assert abs(s1 - s2) < TOL, (
            f"Asymmetric: sim({a_str},{b_str})={s1:.6f} != sim({b_str},{a_str})={s2:.6f}"
        )


# ── Range tests ─────────────────────────────────────────────────────────────

class TestRange:
    """Verify all scores are in [0, 1]."""

    @pytest.fixture(autouse=True)
    def _import(self):
        sys.path.insert(0, "/app")
        self.parser = importlib.import_module("typesim.parser")
        self.similarity = importlib.import_module("typesim.similarity")

    RANGE_PAIRS = [
        ("int", "str"), ("Any", "int"), ("None", "List[int]"),
        ("Dict[str, int]", "Tuple[float, bool]"),
        ("Union[int, str, float]", "Optional[bytes]"),
    ]

    @pytest.mark.parametrize("a_str,b_str", RANGE_PAIRS)
    def test_in_range(self, a_str, b_str):
        a = self.parser.parse_type(a_str)
        b = self.parser.parse_type(b_str)
        s = self.similarity.get_type_similarity(a, b)
        assert 0.0 - TOL <= s <= 1.0 + TOL, f"Score {s} out of [0,1] range"


# ── CLI tests ───────────────────────────────────────────────────────────────

class TestCLI:
    """Verify the CLI interface works correctly."""

    def test_single_pair(self):
        result = subprocess.run(
            ["python3", "/app/typesim/cli.py", "int", "int"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0
        val = float(result.stdout.strip())
        assert abs(val - 1.0) < TOL

    def test_single_pair_mismatch(self):
        result = subprocess.run(
            ["python3", "/app/typesim/cli.py", "int", "str"],
            capture_output=True, text=True, cwd="/app"
        )
        assert result.returncode == 0
        val = float(result.stdout.strip())
        assert abs(val - 0.0594) < 0.01

    def test_batch_mode(self):
        pairs = [
            {"a": "int", "b": "int"},
            {"a": "int", "b": "str"},
            {"a": "List[int]", "b": "List[float]"},
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(pairs, f)
            input_path = f.name
        output_path = input_path + ".out.json"
        try:
            result = subprocess.run(
                ["python3", "/app/typesim/cli.py", "--batch", input_path,
                 "--output", output_path],
                capture_output=True, text=True, cwd="/app"
            )
            assert result.returncode == 0, f"CLI error: {result.stderr}"
            with open(output_path) as f:
                output = json.load(f)
            assert len(output) == 3
            assert abs(output[0]["score"] - 1.0) < TOL
            assert abs(output[1]["score"] - 0.059406) < TOL
            for entry in output:
                assert "a" in entry
                assert "b" in entry
                assert "score" in entry
        finally:
            os.unlink(input_path)
            if os.path.exists(output_path):
                os.unlink(output_path)


# ── Package structure tests ─────────────────────────────────────────────────

class TestPackageStructure:
    """Verify the package has the required module structure."""

    def test_init_exists(self):
        assert os.path.isfile("/app/typesim/__init__.py")

    def test_parser_exists(self):
        assert os.path.isfile("/app/typesim/parser.py")

    def test_similarity_exists(self):
        assert os.path.isfile("/app/typesim/similarity.py")

    def test_cli_exists(self):
        assert os.path.isfile("/app/typesim/cli.py")

    def test_importable(self):
        sys.path.insert(0, "/app")
        mod = importlib.import_module("typesim")
        assert mod is not None

    def test_parser_importable(self):
        sys.path.insert(0, "/app")
        mod = importlib.import_module("typesim.parser")
        assert hasattr(mod, "parse_type")

    def test_similarity_importable(self):
        sys.path.insert(0, "/app")
        mod = importlib.import_module("typesim.similarity")
        assert hasattr(mod, "get_type_similarity")


# ── Attribute-set tests ─────────────────────────────────────────────────────

class TestAttributeSets:
    """Verify that attribute sets are derived from runtime dir() calls."""

    @pytest.fixture(autouse=True)
    def _import(self):
        sys.path.insert(0, "/app")
        self.similarity = importlib.import_module("typesim.similarity")

    def test_int_float_similarity_range(self):
        """int and float share numeric dunders — similarity should be moderate."""
        sys.path.insert(0, "/app")
        parser = importlib.import_module("typesim.parser")
        a = parser.parse_type("int")
        b = parser.parse_type("float")
        s = self.similarity.get_type_similarity(a, b)
        # Must be in reasonable range (0.5-0.7 based on Python 3.12 dir())
        assert 0.5 < s < 0.75, f"int vs float similarity {s} outside expected range"

    def test_any_matches_object(self):
        """Any uses dir(object) as its attributes."""
        sys.path.insert(0, "/app")
        parser = importlib.import_module("typesim.parser")
        a = parser.parse_type("Any")
        b = parser.parse_type("Any")
        s = self.similarity.get_type_similarity(a, b)
        assert abs(s - 1.0) < TOL
