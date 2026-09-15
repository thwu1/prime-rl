"""
Tests for WQX 3.0 Schema Intelligence and Conformance Engine.

"""

import json
import os
import pytest


TYPE_SYSTEM_PATH = "/app/type_system.json"
EVOLUTION_PATH = "/app/schema_evolution.json"
REPORTS_DIR = "/app/reports"


def load_type_system():
    with open(TYPE_SYSTEM_PATH, "r") as f:
        return json.load(f)


def load_evolution():
    with open(EVOLUTION_PATH, "r") as f:
        return json.load(f)


def load_report(filename):
    report_path = os.path.join(REPORTS_DIR, f"{filename}.json")
    assert os.path.exists(report_path), f"Report not found: {report_path}"
    with open(report_path, "r") as f:
        return json.load(f)


# ==================================================================
# Phase 1: XSD Type System Resolution
# ==================================================================


class TestTypeSystemStructure:
    def test_file_exists(self):
        assert os.path.exists(TYPE_SYSTEM_PATH), "type_system.json not found"

    def test_has_types_key(self):
        ts = load_type_system()
        assert "types" in ts, "type_system.json missing 'types' key"

    def test_has_element_type_map(self):
        ts = load_type_system()
        assert "element_type_map" in ts, "type_system.json missing 'element_type_map'"

    def test_min_types_count(self):
        ts = load_type_system()
        assert len(ts["types"]) >= 50, f"Expected >=50 types, got {len(ts['types'])}"

    def test_min_element_map_count(self):
        ts = load_type_system()
        assert len(ts["element_type_map"]) >= 50, (
            f"Expected >=50 element mappings, got {len(ts['element_type_map'])}"
        )


class TestTypeSystemConstraints:
    def test_org_id_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["OrganizationIdentifier"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 35

    def test_org_id_min_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["OrganizationIdentifier"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["minLength"] == 1

    def test_activity_id_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["ActivityIdentifier"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 55

    def test_activity_type_code_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["ActivityTypeCode"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 70

    def test_char_name_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["CharacteristicName"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 255

    def test_project_id_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["ProjectIdentifier"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 55

    def test_monitoring_location_name_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["MonitoringLocationName"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 255

    def test_monitoring_location_type_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["MonitoringLocationTypeName"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 45

    def test_media_name_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["ActivityMediaName"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 20

    def test_org_formal_name_max_length(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["OrganizationFormalName"]
        tinfo = ts["types"][etype]
        assert tinfo["restrictions"]["maxLength"] == 255

    def test_base_type_resolved_to_string(self):
        ts = load_type_system()
        etype = ts["element_type_map"]["OrganizationIdentifier"]
        tinfo = ts["types"][etype]
        assert "string" in tinfo["base_type"].lower(), (
            f"Expected base_type containing 'string', got '{tinfo['base_type']}'"
        )


# ==================================================================
# Phase 2: Schema Evolution Analysis
# ==================================================================


class TestEvolutionStructure:
    def test_file_exists(self):
        assert os.path.exists(EVOLUTION_PATH), "schema_evolution.json not found"

    def test_has_required_keys(self):
        evo = load_evolution()
        for key in ("total_version_sections", "field_length_changes",
                     "element_renames", "business_rules"):
            assert key in evo, f"schema_evolution.json missing '{key}'"

    def test_version_sections_count(self):
        evo = load_evolution()
        assert evo["total_version_sections"] >= 30, (
            f"Expected >=30 version sections, got {evo['total_version_sections']}"
        )


class TestEvolutionFieldLengths:
    def test_field_length_changes_count(self):
        evo = load_evolution()
        assert len(evo["field_length_changes"]) >= 40, (
            f"Expected >=40 field length changes, got {len(evo['field_length_changes'])}"
        )

    def test_activity_id_expansion(self):
        evo = load_evolution()
        found = any(
            "ActivityIdentifier" in c.get("field", "")
            and c.get("to_length") == 55
            for c in evo["field_length_changes"]
        )
        assert found, "ActivityIdentifier maxLength expansion to 55 not found"

    def test_org_id_expansion(self):
        evo = load_evolution()
        found = any(
            "OrganizationIdentifier" in c.get("field", "")
            and c.get("to_length") == 35
            for c in evo["field_length_changes"]
        )
        assert found, "OrganizationIdentifier maxLength expansion to 35 not found"

    def test_char_name_expansion(self):
        evo = load_evolution()
        found = any(
            "CharacteristicName" in c.get("field", "")
            and c.get("to_length") == 255
            for c in evo["field_length_changes"]
        )
        assert found, "CharacteristicName maxLength expansion to 255 not found"

    def test_change_record_has_fields(self):
        evo = load_evolution()
        if evo["field_length_changes"]:
            c = evo["field_length_changes"][0]
            assert "field" in c, "field_length_change missing 'field'"
            assert "to_length" in c, "field_length_change missing 'to_length'"
            assert "date" in c, "field_length_change missing 'date'"


class TestEvolutionRenames:
    def test_element_renames_count(self):
        evo = load_evolution()
        assert len(evo["element_renames"]) >= 5, (
            f"Expected >=5 element renames, got {len(evo['element_renames'])}"
        )

    def test_horizontal_method_rename(self):
        evo = load_evolution()
        found = any(
            "HorizontalCollect" in r.get("old_name", "")
            for r in evo["element_renames"]
        )
        assert found, "HorizontalCollectionMethod element rename not found"

    def test_media_rename(self):
        evo = load_evolution()
        found = any(
            "ActivityMedia" in r.get("old_name", "")
            for r in evo["element_renames"]
        )
        assert found, "ActivityMedia element rename not found"


class TestEvolutionBusinessRules:
    def test_business_rules_count(self):
        evo = load_evolution()
        assert len(evo["business_rules"]) >= 3, (
            f"Expected >=3 business rule entries, got {len(evo['business_rules'])}"
        )

    def test_detection_rule_discovered(self):
        evo = load_evolution()
        found = any(
            "detect" in r.get("description", "").lower()
            or "quantit" in r.get("description", "").lower()
            or "quantif" in r.get("description", "").lower()
            for r in evo["business_rules"]
        )
        assert found, "Detection/quantitation business rule not found in evolution"

    def test_depth_rule_discovered(self):
        evo = load_evolution()
        found = any(
            "depth" in r.get("description", "").lower()
            or "vertical" in r.get("description", "").lower()
            for r in evo["business_rules"]
        )
        assert found, "Vertical profile/depth business rule not found in evolution"

    def test_tissue_rule_discovered(self):
        evo = load_evolution()
        found = any(
            "tissue" in r.get("description", "").lower()
            or "anatomyname" in r.get("description", "").lower()
            for r in evo["business_rules"]
        )
        assert found, "Tissue sampling business rule not found in evolution"


# ==================================================================
# Phase 3: Submission Conformance Reports
# ==================================================================


# ---- Submission 01: Valid file ----

class TestSubmission01Valid:
    def test_report_exists(self):
        load_report("submission_01.xml")

    def test_schema_valid(self):
        r = load_report("submission_01.xml")
        assert r["schema_valid"] is True

    def test_valid_flag(self):
        r = load_report("submission_01.xml")
        assert r["valid"] is True

    def test_zero_errors(self):
        r = load_report("submission_01.xml")
        assert r["total_errors"] == 0

    def test_empty_violations(self):
        r = load_report("submission_01.xml")
        assert len(r["violations"]) == 0


# ---- Submission 02: Field-length violations ----

class TestSubmission02FieldLength:
    def test_schema_valid(self):
        r = load_report("submission_02.xml")
        assert r["schema_valid"] is False

    def test_not_valid(self):
        r = load_report("submission_02.xml")
        assert r["valid"] is False

    def test_total_errors(self):
        r = load_report("submission_02.xml")
        assert r["total_errors"] == 3

    def test_field_length_count(self):
        r = load_report("submission_02.xml")
        assert r["category_counts"].get("field_length") == 3

    def test_only_field_length_category(self):
        r = load_report("submission_02.xml")
        categories = set(r["category_counts"].keys())
        assert categories == {"field_length"}


# ---- Submission 03: Domain value violations ----

class TestSubmission03DomainValue:
    def test_schema_valid(self):
        r = load_report("submission_03.xml")
        assert r["schema_valid"] is True

    def test_not_valid(self):
        r = load_report("submission_03.xml")
        assert r["valid"] is False

    def test_total_errors(self):
        r = load_report("submission_03.xml")
        assert r["total_errors"] == 3

    def test_domain_value_count(self):
        r = load_report("submission_03.xml")
        assert r["category_counts"].get("domain_value") == 3

    def test_only_domain_category(self):
        r = load_report("submission_03.xml")
        categories = set(r["category_counts"].keys())
        assert categories == {"domain_value"}


# ---- Submission 04: Business rule violations ----

class TestSubmission04BusinessRule:
    def test_schema_valid(self):
        r = load_report("submission_04.xml")
        assert r["schema_valid"] is True

    def test_not_valid(self):
        r = load_report("submission_04.xml")
        assert r["valid"] is False

    def test_total_errors(self):
        r = load_report("submission_04.xml")
        assert r["total_errors"] == 4

    def test_business_rule_count(self):
        r = load_report("submission_04.xml")
        assert r["category_counts"].get("business_rule") == 4

    def test_only_business_rule_category(self):
        r = load_report("submission_04.xml")
        categories = set(r["category_counts"].keys())
        assert categories == {"business_rule"}


# ---- Submission 05: Referential integrity + business rule ----

class TestSubmission05Mixed:
    def test_schema_valid(self):
        r = load_report("submission_05.xml")
        assert r["schema_valid"] is True

    def test_not_valid(self):
        r = load_report("submission_05.xml")
        assert r["valid"] is False

    def test_total_errors(self):
        r = load_report("submission_05.xml")
        assert r["total_errors"] == 5

    def test_referential_count(self):
        r = load_report("submission_05.xml")
        assert r["category_counts"].get("referential_integrity") == 3

    def test_business_rule_count(self):
        r = load_report("submission_05.xml")
        assert r["category_counts"].get("business_rule") == 2

    def test_exactly_two_categories(self):
        r = load_report("submission_05.xml")
        categories = set(r["category_counts"].keys())
        assert categories == {"referential_integrity", "business_rule"}


# ---- Submission 06: Complex multi-category ----

class TestSubmission06Complex:
    def test_schema_valid(self):
        r = load_report("submission_06.xml")
        assert r["schema_valid"] is False

    def test_not_valid(self):
        r = load_report("submission_06.xml")
        assert r["valid"] is False

    def test_total_errors(self):
        r = load_report("submission_06.xml")
        assert r["total_errors"] == 5

    def test_field_length_count(self):
        r = load_report("submission_06.xml")
        assert r["category_counts"].get("field_length") == 1

    def test_domain_value_count(self):
        r = load_report("submission_06.xml")
        assert r["category_counts"].get("domain_value") == 1

    def test_business_rule_count(self):
        r = load_report("submission_06.xml")
        assert r["category_counts"].get("business_rule") == 2

    def test_referential_count(self):
        r = load_report("submission_06.xml")
        assert r["category_counts"].get("referential_integrity") == 1


# ==================================================================
# Report Structure Validation
# ==================================================================


class TestReportStructure:
    def test_report_has_required_keys(self):
        r = load_report("submission_01.xml")
        for key in ("file", "schema_valid", "valid", "total_errors",
                     "violations", "category_counts"):
            assert key in r, f"Report missing key: {key}"

    def test_violation_entry_structure(self):
        r = load_report("submission_06.xml")
        for v in r["violations"]:
            assert "category" in v, f"Violation missing 'category': {v}"
            assert "element" in v, f"Violation missing 'element': {v}"
            assert "detail" in v, f"Violation missing 'detail': {v}"

    def test_category_counts_match_violations(self):
        r = load_report("submission_06.xml")
        computed = {}
        for v in r["violations"]:
            cat = v["category"]
            computed[cat] = computed.get(cat, 0) + 1
        for cat, cnt in computed.items():
            assert r["category_counts"].get(cat) == cnt, (
                f"category_counts[{cat}] = {r['category_counts'].get(cat)} "
                f"but counted {cnt} violations"
            )

    def test_valid_reflects_schema_and_errors(self):
        r1 = load_report("submission_01.xml")
        assert r1["valid"] == (r1["schema_valid"] is True and r1["total_errors"] == 0)
        r2 = load_report("submission_02.xml")
        assert r2["valid"] is False
        r3 = load_report("submission_03.xml")
        assert r3["valid"] is False

    def test_reports_directory_exists(self):
        assert os.path.isdir(REPORTS_DIR), "/app/reports/ directory not found"

    def test_all_reports_exist(self):
        for i in range(1, 7):
            fname = f"submission_0{i}.xml.json"
            path = os.path.join(REPORTS_DIR, fname)
            assert os.path.exists(path), f"Missing report: {fname}"
