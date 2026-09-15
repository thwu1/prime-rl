
import pytest
import json
import os
import subprocess

from lxml import etree


# Full path to the allergy observation value element — used by multiple tests.
# Matches the exact document structure and avoids potential issues with
# descendant-or-self axis (`//`) in some lxml builds.
_ALLERGY_VALUE_XPATH = (
    "/v3:ClinicalDocument/v3:component/v3:structuredBody/v3:component/"
    "v3:section[v3:templateId[@root='2.16.840.1.113883.10.20.22.2.6.1']]/"
    "v3:entry/v3:act/v3:entryRelationship/"
    "v3:observation[v3:templateId[@root='2.16.840.1.113883.10.20.22.4.7']]/"
    "v3:value"
)


# ---------------------------------------------------------------------------
# Validator execution — anti-cheat: re-run the validator to verify it works
# ---------------------------------------------------------------------------

class TestValidatorExecution:
    """Run the validator fresh and verify it produces a correct report.
    This prevents fake report.json files that bypass actual validation."""

    @pytest.fixture(autouse=True)
    def run_validator(self):
        if os.path.exists("/app/report.json"):
            os.remove("/app/report.json")
        result = subprocess.run(
            ["python3", "/app/validator.py"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, (
            f"Validator exited with code {result.returncode}: {result.stderr}"
        )
        assert os.path.isfile("/app/report.json"), (
            "Validator did not produce /app/report.json"
        )
        with open("/app/report.json") as f:
            self.report = json.load(f)

    def test_execution_total_rules(self):
        assert self.report["total_rules"] == 13

    def test_execution_total_violations(self):
        assert self.report["total_violations"] == 6

    def test_execution_shall_count(self):
        assert self.report["shall_violations"] == 4

    def test_execution_should_count(self):
        assert self.report["should_violations"] == 2

    def test_execution_violation_ids(self):
        ids = {v["rule_id"] for v in self.report["violations"]}
        expected = {"R001", "R002", "R005", "R006", "R007", "R012"}
        assert ids == expected, f"Expected violation IDs {expected}, got {ids}"


# ---------------------------------------------------------------------------
# Report structure and counts (read from on-disk report)
# ---------------------------------------------------------------------------

class TestReportCounts:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open("/app/report.json") as f:
            self.report = json.load(f)

    def test_total_rules(self):
        assert self.report["total_rules"] == 13, (
            f"Expected 13 rules evaluated, got {self.report['total_rules']}"
        )

    def test_total_violations(self):
        assert self.report["total_violations"] == 6, (
            f"Expected 6 violations, got {self.report['total_violations']}"
        )

    def test_shall_violations(self):
        assert self.report["shall_violations"] == 4, (
            f"Expected 4 SHALL violations, got {self.report['shall_violations']}"
        )

    def test_should_violations(self):
        assert self.report["should_violations"] == 2, (
            f"Expected 2 SHOULD violations, got {self.report['should_violations']}"
        )

    def test_violations_is_list(self):
        assert isinstance(self.report["violations"], list)

    def test_violations_length(self):
        assert len(self.report["violations"]) == 6


# ---------------------------------------------------------------------------
# Expected violations must be present with correct details
# ---------------------------------------------------------------------------

class TestExpectedViolations:
    @pytest.fixture(autouse=True)
    def load_violations(self):
        with open("/app/report.json") as f:
            data = json.load(f)
        self.violations = {v["rule_id"]: v for v in data["violations"]}

    def test_r001_confidentiality_violation(self):
        assert "R001" in self.violations, "R001 violation not found"
        v = self.violations["R001"]
        assert v["severity"] == "SHALL"
        assert v["actual_code"] == "X"
        assert v["valueset_oid"] == "2.16.840.1.113883.1.11.10228"

    def test_r002_gender_violation(self):
        assert "R002" in self.violations, "R002 violation not found"
        v = self.violations["R002"]
        assert v["severity"] == "SHALL"
        assert v["actual_code"] == "Q"
        assert v["valueset_oid"] == "2.16.840.1.113883.1.11.1"

    def test_r005_marital_status_violation(self):
        assert "R005" in self.violations, "R005 violation not found"
        v = self.violations["R005"]
        assert v["severity"] == "SHOULD"
        assert v["actual_code"] == "Z"
        assert v["valueset_oid"] == "2.16.840.1.113883.1.11.12212"

    def test_r006_language_violation(self):
        assert "R006" in self.violations, "R006 violation not found"
        v = self.violations["R006"]
        assert v["severity"] == "SHOULD"
        assert v["actual_code"] == "xx"
        assert v["valueset_oid"] == "2.16.840.1.113883.1.11.11526"

    def test_r007_route_violation(self):
        assert "R007" in self.violations, "R007 violation not found"
        v = self.violations["R007"]
        assert v["severity"] == "SHALL"
        assert v["actual_code"] == "INVALID_ROUTE"
        assert v["valueset_oid"] == "2.16.840.1.113883.3.88.12.3221.8.7"

    def test_r012_sdtc_race_violation(self):
        """sdtc:raceCode with invalid code must be detected.
        Requires proper sdtc namespace binding and supplementary rule loading."""
        assert "R012" in self.violations, (
            "R012 violation not found - sdtc:raceCode check failed"
        )
        v = self.violations["R012"]
        assert v["severity"] == "SHALL"
        assert v["actual_code"] == "9999-4"
        assert v["valueset_oid"] == "2.16.840.1.113883.1.11.14914"


# ---------------------------------------------------------------------------
# False positives must NOT be present
# ---------------------------------------------------------------------------

class TestNoFalsePositives:
    @pytest.fixture(autouse=True)
    def load_violation_ids(self):
        with open("/app/report.json") as f:
            data = json.load(f)
        self.violation_ids = {v["rule_id"] for v in data["violations"]}

    def test_r003_no_false_positive(self):
        """raceCode 2028-9 is valid via transitive value set includes expansion.
        Race Category Extended -> Race Category Base Groups -> Race Category
        Excluding Nulls (which contains 2028-9). Requires two levels of
        transitive expansion — single-level expansion will NOT find 2028-9."""
        assert "R003" not in self.violation_ids, (
            "R003 is a false positive - value set includes not expanded "
            "transitively (requires two levels of expansion)"
        )

    def test_r004_no_violation(self):
        """ethnicGroupCode 2135-2 is valid in the Ethnicity value set."""
        assert "R004" not in self.violation_ids

    def test_r008_no_false_positive_cwe(self):
        """Allergy observation code 91936005 is NOT in the Allergy/Adverse
        Event Type value set. However, R008 has CWE (Coded With Extensibility)
        binding and the code's codeSystem 2.16.840.1.113883.6.96 (SNOMED CT)
        is listed in the value set's approvedCodeSystems. Under CWE semantics,
        codes from approved code systems are valid extensions even when not
        enumerated in the bound value set."""
        assert "R008" not in self.violation_ids, (
            "R008 is a false positive - CWE binding allows codes from "
            "approved code systems (SNOMED CT) as valid extensions"
        )

    def test_r009_no_violation(self):
        """Problem observation code 55607006 is valid in the Problem Type
        value set (direct membership, CWE binding not relevant here)."""
        assert "R009" not in self.violation_ids

    def test_r010_no_violation(self):
        """Care Plan template not present - rule should not match."""
        assert "R010" not in self.violation_ids

    def test_r011_no_violation(self):
        """Vital sign unit mm[Hg] is valid."""
        assert "R011" not in self.violation_ids

    def test_r013_no_false_positive(self):
        """CodeSystemCodeValidator should check @codeSystem not @code.
        codeSystem 2.16.840.1.113883.6.88 (RxNorm) is a valid code system."""
        assert "R013" not in self.violation_ids, (
            "R013 is a false positive - CodeSystemCodeValidator "
            "should check @codeSystem attribute, not @code"
        )


# ---------------------------------------------------------------------------
# Violation structure validation
# ---------------------------------------------------------------------------

class TestViolationStructure:
    @pytest.fixture(autouse=True)
    def load_violations(self):
        with open("/app/report.json") as f:
            data = json.load(f)
        self.violations = data["violations"]

    def test_all_violations_have_required_fields(self):
        for v in self.violations:
            assert "rule_id" in v, f"Missing rule_id in violation: {v}"
            assert "severity" in v, f"Missing severity in violation: {v}"
            assert "actual_code" in v, f"Missing actual_code in violation: {v}"
            assert "valueset_oid" in v, f"Missing valueset_oid in violation: {v}"

    def test_no_duplicate_rule_ids(self):
        ids = [v["rule_id"] for v in self.violations]
        assert len(ids) == len(set(ids)), (
            f"Duplicate rule IDs in violations: {ids}"
        )

    def test_severity_values_valid(self):
        valid_severities = {"SHALL", "SHOULD", "MAY"}
        for v in self.violations:
            assert v["severity"] in valid_severities, (
                f"Invalid severity '{v['severity']}' for rule {v['rule_id']}"
            )


# ---------------------------------------------------------------------------
# Input integrity — anti-cheat: input files must not be modified
# ---------------------------------------------------------------------------

class TestInputIntegrity:
    NSMAP = {"v3": "urn:hl7-org:v3", "sdtc": "urn:hl7-org:sdtc"}

    def test_patient_record_allergy_code(self):
        """The allergy observation value code 91936005 must remain unchanged.
        This code is from SNOMED CT but NOT in the Allergy/Adverse Event Type
        value set — it specifically tests CWE binding type handling."""
        tree = etree.parse("/app/patient_record.xml")
        elems = tree.xpath(_ALLERGY_VALUE_XPATH, namespaces=self.NSMAP)
        assert len(elems) > 0, "Allergy observation value element not found"
        assert elems[0].get("code") == "91936005", (
            f"patient_record.xml allergy code was modified from '91936005' to "
            f"'{elems[0].get('code')}' - the input document must not be altered"
        )

    def test_patient_record_confidentiality_code(self):
        """confidentialityCode must remain 'X' in the original document."""
        tree = etree.parse("/app/patient_record.xml")
        elems = tree.xpath("//v3:confidentialityCode", namespaces=self.NSMAP)
        assert len(elems) > 0
        assert elems[0].get("code") == "X", (
            "patient_record.xml confidentialityCode must remain 'X'"
        )

    def test_patient_record_sdtc_racecode(self):
        """sdtc:raceCode must remain '9999-4' in the original document."""
        tree = etree.parse("/app/patient_record.xml")
        elems = tree.xpath("//sdtc:raceCode", namespaces=self.NSMAP)
        assert len(elems) > 0
        assert elems[0].get("code") == "9999-4", (
            "patient_record.xml sdtc:raceCode must remain '9999-4'"
        )

    def test_allergy_valueset_not_modified(self):
        """The allergy value set must not be modified to include 91936005.
        The correct fix is CWE binding implementation, not value set mutation."""
        with open("/app/valuesets.json") as f:
            vs = json.load(f)
        allergy_vs = vs.get("2.16.840.1.113883.3.88.12.3221.6.2", {})
        codes = {c["code"] for c in allergy_vs.get("codes", [])}
        assert "91936005" not in codes, (
            "Allergy value set was modified to include 91936005 - this code "
            "should be valid via CWE binding, not by modifying the value set"
        )

    def test_allergy_valueset_code_count(self):
        """The allergy value set should have exactly 5 codes (unchanged)."""
        with open("/app/valuesets.json") as f:
            vs = json.load(f)
        allergy_vs = vs["2.16.840.1.113883.3.88.12.3221.6.2"]
        assert len(allergy_vs["codes"]) == 5, (
            f"Allergy value set has {len(allergy_vs['codes'])} codes, expected 5"
        )

    def test_rules_file_rule_count(self):
        """The validation rules configuration must not be modified."""
        tree = etree.parse("/app/validation_rules.xml")
        root = tree.getroot()
        expr_rules = root.findall(".//expressions/expression")
        supp_rules = root.findall(".//supplementaryExpressions/expression")
        total = len(expr_rules) + len(supp_rules)
        assert total == 13, (
            f"Expected 13 rules in config, found {total} - "
            "validation_rules.xml must not be modified"
        )


# ---------------------------------------------------------------------------
# Remediated document — existence and validity
# ---------------------------------------------------------------------------

class TestRemediatedDocumentExists:
    def test_remediated_file_exists(self):
        assert os.path.isfile("/app/remediated_record.xml"), (
            "remediated_record.xml not found"
        )

    def test_remediated_is_valid_xml(self):
        tree = etree.parse("/app/remediated_record.xml")
        assert tree is not None


# ---------------------------------------------------------------------------
# Remediated document — SHALL violations corrected
# ---------------------------------------------------------------------------

class TestRemediatedShallViolationsFixed:
    """SHALL-severity violations must be corrected with valid vocabulary codes."""

    NSMAP = {"v3": "urn:hl7-org:v3", "sdtc": "urn:hl7-org:sdtc"}

    @pytest.fixture(autouse=True)
    def load_tree(self):
        self.tree = etree.parse("/app/remediated_record.xml")

    def test_confidentiality_code_valid(self):
        """R001 (SHALL): confidentialityCode must be in HL7 BasicConfidentialityKind."""
        elems = self.tree.xpath(
            "//v3:confidentialityCode", namespaces=self.NSMAP
        )
        assert len(elems) > 0, "confidentialityCode element not found"
        code = elems[0].get("code")
        valid_codes = {"L", "M", "N", "R", "U", "V"}
        assert code in valid_codes, (
            f"confidentialityCode '{code}' not in valid set {valid_codes}"
        )

    def test_gender_code_valid(self):
        """R002 (SHALL): administrativeGenderCode must be in AdministrativeGender."""
        elems = self.tree.xpath(
            "//v3:administrativeGenderCode", namespaces=self.NSMAP
        )
        assert len(elems) > 0, "administrativeGenderCode element not found"
        code = elems[0].get("code")
        valid_codes = {"F", "M", "UN"}
        assert code in valid_codes, (
            f"administrativeGenderCode '{code}' not in valid set {valid_codes}"
        )

    def test_route_code_valid(self):
        """R007 (SHALL): routeCode must be in Medication Route FDA."""
        elems = self.tree.xpath("//v3:routeCode", namespaces=self.NSMAP)
        assert len(elems) > 0, "routeCode element not found"
        code = elems[0].get("code")
        valid_codes = {
            "C38205", "C38208", "C38276", "C38284",
            "C38288", "C38299", "C38305",
        }
        assert code in valid_codes, (
            f"routeCode '{code}' not in valid set {valid_codes}"
        )

    def test_sdtc_race_code_valid(self):
        """R012 (SHALL): sdtc:raceCode must be in Race Category Excluding Nulls."""
        elems = self.tree.xpath(
            "//sdtc:raceCode", namespaces=self.NSMAP
        )
        assert len(elems) > 0, "sdtc:raceCode element not found"
        code = elems[0].get("code")
        valid_codes = {"1002-5", "2028-9", "2054-5", "2076-8", "2106-3"}
        assert code in valid_codes, (
            f"sdtc:raceCode '{code}' not in valid set {valid_codes}"
        )


# ---------------------------------------------------------------------------
# Remediated document — SHOULD violations preserved
# ---------------------------------------------------------------------------

class TestRemediatedShouldViolationsPreserved:
    """SHOULD-severity violations must NOT be corrected per HL7 conformance
    binding strength semantics. SHOULD bindings are recommended but not
    required — altering them misrepresents the original clinical data."""

    NSMAP = {"v3": "urn:hl7-org:v3"}

    @pytest.fixture(autouse=True)
    def load_tree(self):
        self.tree = etree.parse("/app/remediated_record.xml")

    def test_marital_status_code_unchanged(self):
        """R005 (SHOULD): maritalStatusCode must remain at original value 'Z'.
        This is a SHOULD-level binding — not corrected during remediation."""
        elems = self.tree.xpath(
            "//v3:maritalStatusCode", namespaces=self.NSMAP
        )
        assert len(elems) > 0, "maritalStatusCode element not found"
        assert elems[0].get("code") == "Z", (
            f"maritalStatusCode was altered from 'Z' to '{elems[0].get('code')}' "
            "- SHOULD violations must not be corrected"
        )

    def test_language_code_unchanged(self):
        """R006 (SHOULD): languageCode must remain at original value 'xx'.
        This is a SHOULD-level binding — not corrected during remediation."""
        elems = self.tree.xpath(
            "//v3:languageCommunication/v3:languageCode",
            namespaces=self.NSMAP,
        )
        assert len(elems) > 0, "languageCommunication/languageCode not found"
        assert elems[0].get("code") == "xx", (
            f"languageCode was altered from 'xx' to '{elems[0].get('code')}' "
            "- SHOULD violations must not be corrected"
        )


# ---------------------------------------------------------------------------
# Remediated document — CWE-conformant codes preserved
# ---------------------------------------------------------------------------

class TestRemediatedCWEPreserved:
    """CWE-bound elements whose codes are from approved code systems are
    conformant extensions. They must NOT be altered during remediation —
    doing so would indicate the solver did not implement CWE binding
    semantics and instead blindly fixed all non-value-set codes."""

    NSMAP = {"v3": "urn:hl7-org:v3"}

    @pytest.fixture(autouse=True)
    def load_tree(self):
        self.tree = etree.parse("/app/remediated_record.xml")

    def test_allergy_code_preserved(self):
        """R008 (CWE): Allergy code 91936005 is from SNOMED CT, an approved
        code system. Under CWE binding, this is a valid extension and must
        remain unchanged in the remediated document."""
        elems = self.tree.xpath(_ALLERGY_VALUE_XPATH, namespaces=self.NSMAP)
        assert len(elems) > 0, "Allergy observation value not found"
        assert elems[0].get("code") == "91936005", (
            f"Allergy code was altered from '91936005' to "
            f"'{elems[0].get('code')}' - CWE extensions from approved "
            "code systems are conformant and must not be modified"
        )

    def test_allergy_codesystem_preserved(self):
        """The allergy code's codeSystem must also remain unchanged."""
        elems = self.tree.xpath(_ALLERGY_VALUE_XPATH, namespaces=self.NSMAP)
        assert len(elems) > 0
        assert elems[0].get("codeSystem") == "2.16.840.1.113883.6.96", (
            "Allergy code's codeSystem was altered - must remain SNOMED CT"
        )


# ---------------------------------------------------------------------------
# Remediated document — structural integrity
# ---------------------------------------------------------------------------

class TestRemediatedDocumentIntegrity:
    """The remediated document must preserve structure and non-violating data."""

    NSMAP = {"v3": "urn:hl7-org:v3", "sdtc": "urn:hl7-org:sdtc"}

    @pytest.fixture(autouse=True)
    def load_trees(self):
        self.original = etree.parse("/app/patient_record.xml")
        self.remediated = etree.parse("/app/remediated_record.xml")

    def test_root_element_preserved(self):
        orig_root = self.original.getroot()
        rem_root = self.remediated.getroot()
        assert orig_root.tag == rem_root.tag

    def test_template_ids_preserved(self):
        orig_tids = self.original.xpath(
            "//v3:templateId/@root", namespaces=self.NSMAP
        )
        rem_tids = self.remediated.xpath(
            "//v3:templateId/@root", namespaces=self.NSMAP
        )
        assert set(orig_tids) == set(rem_tids), (
            "templateId roots differ between original and remediated"
        )

    def test_patient_name_preserved(self):
        orig_family = self.original.xpath(
            "//v3:patient/v3:name/v3:family/text()",
            namespaces=self.NSMAP,
        )
        rem_family = self.remediated.xpath(
            "//v3:patient/v3:name/v3:family/text()",
            namespaces=self.NSMAP,
        )
        assert orig_family == rem_family, "Patient family name was altered"

    def test_race_code_preserved(self):
        """The v3:raceCode (R003) was valid (not a violation) — must not change."""
        elems = self.remediated.xpath(
            "//v3:raceCode", namespaces=self.NSMAP
        )
        assert len(elems) > 0
        assert elems[0].get("code") == "2028-9", (
            "raceCode was altered but it was not a violation"
        )

    def test_section_count_preserved(self):
        orig_sections = len(self.original.xpath(
            "//v3:section", namespaces=self.NSMAP
        ))
        rem_sections = len(self.remediated.xpath(
            "//v3:section", namespaces=self.NSMAP
        ))
        assert orig_sections == rem_sections, (
            f"Section count changed: {orig_sections} -> {rem_sections}"
        )
