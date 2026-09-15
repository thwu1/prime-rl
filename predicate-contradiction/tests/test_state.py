
import json
import os
import sqlite3
import pytest


def load_results():
    path = "/app/results.json"
    assert os.path.exists(path), "results.json not found at /app/results.json"
    with open(path) as f:
        data = json.load(f)
    assert isinstance(data, dict), "results.json root must be a JSON object"
    for key in ("equivalent", "implies", "contradicts"):
        assert key in data, f"results.json missing key '{key}'"
        assert isinstance(data[key], list), f"results.json['{key}'] must be a list"
    return data


def to_frozenset_pairs(pairs):
    """Convert list of [A, B] to set of frozensets (unordered pairs)."""
    return {frozenset(p) for p in pairs}


def to_tuple_pairs(pairs):
    """Convert list of [A, B] to set of tuples (ordered pairs)."""
    return {tuple(p) for p in pairs}


# ── Expected results ──────────────────────────────────────────────

EXPECTED_EQUIVALENT = {
    frozenset(["A1", "A2"]),   # 5mm = 0.5cm
    frozenset(["D1", "D2"]),   # interchangeable [Alice, Bob] ≡ [Bob, Alice]
    frozenset(["H1", "H2"]),   # interchangeable plaintiffs [Smith, Jones] ≡ [Jones, Smith]
}

EXPECTED_IMPLIES = {
    ("A3", "A1"),   # >= 2cm (20mm) implies >= 5mm
    ("A3", "A2"),   # >= 2cm (20mm) implies >= 0.5cm (5mm)
    ("A5", "A4"),   # < 3mm implies < 5mm (A4 normalized from truth=false, >= 5mm)
    ("B1", "B2"),   # >= 20g implies >= 0.5oz (~14.17g)
    ("C1", "C2"),   # truth=true implies truth=null
    ("C3", "C2"),   # truth=false implies truth=null
    ("E1", "E2"),   # generic entity implies specific entity
    ("G1", "G2"),   # >= 100mph implies >= 50mph
    ("G1", "G3"),   # >= 100mph (~160.93kph) implies >= 160kph
    ("G3", "G2"),   # >= 160kph (~99.42mph) implies >= 50mph
    ("I1", "I2"),   # > 1000g implies >= 1kg (strict ⊂ non-strict at boundary)
    ("J1", "J2"),   # all-generic implies specific [Alice, Bob]
    ("J1", "J3"),   # all-generic implies specific [Alice, Alice]
    ("J1", "J4"),   # all-generic implies mixed [generic, Alice]
    ("J4", "J2"),   # mixed [generic, Alice] implies [Alice, Bob] via interchangeability
    ("J4", "J3"),   # mixed [generic, Alice] implies [Alice, Alice]
}

EXPECTED_CONTRADICTS = {
    frozenset(["A1", "A4"]),   # >= 5mm vs < 5mm
    frozenset(["A1", "A5"]),   # >= 5mm vs < 3mm
    frozenset(["A2", "A4"]),   # >= 0.5cm vs < 5mm
    frozenset(["A2", "A5"]),   # >= 0.5cm vs < 3mm
    frozenset(["A3", "A4"]),   # >= 2cm vs < 5mm
    frozenset(["A3", "A5"]),   # >= 2cm vs < 3mm
    frozenset(["B1", "B3"]),   # >= 20g vs <= 10g
    frozenset(["B2", "B3"]),   # >= 0.5oz (~14.17g) vs <= 10g
    frozenset(["C1", "C3"]),   # true vs false
    frozenset(["D1", "D4"]),   # [Alice, Bob] true vs [Alice, Bob] false
    frozenset(["D2", "D4"]),   # [Bob, Alice] true vs [Alice, Bob] false (interchangeable)
    frozenset(["F1", "F2"]),   # true vs false (generic terms match)
    frozenset(["I1", "I3"]),   # > 1000g vs <= 1kg (disjoint at boundary)
    frozenset(["J1", "J5"]),   # all-generic true vs [Alice, Bob] false
    frozenset(["J2", "J5"]),   # [Alice, Bob] true vs [Alice, Bob] false
    frozenset(["J4", "J5"]),   # mixed [generic, Alice] true vs [Alice, Bob] false
}


# ── Main correctness tests ────────────────────────────────────────

class TestResultsFileFormat:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json")

    def test_results_is_valid_json(self):
        data = load_results()
        assert "equivalent" in data
        assert "implies" in data
        assert "contradicts" in data


class TestEquivalences:
    def test_exact_equivalences(self):
        data = load_results()
        actual = to_frozenset_pairs(data["equivalent"])
        assert actual == EXPECTED_EQUIVALENT, (
            f"Expected equivalences: {EXPECTED_EQUIVALENT}\n"
            f"Got: {actual}\n"
            f"Missing: {EXPECTED_EQUIVALENT - actual}\n"
            f"Spurious: {actual - EXPECTED_EQUIVALENT}"
        )


class TestImplications:
    def test_exact_implications(self):
        data = load_results()
        actual = to_tuple_pairs(data["implies"])
        assert actual == EXPECTED_IMPLIES, (
            f"Expected implications: {EXPECTED_IMPLIES}\n"
            f"Got: {actual}\n"
            f"Missing: {EXPECTED_IMPLIES - actual}\n"
            f"Spurious: {actual - EXPECTED_IMPLIES}"
        )


class TestContradictions:
    def test_exact_contradictions(self):
        data = load_results()
        actual = to_frozenset_pairs(data["contradicts"])
        assert actual == EXPECTED_CONTRADICTS, (
            f"Expected contradictions: {EXPECTED_CONTRADICTS}\n"
            f"Got: {actual}\n"
            f"Missing: {EXPECTED_CONTRADICTS - actual}\n"
            f"Spurious: {actual - EXPECTED_CONTRADICTS}"
        )


# ── Targeted spot checks ─────────────────────────────────────────

class TestUnitConversion:
    """Verify that cross-unit comparisons work correctly."""

    def test_millimeter_centimeter_equivalence(self):
        data = load_results()
        equiv = to_frozenset_pairs(data["equivalent"])
        assert frozenset(["A1", "A2"]) in equiv, "5mm and 0.5cm should be equivalent"

    def test_gram_ounce_implication(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("B1", "B2") in impl, ">= 20g should imply >= 0.5oz"

    def test_gram_ounce_not_reverse(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("B2", "B1") not in impl, ">= 0.5oz should NOT imply >= 20g"

    def test_mph_kph_implication(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("G1", "G3") in impl, ">= 100mph should imply >= 160kph"

    def test_kph_mph_not_reverse(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("G3", "G1") not in impl, ">= 160kph should NOT imply >= 100mph"

    def test_cross_unit_contradiction(self):
        data = load_results()
        contra = to_frozenset_pairs(data["contradicts"])
        assert frozenset(["B2", "B3"]) in contra, ">= 0.5oz vs <= 10g should contradict"


class TestTruthNormalization:
    """Verify truth=false normalization for comparison predicates."""

    def test_negated_geq_contradicts_geq(self):
        data = load_results()
        contra = to_frozenset_pairs(data["contradicts"])
        assert frozenset(["A1", "A4"]) in contra, (
            "truth=false on >= 5mm should normalize to < 5mm, contradicting >= 5mm"
        )

    def test_negated_geq_implied_by_smaller_lt(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("A5", "A4") in impl, "< 3mm should imply < 5mm (A4 normalized)"


class TestInterchangeableTerms:
    """Verify interchangeable group handling."""

    def test_swapped_specific_terms_equivalent(self):
        data = load_results()
        equiv = to_frozenset_pairs(data["equivalent"])
        assert frozenset(["D1", "D2"]) in equiv, (
            "[Alice, Bob] with interchangeability should be equivalent to [Bob, Alice]"
        )

    def test_different_specific_terms_not_related(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        contra = to_frozenset_pairs(data["contradicts"])
        equiv = to_frozenset_pairs(data["equivalent"])
        # D3 [Alice, Carol] should have no relationship with D1 [Alice, Bob]
        assert ("D1", "D3") not in impl
        assert ("D3", "D1") not in impl
        assert frozenset(["D1", "D3"]) not in contra
        assert frozenset(["D1", "D3"]) not in equiv

    def test_multi_position_interchangeable(self):
        data = load_results()
        equiv = to_frozenset_pairs(data["equivalent"])
        assert frozenset(["H1", "H2"]) in equiv, (
            "4-term predicate with interchangeable plaintiffs [Smith, Jones] "
            "should be equivalent to [Jones, Smith]"
        )


class TestGenericSpecific:
    """Verify generic-implies-specific semantics."""

    def test_generic_implies_specific(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("E1", "E2") in impl, "Generic entity should imply specific"

    def test_specific_not_implies_generic(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        equiv = to_frozenset_pairs(data["equivalent"])
        assert ("E2", "E1") not in impl, "Specific should NOT imply generic"
        assert frozenset(["E1", "E2"]) not in equiv


class TestNullTruth:
    """Verify truth=null (whether) semantics."""

    def test_true_implies_null(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("C1", "C2") in impl

    def test_false_implies_null(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("C3", "C2") in impl

    def test_null_never_contradicts(self):
        data = load_results()
        contra = to_frozenset_pairs(data["contradicts"])
        for pair in contra:
            assert "C2" not in pair, "truth=null predicate should never appear in contradictions"

    def test_null_not_implies_true(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("C2", "C1") not in impl

    def test_null_not_implies_false(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("C2", "C3") not in impl


class TestStrictBoundary:
    """Verify strict vs non-strict comparison boundary handling."""

    def test_strict_greater_implies_nonstrict_geq(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("I1", "I2") in impl, (
            "> 1000g should imply >= 1kg (strict ⊂ non-strict at same value)"
        )

    def test_nonstrict_geq_not_implies_strict_greater(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        equiv = to_frozenset_pairs(data["equivalent"])
        assert ("I2", "I1") not in impl, ">= 1kg should NOT imply > 1000g"
        assert frozenset(["I1", "I2"]) not in equiv

    def test_strict_greater_contradicts_leq_at_boundary(self):
        data = load_results()
        contra = to_frozenset_pairs(data["contradicts"])
        assert frozenset(["I1", "I3"]) in contra, (
            "> 1000g vs <= 1kg should contradict (disjoint at boundary)"
        )

    def test_nonstrict_geq_not_contradicts_leq_at_boundary(self):
        data = load_results()
        contra = to_frozenset_pairs(data["contradicts"])
        assert frozenset(["I2", "I3"]) not in contra, (
            ">= 1kg and <= 1kg should NOT contradict (they share the value 1kg)"
        )

    def test_i2_i3_not_in_any_relationship(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        equiv = to_frozenset_pairs(data["equivalent"])
        contra = to_frozenset_pairs(data["contradicts"])
        assert ("I2", "I3") not in impl
        assert ("I3", "I2") not in impl
        assert frozenset(["I2", "I3"]) not in equiv
        assert frozenset(["I2", "I3"]) not in contra


class TestMixedGenericInterchangeable:
    """Verify interaction between generic/specific terms and interchangeable groups."""

    def test_all_generic_implies_all_specific(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("J1", "J2") in impl, (
            "All-generic interchangeable should imply all-specific [Alice, Bob]"
        )

    def test_all_specific_not_implies_all_generic(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("J2", "J1") not in impl

    def test_mixed_generic_specific_implies_specific(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("J4", "J2") in impl, (
            "[generic, Alice] should imply [Alice, Bob] via interchangeability: "
            "generic maps to Bob, Alice maps to Alice in swapped positions"
        )

    def test_mixed_implies_identical_specific(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("J4", "J3") in impl, (
            "[generic, Alice] should imply [Alice, Alice]"
        )

    def test_specific_not_implies_mixed(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        assert ("J2", "J4") not in impl, (
            "[Alice, Bob] should NOT imply [generic, Alice]"
        )

    def test_duplicate_specific_not_related_to_distinct_specific(self):
        data = load_results()
        impl = to_tuple_pairs(data["implies"])
        contra = to_frozenset_pairs(data["contradicts"])
        equiv = to_frozenset_pairs(data["equivalent"])
        assert ("J2", "J3") not in impl
        assert ("J3", "J2") not in impl
        assert frozenset(["J2", "J3"]) not in contra
        assert frozenset(["J2", "J3"]) not in equiv

    def test_no_register_blocks_contradiction(self):
        data = load_results()
        contra = to_frozenset_pairs(data["contradicts"])
        assert frozenset(["J3", "J5"]) not in contra, (
            "[Alice, Alice] true vs [Alice, Bob] false should NOT contradict: "
            "no valid term mapping exists (Alice cannot map to Bob)"
        )

    def test_generic_contradicts_negated_specific(self):
        data = load_results()
        contra = to_frozenset_pairs(data["contradicts"])
        assert frozenset(["J1", "J5"]) in contra, (
            "All-generic true should contradict [Alice, Bob] false"
        )

    def test_mixed_contradicts_negated_specific(self):
        data = load_results()
        contra = to_frozenset_pairs(data["contradicts"])
        assert frozenset(["J4", "J5"]) in contra, (
            "[generic, Alice] true should contradict [Alice, Bob] false"
        )


class TestNoOverlap:
    """Verify that no pair appears in multiple categories."""

    def test_no_overlap_equivalent_implies(self):
        data = load_results()
        equiv = to_frozenset_pairs(data["equivalent"])
        impl_as_frozensets = {frozenset(p) for p in data["implies"]}
        overlap = equiv & impl_as_frozensets
        assert len(overlap) == 0, f"Pairs in both equivalent and implies: {overlap}"

    def test_no_overlap_equivalent_contradicts(self):
        data = load_results()
        equiv = to_frozenset_pairs(data["equivalent"])
        contra = to_frozenset_pairs(data["contradicts"])
        overlap = equiv & contra
        assert len(overlap) == 0, f"Pairs in both equivalent and contradicts: {overlap}"

    def test_no_overlap_implies_contradicts(self):
        data = load_results()
        impl_as_frozensets = {frozenset(p) for p in data["implies"]}
        contra = to_frozenset_pairs(data["contradicts"])
        overlap = impl_as_frozensets & contra
        assert len(overlap) == 0, f"Pairs in both implies and contradicts: {overlap}"


# ── SQLite output tests ──────────────────────────────────────────

class TestSQLiteOutputExists:
    """Verify that the SQLite results database is produced."""

    def test_db_file_exists(self):
        assert os.path.exists("/app/results.db"), "results.db not found at /app/results.db"

    def test_db_has_relationships_table(self):
        conn = sqlite3.connect("/app/results.db")
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='relationships'"
        )
        tables = [row[0] for row in cursor]
        conn.close()
        assert "relationships" in tables, "results.db missing 'relationships' table"

    def test_db_schema_columns(self):
        conn = sqlite3.connect("/app/results.db")
        cursor = conn.execute("PRAGMA table_info(relationships)")
        columns = {row[1] for row in cursor}
        conn.close()
        assert "id_a" in columns, "relationships table missing 'id_a' column"
        assert "id_b" in columns, "relationships table missing 'id_b' column"
        assert "relation" in columns, "relationships table missing 'relation' column"


class TestSQLiteEquivalences:
    def test_db_equivalences(self):
        conn = sqlite3.connect("/app/results.db")
        rows = conn.execute(
            "SELECT id_a, id_b FROM relationships WHERE relation='equivalent'"
        ).fetchall()
        conn.close()
        actual = {frozenset([r[0], r[1]]) for r in rows}
        assert actual == EXPECTED_EQUIVALENT, (
            f"SQLite equivalences mismatch.\n"
            f"Missing: {EXPECTED_EQUIVALENT - actual}\n"
            f"Spurious: {actual - EXPECTED_EQUIVALENT}"
        )


class TestSQLiteImplications:
    def test_db_implications(self):
        conn = sqlite3.connect("/app/results.db")
        rows = conn.execute(
            "SELECT id_a, id_b FROM relationships WHERE relation='implies'"
        ).fetchall()
        conn.close()
        actual = {(r[0], r[1]) for r in rows}
        assert actual == EXPECTED_IMPLIES, (
            f"SQLite implications mismatch.\n"
            f"Missing: {EXPECTED_IMPLIES - actual}\n"
            f"Spurious: {actual - EXPECTED_IMPLIES}"
        )


class TestSQLiteContradictions:
    def test_db_contradictions(self):
        conn = sqlite3.connect("/app/results.db")
        rows = conn.execute(
            "SELECT id_a, id_b FROM relationships WHERE relation='contradicts'"
        ).fetchall()
        conn.close()
        actual = {frozenset([r[0], r[1]]) for r in rows}
        assert actual == EXPECTED_CONTRADICTS, (
            f"SQLite contradictions mismatch.\n"
            f"Missing: {EXPECTED_CONTRADICTS - actual}\n"
            f"Spurious: {actual - EXPECTED_CONTRADICTS}"
        )


class TestSQLiteJSONConsistency:
    """Verify that JSON and SQLite outputs contain identical results."""

    def test_equivalent_counts_match(self):
        data = load_results()
        conn = sqlite3.connect("/app/results.db")
        db_count = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE relation='equivalent'"
        ).fetchone()[0]
        conn.close()
        assert len(data["equivalent"]) == db_count, (
            f"JSON has {len(data['equivalent'])} equivalences but SQLite has {db_count}"
        )

    def test_implies_counts_match(self):
        data = load_results()
        conn = sqlite3.connect("/app/results.db")
        db_count = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE relation='implies'"
        ).fetchone()[0]
        conn.close()
        assert len(data["implies"]) == db_count, (
            f"JSON has {len(data['implies'])} implications but SQLite has {db_count}"
        )

    def test_contradicts_counts_match(self):
        data = load_results()
        conn = sqlite3.connect("/app/results.db")
        db_count = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE relation='contradicts'"
        ).fetchone()[0]
        conn.close()
        assert len(data["contradicts"]) == db_count, (
            f"JSON has {len(data['contradicts'])} contradictions but SQLite has {db_count}"
        )
