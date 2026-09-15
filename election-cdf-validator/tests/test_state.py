
"""
Tests for the cross-CDF election data validation pipeline.

Verifies three artifact categories:
1. Schematron: /app/cross_cdf_rules.sch is valid, compilable, functionally correct
2. Merged XML: /app/merged.xml is well-formed with CDF sections
3. Report: /app/report.json identifies all planted cross-format violations
4. Pipeline integrity: Schematron finds violations when applied to merged XML
"""

import json
import os
import pytest
from lxml import etree
from lxml.isoschematron import Schematron

REPORT_PATH = "/app/report.json"
SCH_PATH = "/app/cross_cdf_rules.sch"
XML_PATH = "/app/merged.xml"

SCH_NS = "http://purl.oclc.org/dsdl/schematron"
XSL_NS = "http://www.w3.org/1999/XSL/Transform"
SVRL_NS = "http://purl.oclc.org/dsdl/svrl"


@pytest.fixture(scope="module")
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def violations(report):
    return report["violations"]


# ── Report structure ─────────────────────────────────────────────────

class TestReportStructure:
    def test_report_file_exists(self):
        assert os.path.exists(REPORT_PATH), "report.json not found at /app/report.json"

    def test_report_is_valid_json_with_violations(self, report):
        assert isinstance(report, dict), "report must be a JSON object"
        assert "violations" in report, "report must contain 'violations' key"

    def test_violations_is_list(self, violations):
        assert isinstance(violations, list), "violations must be a list"

    def test_each_violation_has_required_fields(self, violations):
        required = {"violation_type", "source_file", "entity_id", "description"}
        for i, v in enumerate(violations):
            assert isinstance(v, dict), f"violation[{i}] must be a dict"
            missing = required - set(v.keys())
            assert not missing, (
                f"violation[{i}] missing required fields: {missing}. "
                f"Got keys: {list(v.keys())}"
            )


# ── Schematron artifact ──────────────────────────────────────────────

class TestSchematronArtifact:
    def test_sch_file_exists(self):
        assert os.path.exists(SCH_PATH), "cross_cdf_rules.sch not found at /app/"

    def test_sch_is_valid_schematron_xml(self):
        """Root element must be sch:schema in the ISO Schematron namespace."""
        tree = etree.parse(SCH_PATH)
        root = tree.getroot()
        assert root.tag == f"{{{SCH_NS}}}schema", (
            f"Root element must be {{sch}}schema, got {root.tag}"
        )

    def test_sch_has_xsl_key_declarations(self):
        """Must declare xsl:key elements for indexing BD entities."""
        tree = etree.parse(SCH_PATH)
        keys = tree.findall(f".//{{{XSL_NS}}}key")
        assert len(keys) >= 3, (
            f"Expected at least 3 xsl:key declarations for BD entity types, "
            f"got {len(keys)}"
        )

    def test_sch_has_rules_and_assertions(self):
        """Must contain sch:rule contexts and sch:assert tests."""
        tree = etree.parse(SCH_PATH)
        rules = tree.findall(f".//{{{SCH_NS}}}rule")
        asserts = tree.findall(f".//{{{SCH_NS}}}assert")
        assert len(rules) >= 3, (
            f"Expected at least 3 sch:rule elements, got {len(rules)}"
        )
        assert len(asserts) >= 3, (
            f"Expected at least 3 sch:assert elements, got {len(asserts)}"
        )

    def test_sch_compiles_with_lxml(self):
        """Schematron must compile to executable XSLT via lxml.isoschematron."""
        sch_doc = etree.parse(SCH_PATH)
        schematron = Schematron(sch_doc, store_report=True)
        assert schematron is not None, "Schematron compilation failed"

    def test_sch_detects_violations_in_merged_xml(self):
        """Compiled Schematron must find referential integrity violations
        when applied to the merged XML document."""
        sch_doc = etree.parse(SCH_PATH)
        schematron = Schematron(sch_doc, store_report=True)
        xml_doc = etree.parse(XML_PATH)
        is_valid = schematron.validate(xml_doc)
        assert not is_valid, (
            "Schematron reported merged.xml as valid — "
            "expected referential integrity violations"
        )
        report = schematron.validation_report
        failed = report.findall(f".//{{{SVRL_NS}}}failed-assert")
        assert len(failed) >= 5, (
            f"Expected at least 5 SVRL failed-assert elements from "
            f"cross-CDF referential integrity checks, got {len(failed)}"
        )

    def test_sch_not_trivially_false(self):
        """Rules must not fire indiscriminately (bounded false positives)."""
        sch_doc = etree.parse(SCH_PATH)
        schematron = Schematron(sch_doc, store_report=True)
        xml_doc = etree.parse(XML_PATH)
        schematron.validate(xml_doc)
        report = schematron.validation_report
        failed = report.findall(f".//{{{SVRL_NS}}}failed-assert")
        assert len(failed) <= 30, (
            f"Too many failed assertions ({len(failed)}); "
            f"rules may be trivially false or overly broad"
        )


# ── Merged XML artifact ──────────────────────────────────────────────

class TestMergedXML:
    def test_xml_file_exists(self):
        assert os.path.exists(XML_PATH), "merged.xml not found at /app/"

    def test_xml_is_well_formed(self):
        """Must parse as well-formed XML."""
        tree = etree.parse(XML_PATH)
        assert tree.getroot() is not None

    def test_xml_contains_cdf_sections(self):
        """Merged XML must contain sections representing BD, CVR, and ERR data."""
        tree = etree.parse(XML_PATH)
        xml_str = etree.tostring(tree.getroot(), encoding="unicode").lower()
        assert "ballot" in xml_str or "definition" in xml_str or "bd" in xml_str, (
            "Merged XML missing ballot definition section"
        )
        assert "cvr" in xml_str or "cast" in xml_str or "vote-record" in xml_str, (
            "Merged XML missing cast vote records section"
        )
        assert "result" in xml_str or "err" in xml_str or "report" in xml_str, (
            "Merged XML missing election results section"
        )


# ── Violation detection ──────────────────────────────────────────────

def _find_violation(violations, *keywords):
    """Return True if any violation mentions ALL keywords (case-insensitive)."""
    for v in violations:
        text = json.dumps(v).lower()
        if all(kw.lower() in text for kw in keywords):
            return True
    return False


class TestViolationDetection:
    """Each test corresponds to one of the 7 planted cross-format violations."""

    def test_v1_undefined_contest_cc_treasurer(self, violations):
        """CVR references ContestId 'cc-treasurer' which is not defined in BD."""
        assert _find_violation(violations, "cc-treasurer"), (
            "Expected violation for undefined contest 'cc-treasurer' in CVR"
        )

    def test_v2_undefined_selection_cs_99(self, violations):
        """CVR references ContestSelectionId 'cs-99' which is not defined in BD."""
        assert _find_violation(violations, "cs-99"), (
            "Expected violation for undefined ContestSelectionId 'cs-99' in CVR"
        )

    def test_v3_undefined_gpunit_precinct_5(self, violations):
        """CVR references BallotStyleUnitId 'gpu-precinct-5' not defined in BD."""
        assert _find_violation(violations, "gpu-precinct-5") or \
               _find_violation(violations, "precinct-5"), (
            "Expected violation for undefined GpUnit 'gpu-precinct-5' in CVR"
        )

    def test_v4_vote_count_mismatch_president(self, violations):
        """ERR reports 16 for cs-pres-dem but CVR tallies 13 (discrepancy +3)."""
        has_ref = _find_violation(violations, "cs-pres-dem") or \
                  _find_violation(violations, "cc-president", "mismatch") or \
                  _find_violation(violations, "cc-president", "discrepan") or \
                  _find_violation(violations, "cc-president", "tally") or \
                  _find_violation(violations, "cand-01", "count") or \
                  _find_violation(violations, "cc-president", "16") or \
                  _find_violation(violations, "cc-president", "13")
        assert has_ref, (
            "Expected vote count mismatch violation for cc-president / cs-pres-dem "
            "(ERR=16 vs CVR=13)"
        )

    def test_v5_undefined_party_green(self, violations):
        """ERR references PartyId 'party-green' which is not defined in BD."""
        assert _find_violation(violations, "party-green") or \
               _find_violation(violations, "green"), (
            "Expected violation for undefined party 'party-green' in ERR"
        )

    def test_v6_undefined_contest_cc_comptroller(self, violations):
        """ERR contains contest 'cc-comptroller' which is not defined in BD."""
        assert _find_violation(violations, "cc-comptroller") or \
               _find_violation(violations, "comptroller"), (
            "Expected violation for undefined contest 'cc-comptroller' in ERR"
        )

    def test_v7_undefined_candidate_cand_phantom(self, violations):
        """ERR references CandidateId 'cand-phantom' not defined in BD."""
        assert _find_violation(violations, "cand-phantom") or \
               _find_violation(violations, "phantom"), (
            "Expected violation for undefined candidate 'cand-phantom' in ERR"
        )


# ── Bounds ───────────────────────────────────────────────────────────

class TestBounds:
    def test_minimum_violations_found(self, violations):
        """Must find at least the 7 planted violations."""
        assert len(violations) >= 7, (
            f"Expected at least 7 violations, found {len(violations)}"
        )

    def test_bounded_violation_count(self, violations):
        """Should not report an excessive number of false positives."""
        assert len(violations) <= 20, (
            f"Expected at most 20 violations (7 planted + Schematron cascades + margin), "
            f"found {len(violations)} — likely false positives"
        )
