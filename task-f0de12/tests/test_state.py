
import json
import os
import subprocess
import pytest
import xml.etree.ElementTree as ET

ASSESSMENT_PATH = "/app/output/assessment.json"
RECONCILED_PATH = "/app/output/reconciled_profile.xml"
XSD_PATH = "/app/schemas/conformance_profile.xsd"

NS = "urn:hl7-org:v2:conformance"

# Expected conformance verdicts for each message under each profile
EXPECTED = {
    "msg_01_both_valid.hl7": {"system_a": True, "system_b": True, "reconciled": True},
    "msg_02_sft_present.hl7": {"system_a": False, "system_b": True, "reconciled": False},
    "msg_03_no_patient.hl7": {"system_a": False, "system_b": True, "reconciled": False},
    "msg_04_pd1_present.hl7": {"system_a": True, "system_b": False, "reconciled": False},
    "msg_05_no_nk1.hl7": {"system_a": True, "system_b": False, "reconciled": False},
    "msg_06_no_orc.hl7": {"system_a": True, "system_b": False, "reconciled": False},
    "msg_07_long_name.hl7": {"system_a": True, "system_b": False, "reconciled": False},
    "msg_08_pid2_populated.hl7": {"system_a": False, "system_b": True, "reconciled": False},
    "msg_09_multi_obs.hl7": {"system_a": True, "system_b": True, "reconciled": True},
    "msg_10_multi_fail.hl7": {"system_a": False, "system_b": False, "reconciled": False},
    "msg_11_no_dob.hl7": {"system_a": False, "system_b": True, "reconciled": False},
    "msg_12_with_nte.hl7": {"system_a": True, "system_b": False, "reconciled": False},
}


# ---- Output file existence ----

class TestOutputExists:
    def test_assessment_file_exists(self):
        assert os.path.isfile(ASSESSMENT_PATH), "assessment.json not found"

    def test_reconciled_profile_exists(self):
        assert os.path.isfile(RECONCILED_PATH), "reconciled_profile.xml not found"


# ---- XSD and namespace validation ----

class TestXMLCompliance:
    def test_reconciled_validates_against_xsd(self):
        """Reconciled profile must validate against the provided XSD."""
        result = subprocess.run(
            ["xmllint", "--schema", XSD_PATH, "--noout", RECONCILED_PATH],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"XSD validation failed:\n{result.stderr}"
        )

    def test_reconciled_uses_namespace(self):
        """Reconciled profile root must be in the conformance namespace."""
        root = _parse_reconciled()
        assert root.tag == f"{{{NS}}}ConformanceProfile", (
            f"Root element should be {{urn:hl7-org:v2:conformance}}ConformanceProfile, "
            f"got {root.tag}"
        )

    def test_message_element_in_namespace(self):
        """Message element must be in the conformance namespace."""
        root = _parse_reconciled()
        msg = root.find(f"{{{NS}}}Message")
        assert msg is not None, (
            "Message element not found in conformance namespace"
        )

    def test_segments_element_in_namespace(self):
        """Segments element must be in the conformance namespace."""
        root = _parse_reconciled()
        segs = root.find(f"{{{NS}}}Segments")
        assert segs is not None, (
            "Segments element not found in conformance namespace"
        )


# ---- Assessment format ----

class TestAssessmentFormat:
    @pytest.fixture(autouse=True)
    def load_assessment(self):
        with open(ASSESSMENT_PATH) as f:
            self.assessment = json.load(f)

    def test_is_dict(self):
        assert isinstance(self.assessment, dict)

    def test_has_all_messages(self):
        for msg_name in EXPECTED:
            assert msg_name in self.assessment, f"Missing message {msg_name}"

    def test_entry_structure(self):
        for msg_name in EXPECTED:
            entry = self.assessment[msg_name]
            assert isinstance(entry, dict), f"{msg_name}: value is not a dict"
            for key in ["system_a", "system_b", "reconciled"]:
                assert key in entry, f"{msg_name}: missing key '{key}'"
                assert isinstance(entry[key], bool), (
                    f"{msg_name}.{key}: expected bool, got {type(entry[key])}"
                )


# ---- Per-message conformance verdicts ----

@pytest.mark.parametrize("msg_name", list(EXPECTED.keys()))
def test_system_a_verdict(msg_name):
    with open(ASSESSMENT_PATH) as f:
        assessment = json.load(f)
    expected = EXPECTED[msg_name]["system_a"]
    actual = assessment[msg_name]["system_a"]
    assert actual == expected, (
        f"{msg_name}: system_a expected {expected}, got {actual}"
    )


@pytest.mark.parametrize("msg_name", list(EXPECTED.keys()))
def test_system_b_verdict(msg_name):
    with open(ASSESSMENT_PATH) as f:
        assessment = json.load(f)
    expected = EXPECTED[msg_name]["system_b"]
    actual = assessment[msg_name]["system_b"]
    assert actual == expected, (
        f"{msg_name}: system_b expected {expected}, got {actual}"
    )


@pytest.mark.parametrize("msg_name", list(EXPECTED.keys()))
def test_reconciled_verdict(msg_name):
    with open(ASSESSMENT_PATH) as f:
        assessment = json.load(f)
    expected = EXPECTED[msg_name]["reconciled"]
    actual = assessment[msg_name]["reconciled"]
    assert actual == expected, (
        f"{msg_name}: reconciled expected {expected}, got {actual}"
    )


# ---- Helpers for namespace-aware XML parsing ----

def _parse_reconciled():
    tree = ET.parse(RECONCILED_PATH)
    return tree.getroot()


def _find_segment_ref(root, ref_value):
    """Find Segment element with Ref=ref_value in Message structure."""
    for elem in root.iter(f"{{{NS}}}Segment"):
        if elem.get("Ref") == ref_value:
            return elem
    return None


def _find_group(root, name_value):
    """Find Group element with Name=name_value in Message structure."""
    for elem in root.iter(f"{{{NS}}}Group"):
        if elem.get("Name") == name_value:
            return elem
    return None


def _find_segment_def(root, seg_id):
    """Find Segment definition with ID=seg_id in Segments section."""
    for segments_section in root.iter(f"{{{NS}}}Segments"):
        for seg in segments_section.findall(f"{{{NS}}}Segment"):
            if seg.get("ID") == seg_id:
                return seg
    return None


def _find_field_by_name(seg_elem, name_substr):
    """Find Field element whose Name contains the substring."""
    for f in seg_elem.findall(f"{{{NS}}}Field"):
        if name_substr.lower() in f.get("Name", "").lower():
            return f
    return None


# ---- Reconciled profile structural constraints ----

class TestReconciledProfileXML:
    def test_valid_xml(self):
        root = _parse_reconciled()
        assert root is not None
        msg = root.find(f"{{{NS}}}Message")
        assert msg is not None, "Message element not found"

    def test_sft_forbidden(self):
        """SFT is X in profile A, O in B -> reconciled must be X."""
        root = _parse_reconciled()
        sft = _find_segment_ref(root, "SFT")
        assert sft is not None, "SFT not found in reconciled Message structure"
        assert sft.get("Usage") == "X", (
            f"SFT Usage should be X, got {sft.get('Usage')}"
        )

    def test_patient_group_required(self):
        """PATIENT is R in A, O in B -> reconciled must be R."""
        root = _parse_reconciled()
        patient = _find_group(root, "PATIENT")
        assert patient is not None, "PATIENT group not found"
        assert patient.get("Usage") == "R", (
            f"PATIENT Usage should be R, got {patient.get('Usage')}"
        )

    def test_pd1_forbidden(self):
        """PD1 is O in A, X in B -> reconciled must be X."""
        root = _parse_reconciled()
        pd1 = _find_segment_ref(root, "PD1")
        if pd1 is not None:
            assert pd1.get("Usage") == "X", (
                f"PD1 Usage should be X, got {pd1.get('Usage')}"
            )

    def test_nk1_required(self):
        """NK1 is O in A, R in B -> reconciled must be R."""
        root = _parse_reconciled()
        nk1 = _find_segment_ref(root, "NK1")
        assert nk1 is not None, "NK1 not found in reconciled structure"
        assert nk1.get("Usage") == "R", (
            f"NK1 Usage should be R, got {nk1.get('Usage')}"
        )

    def test_orc_required(self):
        """ORC is O in A, R in B -> reconciled must be R."""
        root = _parse_reconciled()
        orc = _find_segment_ref(root, "ORC")
        assert orc is not None, "ORC not found in reconciled structure"
        assert orc.get("Usage") == "R", (
            f"ORC Usage should be R, got {orc.get('Usage')}"
        )

    def test_nte_effectively_forbidden(self):
        """NTE Comment field is R in A and X in B -> irreconcilable.
        NTE segment must be X or absent in reconciled profile."""
        root = _parse_reconciled()
        nte = _find_segment_ref(root, "NTE")
        if nte is not None:
            assert nte.get("Usage") == "X", (
                f"NTE Usage should be X (irreconcilable Comment field), "
                f"got {nte.get('Usage')}"
            )


class TestReconciledFieldConstraints:
    def test_pid5_max_length(self):
        """PID-5 MaxLength is 250 in A, 100 in B -> reconciled must be 100."""
        root = _parse_reconciled()
        pid = _find_segment_def(root, "PID")
        assert pid is not None, "PID segment definition not found"
        name_field = _find_field_by_name(pid, "Patient Name")
        assert name_field is not None, "Patient Name field not found in PID"
        max_len = int(name_field.get("MaxLength"))
        assert max_len == 100, (
            f"PID Patient Name MaxLength should be 100, got {max_len}"
        )

    def test_pid7_dob_required(self):
        """PID-7 DOB is R in A, O in B -> reconciled must be R."""
        root = _parse_reconciled()
        pid = _find_segment_def(root, "PID")
        assert pid is not None, "PID segment definition not found"
        dob_field = _find_field_by_name(pid, "Date/Time of Birth")
        if dob_field is None:
            dob_field = _find_field_by_name(pid, "Birth")
        assert dob_field is not None, "DOB field not found in PID"
        assert dob_field.get("Usage") == "R", (
            f"PID DOB Usage should be R, got {dob_field.get('Usage')}"
        )

    def test_pid8_max_length(self):
        """PID-8 AdminSex MaxLength is 1 in A, 3 in B -> reconciled must be 1."""
        root = _parse_reconciled()
        pid = _find_segment_def(root, "PID")
        assert pid is not None
        sex_field = _find_field_by_name(pid, "Administrative Sex")
        if sex_field is None:
            sex_field = _find_field_by_name(pid, "Sex")
        assert sex_field is not None, "Administrative Sex field not found in PID"
        max_len = int(sex_field.get("MaxLength"))
        assert max_len == 1, (
            f"PID AdminSex MaxLength should be 1, got {max_len}"
        )

    def test_pid2_withdrawn(self):
        """PID-2 is W in A, O in B -> reconciled must be W."""
        root = _parse_reconciled()
        pid = _find_segment_def(root, "PID")
        assert pid is not None
        pid2_field = _find_field_by_name(pid, "Patient ID")
        assert pid2_field is not None, "Patient ID field not found in PID"
        assert pid2_field.get("Usage") == "W", (
            f"PID-2 Usage should be W, got {pid2_field.get('Usage')}"
        )

    def test_obx11_max_length(self):
        """OBX-11 ResultStatus MaxLength is 1 in A, 3 in B -> reconciled must be 1."""
        root = _parse_reconciled()
        obx = _find_segment_def(root, "OBX")
        assert obx is not None, "OBX segment definition not found"
        status_field = _find_field_by_name(obx, "Result Status")
        assert status_field is not None, "Result Status field not found in OBX"
        max_len = int(status_field.get("MaxLength"))
        assert max_len == 1, (
            f"OBX ResultStatus MaxLength should be 1, got {max_len}"
        )


# ---- Consistency checks ----

class TestReconciliationConsistency:
    def test_reconciled_never_more_permissive(self):
        """A message valid under reconciled must be valid under both inputs."""
        with open(ASSESSMENT_PATH) as f:
            assessment = json.load(f)
        for msg_name, verdicts in assessment.items():
            if verdicts.get("reconciled"):
                assert verdicts.get("system_a"), (
                    f"{msg_name}: reconciled=true but system_a=false"
                )
                assert verdicts.get("system_b"), (
                    f"{msg_name}: reconciled=true but system_b=false"
                )

    def test_both_valid_implies_reconciled(self):
        """If a message is valid under both A and B, it should be valid under reconciled."""
        with open(ASSESSMENT_PATH) as f:
            assessment = json.load(f)
        for msg_name, verdicts in assessment.items():
            if verdicts.get("system_a") and verdicts.get("system_b"):
                assert verdicts.get("reconciled"), (
                    f"{msg_name}: valid under both A and B but not under reconciled"
                )
