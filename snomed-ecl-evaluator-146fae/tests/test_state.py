
"""Tests for the SNOMED CT ECL evaluator with SQLite backend and FHIR export."""

import hashlib
import json
import os
import subprocess
import pytest


def run_ecl(expression: str, json_mode: bool = False) -> str:
    """Run the ECL evaluator and return raw stdout."""
    cmd = ["/app/ecl-eval"]
    if json_mode:
        cmd.append("--json")
    cmd.append(expression)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"ecl-eval failed for expression: {expression!r}\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return result.stdout


def parse_ids(stdout: str) -> list[int]:
    """Parse sorted concept IDs from plain-text output."""
    lines = [line.strip() for line in stdout.strip().split("\n") if line.strip()]
    return sorted(int(x) for x in lines)


def ecl_ids(expression: str) -> list[int]:
    """Run ECL and return sorted concept IDs."""
    return parse_ids(run_ecl(expression))


def run_sqlite(sql: str) -> str:
    """Run a sqlite3 CLI command against the database."""
    result = subprocess.run(
        ["sqlite3", "/app/snomed.db", sql],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, f"sqlite3 failed: {result.stderr}"
    return result.stdout.strip()


# ── SQLite Database Structure ──────────────────────────────────────────────

class TestSQLiteDatabase:
    def test_database_exists(self):
        """snomed.db must exist as a valid SQLite database."""
        assert os.path.exists("/app/snomed.db")
        count = run_sqlite("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
        assert int(count) >= 5

    def test_concepts_verhoeff_column(self):
        """concepts table must have verhoeff_valid column."""
        info = run_sqlite("PRAGMA table_info(concepts)")
        assert "verhoeff_valid" in info

    def test_valid_concept_count(self):
        """56 active, Verhoeff-valid concepts in the database."""
        count = run_sqlite(
            "SELECT COUNT(*) FROM concepts WHERE active = 1 AND verhoeff_valid = 1"
        )
        assert count == "56"

    def test_invalid_sctids_marked(self):
        """Invalid SCTIDs must have verhoeff_valid = 0."""
        val = run_sqlite("SELECT verhoeff_valid FROM concepts WHERE id = '88810001'")
        assert val == "0"
        val = run_sqlite("SELECT verhoeff_valid FROM concepts WHERE id = '88820008'")
        assert val == "0"
        val = run_sqlite("SELECT verhoeff_valid FROM concepts WHERE id = '88830009'")
        assert val == "0"

    def test_transitive_closure_table(self):
        """transitive_closure table must exist with IS-A closure data."""
        count = run_sqlite(
            "SELECT COUNT(*) FROM transitive_closure WHERE ancestor = '73211009'"
        )
        assert count == "2"  # 44054006, 46635009

    def test_transitive_closure_deep(self):
        """Transitive closure must include multi-hop descendants."""
        count = run_sqlite(
            "SELECT COUNT(*) FROM transitive_closure WHERE ancestor = '64572001'"
        )
        assert count == "12"

    def test_transitive_closure_ancestors(self):
        """Ancestor lookup via transitive_closure must match hierarchy."""
        count = run_sqlite(
            "SELECT COUNT(*) FROM transitive_closure WHERE descendant = '46635009'"
        )
        assert count == "4"  # 73211009, 64572001, 404684003, 138875005

    def test_indices_exist(self):
        """Database must have indices for query performance."""
        count = run_sqlite(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
        )
        assert int(count) >= 5

    def test_relationships_imported(self):
        """Relationships table must have imported data."""
        count = run_sqlite(
            "SELECT COUNT(*) FROM relationships WHERE active = 1 AND typeId = '116680003'"
        )
        assert int(count) >= 50

    def test_descriptions_imported(self):
        """Descriptions table must have preferred synonyms."""
        term = run_sqlite(
            "SELECT term FROM descriptions WHERE conceptId = '73211009' "
            "AND typeId = '900000000000013009' AND active = 1 LIMIT 1"
        )
        assert term == "Diabetes mellitus"

    def test_refset_imported(self):
        """Reference set members must be imported."""
        count = run_sqlite(
            "SELECT COUNT(*) FROM refset_members WHERE refsetId = '99900009' AND active = 1"
        )
        assert int(count) == 7  # includes invalid SCTID 88810001


# ── FHIR ValueSet Export ───────────────────────────────────────────────────

class TestFHIRValueSet:
    def test_valueset_structure(self):
        """ecl-to-valueset must produce valid FHIR R4 ValueSet JSON."""
        result = subprocess.run(
            ["/app/ecl-to-valueset", "<< 73211009"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["resourceType"] == "ValueSet"
        assert data["status"] == "active"
        assert "expansion" in data
        assert data["expansion"]["total"] == 3
        assert data["expansion"]["timestamp"] == "2024-01-01T00:00:00Z"

    def test_valueset_contains_system(self):
        """All contains entries must have system http://snomed.info/sct."""
        result = subprocess.run(
            ["/app/ecl-to-valueset", "<< 73211009"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        for entry in data["expansion"]["contains"]:
            assert entry["system"] == "http://snomed.info/sct"
            assert "code" in entry
            assert "display" in entry

    def test_valueset_sorted(self):
        """Contains array must be sorted by code numerically."""
        result = subprocess.run(
            ["/app/ecl-to-valueset", "<< 73211009"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        codes = [int(e["code"]) for e in data["expansion"]["contains"]]
        assert codes == sorted(codes)

    def test_valueset_identifier_sha256(self):
        """Identifier must be urn:sha256: followed by SHA-256 hex digest of expression."""
        expr = "<< 73211009"
        result = subprocess.run(
            ["/app/ecl-to-valueset", expr],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        ident = data["expansion"]["identifier"]
        assert ident.startswith("urn:sha256:")
        expected_hash = hashlib.sha256(expr.encode()).hexdigest()
        assert ident == f"urn:sha256:{expected_hash}"

    def test_valueset_content(self):
        """Contains entries must have correct SNOMED content."""
        result = subprocess.run(
            ["/app/ecl-to-valueset", "<< 73211009"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        entries = {e["code"]: e["display"] for e in data["expansion"]["contains"]}
        assert entries["73211009"] == "Diabetes mellitus"
        assert entries["44054006"] == "Type 2 diabetes mellitus"
        assert entries["46635009"] == "Type 1 diabetes mellitus"

    def test_valueset_excludes_invalid(self):
        """FHIR output must exclude invalid Verhoeff SCTIDs."""
        result = subprocess.run(
            ["/app/ecl-to-valueset", "*"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        assert data["expansion"]["total"] == 56
        codes = {e["code"] for e in data["expansion"]["contains"]}
        assert "88810001" not in codes
        assert "88820008" not in codes


# ── Verhoeff SCTID Validation ───────────────────────────────────────────────

class TestVerhoeffFiltering:
    def test_wildcard_excludes_invalid_sctids(self):
        """* returns only concepts with valid Verhoeff check digits."""
        result = ecl_ids("*")
        assert len(result) == 56
        assert 88810001 not in result
        assert 88820008 not in result
        assert 88830009 not in result
        assert 138875005 in result

    def test_invalid_sctid_excluded_from_hierarchy(self):
        """Corrupted concept (88810001 IS-A 73211009) must not appear in descendants."""
        result = ecl_ids("< 73211009")
        assert result == [44054006, 46635009]
        assert 88810001 not in result

    def test_invalid_sctid_excluded_from_memberof(self):
        """Corrupted concept in refset must be filtered from memberOf results."""
        result = ecl_ids("^ 99900009")
        assert result == [22298006, 29857009, 49436004, 56265001, 80891009, 232717009]
        assert 88810001 not in result

    def test_inactive_concept_excluded(self):
        """Inactive concept 99910000 must not appear in results."""
        result = ecl_ids("*")
        assert 99910000 not in result


# ── Self / Concept Reference ────────────────────────────────────────────────

class TestSelfConcept:
    def test_single_concept_reference(self):
        assert ecl_ids("22298006") == [22298006]


# ── Constraint Operators ────────────────────────────────────────────────────

class TestConstraintOperators:
    def test_descendant_of(self):
        result = ecl_ids("< 73211009")
        assert result == [44054006, 46635009]

    def test_descendant_or_self_of(self):
        result = ecl_ids("<< 73211009")
        assert result == [44054006, 46635009, 73211009]

    def test_ancestor_of(self):
        result = ecl_ids("> 46635009")
        assert result == [64572001, 73211009, 138875005, 404684003]

    def test_ancestor_or_self_of(self):
        result = ecl_ids(">> 46635009")
        assert result == [46635009, 64572001, 73211009, 138875005, 404684003]

    def test_child_of(self):
        result = ecl_ids("<! 64572001")
        assert result == [50043002, 56265001, 73211009, 235856003]

    def test_parent_of(self):
        result = ecl_ids(">! 22298006")
        assert result == [56265001]

    def test_child_or_self_of(self):
        result = ecl_ids("<<! 64572001")
        assert result == [50043002, 56265001, 64572001, 73211009, 235856003]

    def test_parent_or_self_of(self):
        result = ecl_ids(">>! 22298006")
        assert result == [22298006, 56265001]

    def test_deeper_descendant(self):
        result = ecl_ids("< 64572001")
        expected = [
            22298006, 44054006, 46635009, 49436004, 50043002, 56265001,
            73211009, 128302006, 195967001, 197321007, 233604007, 235856003,
        ]
        assert result == expected


# ── Compound Expressions ────────────────────────────────────────────────────

class TestCompoundExpressions:
    def test_conjunction(self):
        result = ecl_ids("< 404684003 AND < 418799008")
        assert result == [25064002, 29857009, 267036007]

    def test_disjunction(self):
        result = ecl_ids("<< 46635009 OR << 44054006")
        assert result == [44054006, 46635009]

    def test_exclusion(self):
        result = ecl_ids("< 64572001 MINUS << 56265001")
        expected = [
            44054006, 46635009, 50043002, 73211009,
            128302006, 195967001, 197321007, 233604007, 235856003,
        ]
        assert result == expected


# ── Refinement ──────────────────────────────────────────────────────────────

class TestRefinement:
    def test_exact_attribute_value(self):
        result = ecl_ids("< 404684003 : 363698007 = 80891009")
        assert result == [22298006, 29857009, 49436004]

    def test_hierarchy_attribute_value(self):
        result = ecl_ids("<< 64572001 : 363698007 = << 123037004")
        expected = [22298006, 49436004, 128302006, 195967001, 197321007, 233604007]
        assert result == expected

    def test_conjunction_attributes(self):
        result = ecl_ids(
            "< 404684003 : 363698007 = << 39607008 AND 116676008 = << 49755003"
        )
        assert result == [233604007]

    def test_not_equal(self):
        result = ecl_ids("< 418799008 : 363698007 != 80891009")
        assert result == [25064002, 267036007]


# ── Attribute Groups ────────────────────────────────────────────────────────

class TestAttributeGroups:
    def test_grouped_refinement(self):
        result = ecl_ids(
            "< 387713003 : { 363704007 = << 80891009, 260686004 = << 129284003 }"
        )
        assert result == [232717009]

    def test_grouped_no_match(self):
        result = ecl_ids(
            "< 387713003 : { 363704007 = << 10200004, 260686004 = << 80891009 }"
        )
        assert result == []


# ── Dot Notation ────────────────────────────────────────────────────────────

class TestDotNotation:
    def test_dot_attribute_values(self):
        result = ecl_ids("<< 50043002 . 363698007")
        assert result == [39607008]

    def test_dot_multiple_values(self):
        result = ecl_ids("<< 56265001 . 363698007")
        assert result == [80891009]


# ── MemberOf ────────────────────────────────────────────────────────────────

class TestMemberOf:
    def test_memberof_refset(self):
        result = ecl_ids("^ 99900009")
        expected = [22298006, 29857009, 49436004, 56265001, 80891009, 232717009]
        assert result == expected


# ── Nested Expressions ──────────────────────────────────────────────────────

class TestNested:
    def test_nested_expression(self):
        result = ecl_ids("< (< 64572001)")
        expected = [
            22298006, 44054006, 46635009, 49436004,
            128302006, 195967001, 197321007, 233604007,
        ]
        assert result == expected


# ── Reverse Flag ────────────────────────────────────────────────────────────

class TestReverseFlag:
    def test_reverse_traversal(self):
        result = ecl_ids("< 123037004 : R 363698007 = << 64572001")
        assert result == [10200004, 39607008, 80891009]


# ── Concept With Term ───────────────────────────────────────────────────────

class TestConceptWithTerm:
    def test_term_in_pipes_ignored(self):
        bare = ecl_ids("< 404684003")
        with_term = ecl_ids("< 404684003 |Clinical finding|")
        assert bare == with_term
        assert len(bare) > 0


# ── Wildcard ────────────────────────────────────────────────────────────────

class TestWildcard:
    def test_wildcard_returns_all_valid_active(self):
        result = ecl_ids("*")
        assert len(result) == 56
        assert 99910000 not in result
        assert 88810001 not in result
        assert 138875005 in result


# ── Case Insensitive Keywords ───────────────────────────────────────────────

class TestCaseInsensitive:
    def test_lowercase_and(self):
        result = ecl_ids("< 404684003 and < 418799008")
        assert result == [25064002, 29857009, 267036007]

    def test_lowercase_or(self):
        result = ecl_ids("<< 46635009 or << 44054006")
        assert result == [44054006, 46635009]

    def test_lowercase_minus(self):
        result = ecl_ids("< 64572001 minus << 56265001")
        expected = [
            44054006, 46635009, 50043002, 73211009,
            128302006, 195967001, 197321007, 233604007, 235856003,
        ]
        assert result == expected


# ── Whitespace Handling ─────────────────────────────────────────────────────

class TestWhitespace:
    def test_extra_whitespace(self):
        result = ecl_ids("  <   73211009  ")
        assert result == [44054006, 46635009]

    def test_newlines_in_expression(self):
        result = ecl_ids("<\n73211009")
        assert result == [44054006, 46635009]


# ── Cardinality ─────────────────────────────────────────────────────────────

class TestCardinality:
    def test_zero_cardinality_negation(self):
        """[0..0] requires zero matching relationships — acts as negation."""
        result = ecl_ids("< 404684003 : [0..0] 363698007 = 80891009")
        expected = [
            25064002, 44054006, 46635009, 50043002, 56265001, 64572001,
            73211009, 128302006, 195967001, 197321007, 233604007,
            235856003, 267036007, 418799008,
        ]
        assert result == expected

    def test_exact_cardinality(self):
        """[1..1] requires exactly one matching relationship."""
        result = ecl_ids("< 404684003 : [1..1] 363698007 = << 123037004")
        expected = [
            22298006, 25064002, 29857009, 49436004,
            128302006, 195967001, 197321007, 233604007, 267036007,
        ]
        assert result == expected


# ── Invalid Expression Error ────────────────────────────────────────────────

class TestInvalidExpression:
    def test_invalid_syntax_nonzero_exit(self):
        """Syntactically invalid expression must produce non-zero exit code."""
        result = subprocess.run(
            ["/app/ecl-eval", "<<< INVALID !!!"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0

    def test_invalid_expression_stderr(self):
        """Invalid expression should print diagnostic to stderr."""
        result = subprocess.run(
            ["/app/ecl-eval", "AND AND AND"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0
        assert len(result.stderr.strip()) > 0


# ── JSON Output ─────────────────────────────────────────────────────────────

class TestJsonOutput:
    def test_json_structure(self):
        """--json flag produces valid JSON with correct structure."""
        stdout = run_ecl("<< 73211009", json_mode=True)
        data = json.loads(stdout)
        assert "total" in data
        assert "expansion" in data
        assert data["total"] == 3
        assert len(data["expansion"]) == 3

    def test_json_content(self):
        """JSON expansion entries contain correct conceptId and display."""
        stdout = run_ecl("<< 73211009", json_mode=True)
        data = json.loads(stdout)
        entries = {e["conceptId"]: e["display"] for e in data["expansion"]}
        assert entries["44054006"] == "Type 2 diabetes mellitus"
        assert entries["46635009"] == "Type 1 diabetes mellitus"
        assert entries["73211009"] == "Diabetes mellitus"

    def test_json_sorted_by_concept_id(self):
        """JSON expansion entries are sorted by conceptId numerically."""
        stdout = run_ecl("<< 73211009", json_mode=True)
        data = json.loads(stdout)
        ids = [int(e["conceptId"]) for e in data["expansion"]]
        assert ids == sorted(ids)

    def test_json_excludes_invalid_sctids(self):
        """JSON output must also exclude concepts with invalid Verhoeff check digits."""
        stdout = run_ecl("*", json_mode=True)
        data = json.loads(stdout)
        assert data["total"] == 56
        concept_ids = {e["conceptId"] for e in data["expansion"]}
        assert "88810001" not in concept_ids
        assert "88820008" not in concept_ids
