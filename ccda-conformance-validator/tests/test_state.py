"""Tests for C-CDA Multi-Layer Conformance Engine task outputs."""


import json
import os

import pytest


VALID_LANGUAGES = {
    "en", "es", "fr", "de", "zh", "ja", "ko", "ar", "pt", "ru",
    "it", "nl", "hi", "pl", "vi", "tl",
}

VALID_COUNTRIES = {
    "AE", "AR", "AT", "AU", "BE", "BR", "CA", "CH", "CL", "CN",
    "CO", "CZ", "DE", "DK", "EG", "ES", "FI", "FR", "GB", "GH",
    "GR", "HU", "ID", "IE", "IL", "IN", "IT", "JP", "KE", "KR",
    "MX", "NG", "NL", "NO", "NZ", "PE", "PL", "PT", "RO", "RU",
    "SA", "SE", "US", "ZA",
}

VALID_GENDERS = {"F", "M", "UN"}

VALID_RACE_CATEGORY = {"1002-5", "2028-9", "2054-5", "2076-8", "2106-3"}

VALID_RACE_EXTENDED = {
    "1002-5", "1004-1", "1006-6", "2028-9", "2029-7", "2034-7",
    "2036-2", "2039-6", "2040-4", "2041-2", "2054-5", "2056-0",
    "2058-6", "2076-8", "2078-4", "2079-2", "2106-3", "2108-9",
    "2109-7", "2110-5", "2111-3", "2112-1", "2113-9", "2114-7",
    "2115-4", "2131-1",
}

VALID_ETHNICITY = {"2135-2", "2186-5"}

VALID_CONFIDENTIALITY = {"N", "R", "V"}

VALID_ROUTE_CODES = {
    "C38288", "C38276", "C38192", "C38305", "C38290",
    "C38194", "C38289", "C38291", "C38675", "C38299",
}

VALID_SECTION_CODES = {
    "48765-2", "10160-0", "11450-4", "30954-2", "8716-3",
    "47519-4", "46240-8", "29762-2", "10190-7", "18776-5",
    "47420-5", "11369-6", "34133-9",
}

VALID_ROLE_CODES = {
    "AGNT", "ASSIGNED", "CAREGIVER", "CIT", "COMPAR", "CON",
    "ECON", "EMP", "GUARD", "INVSBJ", "LIC", "MIL", "NOK",
    "NOT", "PAT", "PROV", "PRS",
}


# ── report.json structure tests ─────────────────────────────────────


class TestReportStructure:
    def test_report_file_exists(self):
        assert os.path.exists("/app/report.json"), "report.json not found"

    def test_report_is_valid_json(self):
        with open("/app/report.json") as f:
            data = json.load(f)
        assert isinstance(data, dict), "report.json root must be a JSON object"

    def test_report_has_violations_key(self):
        with open("/app/report.json") as f:
            data = json.load(f)
        assert "violations" in data, "report.json must contain 'violations'"
        assert isinstance(data["violations"], list)

    def test_report_has_summary(self):
        with open("/app/report.json") as f:
            data = json.load(f)
        assert "summary" in data, "report.json must contain 'summary'"
        assert isinstance(data["summary"], dict)


# ── report violation detection tests ─────────────────────────────────


class TestReportViolations:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/report.json") as f:
            self.data = json.load(f)
        self.violations = self.data["violations"]

    def test_exactly_sixteen_violations(self):
        assert len(self.violations) == 16, (
            f"Expected exactly 16 violations, got {len(self.violations)}"
        )

    def test_each_violation_has_severity(self):
        for i, v in enumerate(self.violations):
            assert "severity" in v, f"Violation {i} missing 'severity'"
            assert v["severity"] in ("SHALL", "SHOULD"), (
                f"Violation {i} severity must be SHALL or SHOULD"
            )

    def test_each_violation_has_found_value(self):
        for i, v in enumerate(self.violations):
            assert "found_value" in v, f"Violation {i} missing 'found_value'"

    def test_each_violation_has_validator_type(self):
        for i, v in enumerate(self.violations):
            assert "validator_type" in v, f"Violation {i} missing 'validator_type'"

    def test_detects_invalid_confidentiality_code(self):
        all_found = [v["found_value"] for v in self.violations]
        assert "X" in all_found, (
            f"Confidentiality code 'X' not detected. Found: {all_found}"
        )

    def test_detects_invalid_language_subtag_xx(self):
        """The document language subtag 'xx' must be reported."""
        all_found = [v["found_value"] for v in self.violations]
        assert "xx" in all_found, (
            f"Language subtag 'xx' not detected. Found: {all_found}"
        )

    def test_detects_invalid_country_subtag_ZZ(self):
        """The document country subtag 'ZZ' must be reported."""
        all_found = [v["found_value"] for v in self.violations]
        assert "ZZ" in all_found, (
            f"Country subtag 'ZZ' not detected. Found: {all_found}"
        )

    def test_detects_invalid_gender_code(self):
        all_found = [v["found_value"] for v in self.violations]
        assert "Z" in all_found, (
            f"Gender code 'Z' not detected. Found: {all_found}"
        )

    def test_detects_invalid_race_code(self):
        all_found = [v["found_value"] for v in self.violations]
        assert "9999-9" in all_found, (
            f"Race code '9999-9' not detected. Found: {all_found}"
        )

    def test_detects_invalid_sdtc_race_code(self):
        """The sdtc:raceCode '0000-1' must be reported (requires sdtc namespace)."""
        all_found = [v["found_value"] for v in self.violations]
        assert "0000-1" in all_found, (
            f"sdtc:raceCode '0000-1' not detected. Found: {all_found}"
        )

    def test_detects_invalid_ethnicity_code(self):
        all_found = [v["found_value"] for v in self.violations]
        assert "9999-1" in all_found, (
            f"Ethnicity code '9999-1' not detected. Found: {all_found}"
        )

    def test_detects_invalid_birthplace_country_text(self):
        """The birthplace country text content 'XX' must be reported."""
        all_found = [v["found_value"] for v in self.violations]
        assert "XX" in all_found, (
            f"Birthplace country text 'XX' not detected. Found: {all_found}"
        )

    def test_detects_invalid_langcomm_language_subtag(self):
        """The languageCommunication language subtag 'zz' must be reported."""
        all_found = [v["found_value"] for v in self.violations]
        assert "zz" in all_found, (
            f"Language comm subtag 'zz' not detected. Found: {all_found}"
        )

    def test_detects_invalid_langcomm_country_subtag(self):
        """The languageCommunication country subtag 'QQ' must be reported."""
        all_found = [v["found_value"] for v in self.violations]
        assert "QQ" in all_found, (
            f"Language comm country subtag 'QQ' not detected. Found: {all_found}"
        )

    def test_detects_invalid_author_code(self):
        all_found = [v["found_value"] for v in self.violations]
        assert "999X00000Z" in all_found, (
            f"Author code '999X00000Z' not detected. Found: {all_found}"
        )

    def test_detects_invalid_author_code_system(self):
        all_found = [v["found_value"] for v in self.violations]
        author_cs_violations = [
            v for v in self.violations
            if v["found_value"] == "2.16.840.1.113883.6.999"
            and v["validator_type"] == "NodeCodeSystemMatchesConfiguredCodeSystemValidator"
        ]
        assert len(author_cs_violations) >= 1, (
            f"Author codeSystem '2.16.840.1.113883.6.999' not detected"
        )

    def test_detects_invalid_participant_classCode(self):
        """The participant classCode 'XXX' must be reported by ClassCodeValidator."""
        found_classCode = [
            v for v in self.violations
            if v["found_value"] == "XXX"
            and v["validator_type"] == "ClassCodeValidator"
        ]
        assert len(found_classCode) == 1, (
            f"Participant classCode 'XXX' not detected by ClassCodeValidator"
        )

    def test_detects_invalid_section_code(self):
        all_found = [v["found_value"] for v in self.violations]
        assert "99999-9" in all_found, (
            f"Allergies section code '99999-9' not detected. Found: {all_found}"
        )

    def test_detects_invalid_route_code(self):
        all_found = [v["found_value"] for v in self.violations]
        assert "ZZZZZ" in all_found, (
            f"Route code 'ZZZZZ' not detected. Found: {all_found}"
        )

    def test_detects_mfg_wrong_code_system(self):
        """The manufacturedMaterial codeSystem mismatch must be detected."""
        mfg_violations = [
            v for v in self.violations
            if v["found_value"] == "2.16.840.1.113883.6.999"
            and v["validator_type"] == "NodeCodeSystemMatchesConfiguredCodeSystemValidator"
        ]
        assert len(mfg_violations) >= 1, (
            f"ManufacturedMaterial codeSystem violation not detected"
        )

    def test_code_system_violations_total_count(self):
        """Exactly 2 NodeCodeSystemMatchesConfiguredCodeSystemValidator violations."""
        cs_violations = [
            v for v in self.violations
            if v["validator_type"] == "NodeCodeSystemMatchesConfiguredCodeSystemValidator"
        ]
        assert len(cs_violations) == 2, (
            f"Expected 2 NodeCodeSystemMatchesConfiguredCodeSystemValidator violations, "
            f"got {len(cs_violations)}"
        )


# ── conformance scorecard tests ──────────────────────────────────────


class TestConformanceScorecard:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/report.json") as f:
            self.data = json.load(f)
        self.summary = self.data["summary"]
        self.violations = self.data["violations"]

    def test_shall_count(self):
        expected = sum(1 for v in self.violations if v["severity"] == "SHALL")
        assert self.summary["shall_count"] == expected == 12, (
            f"Expected shall_count=12, got {self.summary['shall_count']}"
        )

    def test_should_count(self):
        expected = sum(1 for v in self.violations if v["severity"] == "SHOULD")
        assert self.summary["should_count"] == expected == 4, (
            f"Expected should_count=4, got {self.summary['should_count']}"
        )

    def test_conformance_score(self):
        """Score = max(0.0, 1.0 - (0.05 * 12 + 0.02 * 4)) = 0.32"""
        score = self.summary["conformance_score"]
        assert abs(score - 0.32) < 0.015, (
            f"Expected conformance_score ~0.32, got {score}"
        )


# ── validator type coverage tests ────────────────────────────────────


class TestValidatorTypeCoverage:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/report.json") as f:
            self.violations = json.load(f)["violations"]

    def test_has_language_code_validator(self):
        types = {v["validator_type"] for v in self.violations}
        assert "LanguageCodeNodeLanguageCodeValuesetValidator" in types

    def test_has_country_code_validator(self):
        types = {v["validator_type"] for v in self.violations}
        assert "LanguageCodeNodeCountryCodeValuesetValidator" in types

    def test_has_text_node_validator(self):
        types = {v["validator_type"] for v in self.violations}
        assert "TextNodeValidator" in types

    def test_has_class_code_validator(self):
        types = {v["validator_type"] for v in self.violations}
        assert "ClassCodeValidator" in types

    def test_has_value_set_code_validator(self):
        types = {v["validator_type"] for v in self.violations}
        assert "ValueSetCodeValidator" in types

    def test_has_code_system_validator(self):
        types = {v["validator_type"] for v in self.violations}
        assert "NodeCodeSystemMatchesConfiguredCodeSystemValidator" in types


# ── fixed_document.xml tests ─────────────────────────────────────────


class TestFixedDocumentExists:
    def test_fixed_document_file_exists(self):
        assert os.path.exists("/app/fixed_document.xml"), (
            "fixed_document.xml not found at /app/fixed_document.xml"
        )

    def test_fixed_document_is_valid_xml(self):
        from lxml import etree
        tree = etree.parse("/app/fixed_document.xml")
        assert tree.getroot() is not None


class TestFixedDocumentCorrections:
    NS = {"v3": "urn:hl7-org:v3", "sdtc": "urn:hl7-org:sdtc"}

    @pytest.fixture(autouse=True)
    def load_fixed(self):
        from lxml import etree
        self.tree = etree.parse("/app/fixed_document.xml")

    def test_confidentiality_code_fixed(self):
        nodes = self.tree.xpath(
            "/v3:ClinicalDocument/v3:confidentialityCode", namespaces=self.NS
        )
        assert len(nodes) == 1
        code = nodes[0].get("code")
        assert code in VALID_CONFIDENTIALITY, (
            f"confidentialityCode must be N, R, or V; got '{code}'"
        )

    def test_document_language_code_fixed(self):
        nodes = self.tree.xpath(
            "/v3:ClinicalDocument/v3:languageCode", namespaces=self.NS
        )
        assert len(nodes) == 1
        code = nodes[0].get("code")
        # Language subtag must be valid
        lang = code.split("-")[0] if "-" in code else code
        assert lang in VALID_LANGUAGES, (
            f"languageCode language subtag must be valid; got '{lang}'"
        )
        # If compound, country subtag must be valid
        if "-" in code:
            country = code.split("-", 1)[1]
            assert country in VALID_COUNTRIES, (
                f"languageCode country subtag must be valid; got '{country}'"
            )

    def test_gender_code_fixed(self):
        nodes = self.tree.xpath(
            "//v3:administrativeGenderCode", namespaces=self.NS
        )
        assert len(nodes) >= 1
        code = nodes[0].get("code")
        assert code in VALID_GENDERS, (
            f"administrativeGenderCode must be valid; got '{code}'"
        )

    def test_race_code_fixed(self):
        nodes = self.tree.xpath("//v3:raceCode", namespaces=self.NS)
        assert len(nodes) >= 1
        code = nodes[0].get("code")
        assert code in VALID_RACE_CATEGORY, (
            f"raceCode must be valid; got '{code}'"
        )

    def test_sdtc_race_code_fixed(self):
        nodes = self.tree.xpath("//sdtc:raceCode", namespaces=self.NS)
        assert len(nodes) >= 1
        code = nodes[0].get("code")
        assert code in VALID_RACE_EXTENDED, (
            f"sdtc:raceCode must be valid; got '{code}'"
        )

    def test_ethnicity_code_fixed(self):
        nodes = self.tree.xpath("//v3:ethnicGroupCode", namespaces=self.NS)
        assert len(nodes) >= 1
        code = nodes[0].get("code")
        assert code in VALID_ETHNICITY, (
            f"ethnicGroupCode must be valid; got '{code}'"
        )

    def test_birthplace_country_text_fixed(self):
        nodes = self.tree.xpath(
            "//v3:birthplace/v3:place/v3:addr/v3:country", namespaces=self.NS
        )
        assert len(nodes) >= 1
        text = (nodes[0].text or "").strip()
        assert text in VALID_COUNTRIES, (
            f"birthplace country text must be valid country; got '{text}'"
        )

    def test_language_communication_code_fixed(self):
        nodes = self.tree.xpath(
            "//v3:languageCommunication/v3:languageCode", namespaces=self.NS
        )
        assert len(nodes) >= 1
        code = nodes[0].get("code")
        lang = code.split("-")[0] if "-" in code else code
        assert lang in VALID_LANGUAGES, (
            f"languageCommunication language subtag must be valid; got '{lang}'"
        )
        if "-" in code:
            country = code.split("-", 1)[1]
            assert country in VALID_COUNTRIES, (
                f"languageCommunication country subtag must be valid; got '{country}'"
            )

    def test_author_code_system_fixed(self):
        nodes = self.tree.xpath(
            "//v3:author/v3:assignedAuthor/v3:code", namespaces=self.NS
        )
        assert len(nodes) >= 1
        cs = nodes[0].get("codeSystem")
        assert cs == "2.16.840.1.113883.6.101", (
            f"author codeSystem must be 2.16.840.1.113883.6.101; got '{cs}'"
        )

    def test_participant_classCode_fixed(self):
        nodes = self.tree.xpath(
            "//v3:participant[@typeCode='IND']/v3:associatedEntity",
            namespaces=self.NS,
        )
        assert len(nodes) >= 1
        cc = nodes[0].get("classCode")
        assert cc in VALID_ROLE_CODES, (
            f"participant classCode must be valid HL7RoleCode; got '{cc}'"
        )

    def test_allergies_section_code_fixed(self):
        nodes = self.tree.xpath(
            "//v3:section[v3:templateId[@root='2.16.840.1.113883.10.20.22.2.6.1']]"
            "/v3:code",
            namespaces=self.NS,
        )
        assert len(nodes) >= 1
        code = nodes[0].get("code")
        assert code in VALID_SECTION_CODES, (
            f"allergies section code must be valid; got '{code}'"
        )

    def test_route_code_fixed(self):
        nodes = self.tree.xpath(
            "//v3:substanceAdministration/v3:routeCode", namespaces=self.NS
        )
        assert len(nodes) >= 1
        code = nodes[0].get("code")
        assert code in VALID_ROUTE_CODES, (
            f"routeCode must be valid; got '{code}'"
        )

    def test_medication_code_system_fixed(self):
        nodes = self.tree.xpath(
            "//v3:manufacturedMaterial/v3:code", namespaces=self.NS
        )
        assert len(nodes) >= 1
        cs = nodes[0].get("codeSystem")
        assert cs == "2.16.840.1.113883.6.88", (
            f"manufacturedMaterial codeSystem must be 2.16.840.1.113883.6.88; got '{cs}'"
        )


class TestFixedDocumentIntegrity:
    NS = {"v3": "urn:hl7-org:v3", "sdtc": "urn:hl7-org:sdtc"}

    @pytest.fixture(autouse=True)
    def load_fixed(self):
        from lxml import etree
        self.tree = etree.parse("/app/fixed_document.xml")

    def test_root_element(self):
        root = self.tree.getroot()
        assert root.tag == "{urn:hl7-org:v3}ClinicalDocument"

    def test_has_record_target(self):
        assert self.tree.xpath("//v3:recordTarget", namespaces=self.NS)

    def test_has_author(self):
        assert self.tree.xpath("//v3:author", namespaces=self.NS)

    def test_has_custodian(self):
        assert self.tree.xpath("//v3:custodian", namespaces=self.NS)

    def test_has_structured_body(self):
        assert self.tree.xpath("//v3:structuredBody", namespaces=self.NS)

    def test_has_four_sections(self):
        sections = self.tree.xpath("//v3:section", namespaces=self.NS)
        assert len(sections) >= 4, (
            f"Expected at least 4 sections, got {len(sections)}"
        )

    def test_template_ids_preserved(self):
        tids = self.tree.xpath("//v3:templateId", namespaces=self.NS)
        roots = {t.get("root") for t in tids}
        required = {
            "2.16.840.1.113883.10.20.22.1.1",
            "2.16.840.1.113883.10.20.22.1.2",
            "2.16.840.1.113883.10.20.22.2.6.1",
            "2.16.840.1.113883.10.20.22.2.1.1",
            "2.16.840.1.113883.10.20.22.2.5.1",
            "2.16.840.1.113883.10.20.22.2.3.1",
        }
        for r in required:
            assert r in roots, f"templateId root='{r}' missing"

    def test_has_participant(self):
        assert self.tree.xpath(
            "//v3:participant[@typeCode='IND']", namespaces=self.NS
        )

    def test_has_sdtc_race_code(self):
        assert self.tree.xpath("//sdtc:raceCode", namespaces=self.NS)

    def test_has_birthplace(self):
        assert self.tree.xpath("//v3:birthplace", namespaces=self.NS)

    def test_problems_section_code_unchanged(self):
        """Problems section code should be 11450-4 (was already valid)."""
        nodes = self.tree.xpath(
            "//v3:section[v3:templateId[@root='2.16.840.1.113883.10.20.22.2.5.1']]"
            "/v3:code",
            namespaces=self.NS,
        )
        assert len(nodes) >= 1
        assert nodes[0].get("code") == "11450-4"

    def test_results_section_code_unchanged(self):
        """Results section code should be 30954-2 (was already valid)."""
        nodes = self.tree.xpath(
            "//v3:section[v3:templateId[@root='2.16.840.1.113883.10.20.22.2.3.1']]"
            "/v3:code",
            namespaces=self.NS,
        )
        assert len(nodes) >= 1
        assert nodes[0].get("code") == "30954-2"
