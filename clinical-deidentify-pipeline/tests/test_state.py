
"""
Tests for Dutch clinical text de-identification pipeline.
Verifies correct PHI removal, medical term preservation, BSN validation,
and output format.
"""

import json
import os
import re
import subprocess

import pytest


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Run the de-identification pipeline before tests."""
    assert os.path.exists("/app/run_pipeline.sh"), \
        "Pipeline runner /app/run_pipeline.sh not found"
    result = subprocess.run(
        ["bash", "/app/run_pipeline.sh"],
        capture_output=True, text=True, timeout=180,
        cwd="/app",
    )
    assert result.returncode == 0, \
        f"Pipeline failed (exit {result.returncode}): {result.stderr[:500]}"


def _read_output(docname):
    path = f"/app/output/{docname}.txt"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _read_annotations(docname):
    path = f"/app/output/{docname}.annotations.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ── Output file existence ──────────────────────────────────────────

class TestOutputFiles:
    def test_doc001_text_exists(self):
        assert os.path.isfile("/app/output/doc_001.txt")

    def test_doc002_text_exists(self):
        assert os.path.isfile("/app/output/doc_002.txt")

    def test_doc003_text_exists(self):
        assert os.path.isfile("/app/output/doc_003.txt")

    def test_doc001_annotations_exist(self):
        assert os.path.isfile("/app/output/doc_001.annotations.json")

    def test_doc002_annotations_exist(self):
        assert os.path.isfile("/app/output/doc_002.annotations.json")

    def test_doc003_annotations_exist(self):
        assert os.path.isfile("/app/output/doc_003.annotations.json")


# ── Patient names redacted ─────────────────────────────────────────

class TestPatientNames:
    def test_doc001_full_name_redacted(self):
        out = _read_output("doc_001")
        assert "Jan van der Berg" not in out

    def test_doc001_surname_redacted(self):
        out = _read_output("doc_001")
        # "Van der Berg" standalone references must be gone
        assert "Van der Berg" not in out

    def test_doc001_first_name_redacted(self):
        out = _read_output("doc_001")
        # "Jan" should not appear as a standalone word in the output
        assert not re.search(r'\bJan\b', out)

    def test_doc002_patient_surname_redacted(self):
        out = _read_output("doc_002")
        # "Henoch" used as surname (not in medical term context)
        # Check that "Mevrouw Henoch" is gone
        assert "Mevrouw Henoch" not in out
        assert "Mw. Henoch" not in out

    def test_doc003_hyphenated_surname_redacted(self):
        out = _read_output("doc_003")
        assert "De Wit-Jansen" not in out
        assert "de Wit-Jansen" not in out


# ── Doctor / third-party names redacted ────────────────────────────

class TestDoctorNames:
    def test_doc001_pietersen_redacted(self):
        out = _read_output("doc_001")
        assert "Pietersen" not in out

    def test_doc001_de_vries_redacted(self):
        out = _read_output("doc_001")
        assert "de Vries" not in out

    def test_doc002_bakker_redacted(self):
        out = _read_output("doc_002")
        assert "Bakker" not in out

    def test_doc002_de_groot_redacted(self):
        out = _read_output("doc_002")
        assert "de Groot" not in out

    def test_doc003_mulder_redacted(self):
        out = _read_output("doc_003")
        assert "Mulder" not in out

    def test_doc003_van_dijk_redacted(self):
        out = _read_output("doc_003")
        assert "van Dijk" not in out


# ── BSN validation (elfproef) ──────────────────────────────────────

class TestBsnValidation:
    def test_valid_bsn_tagged_doc001(self):
        anns = _read_annotations("doc_001")
        bsn_anns = [a for a in anns if a["tag"] == "bsn"]
        bsn_texts = [a["text"] for a in bsn_anns]
        assert "123456782" in bsn_texts, \
            f"Valid BSN 123456782 not found in bsn annotations: {bsn_texts}"

    def test_invalid_bsn_not_tagged_doc001(self):
        anns = _read_annotations("doc_001")
        bsn_anns = [a for a in anns if a["tag"] == "bsn"]
        bsn_texts = [a["text"] for a in bsn_anns]
        assert "987654321" not in bsn_texts, \
            "Invalid BSN 987654321 should not be tagged as bsn (fails elfproef)"

    def test_valid_bsn_tagged_doc002(self):
        anns = _read_annotations("doc_002")
        bsn_anns = [a for a in anns if a["tag"] == "bsn"]
        bsn_texts = [a["text"] for a in bsn_anns]
        assert "249326875" in bsn_texts

    def test_valid_bsn_tagged_doc003(self):
        anns = _read_annotations("doc_003")
        bsn_anns = [a for a in anns if a["tag"] == "bsn"]
        bsn_texts = [a["text"] for a in bsn_anns]
        assert "305808692" in bsn_texts

    def test_bsn_absent_from_text_doc001(self):
        out = _read_output("doc_001")
        assert "123456782" not in out


# ── Medical terms preserved ────────────────────────────────────────

class TestMedicalTermsPreserved:
    def test_henoch_schonlein_preserved_doc002(self):
        out = _read_output("doc_002")
        # The medical term must survive de-identification
        assert "Henoch-Sch" in out, \
            "Medical term 'Henoch-Schönlein' should be preserved in doc_002"

    def test_parkinson_preserved_doc003(self):
        out = _read_output("doc_003")
        assert "Parkinson" in out, \
            "Medical term 'Parkinson' should be preserved in doc_003"

    def test_alzheimer_preserved_doc003(self):
        out = _read_output("doc_003")
        assert "Alzheimer" in out, \
            "Medical term 'Alzheimer' should be preserved in doc_003"


# ── Dates redacted ─────────────────────────────────────────────────

class TestDatesRedacted:
    def test_numeric_date_doc001(self):
        out = _read_output("doc_001")
        assert "12-03-2024" not in out

    def test_birth_date_doc001(self):
        out = _read_output("doc_001")
        assert "12-03-1985" not in out

    def test_numeric_date_doc002(self):
        out = _read_output("doc_002")
        assert "25-08-2024" not in out

    def test_text_date_doc002(self):
        out = _read_output("doc_002")
        assert "25 augustus 1972" not in out

    def test_text_date_doc003(self):
        out = _read_output("doc_003")
        assert "3 januari 2024" not in out

    def test_slash_date_doc003(self):
        out = _read_output("doc_003")
        assert "17/05/1968" not in out

    def test_discharge_date_doc003(self):
        out = _read_output("doc_003")
        assert "15-01-2024" not in out


# ── Phone numbers redacted ─────────────────────────────────────────

class TestPhoneNumbers:
    def test_mobile_doc001(self):
        out = _read_output("doc_001")
        assert "06-23456789" not in out

    def test_landline_doc001(self):
        out = _read_output("doc_001")
        assert "050-3612345" not in out

    def test_landline_doc002(self):
        out = _read_output("doc_002")
        assert "010-4567890" not in out

    def test_mobile_no_separator_doc003(self):
        out = _read_output("doc_003")
        assert "0612345678" not in out

    def test_international_phone_doc003(self):
        out = _read_output("doc_003")
        # International format +31 must also be detected
        assert "+31 20 5551234" not in out


# ── Addresses and locations redacted ───────────────────────────────

class TestLocations:
    def test_street_doc001(self):
        out = _read_output("doc_001")
        assert "Oude Ebbingestraat" not in out

    def test_street2_doc001(self):
        out = _read_output("doc_001")
        assert "Hoofdstraat" not in out

    def test_postal_code_doc001(self):
        out = _read_output("doc_001")
        assert "9712 HH" not in out

    def test_street_doc003(self):
        out = _read_output("doc_003")
        assert "Van Baerlestraat" not in out

    def test_street2_doc003(self):
        out = _read_output("doc_003")
        assert "Keizersgracht" not in out

    def test_postal_code_doc003(self):
        out = _read_output("doc_003")
        assert "1071 BB" not in out


# ── Institutions redacted ──────────────────────────────────────────

class TestInstitutions:
    def test_umcg_doc001(self):
        out = _read_output("doc_001")
        assert "UMCG" not in out

    def test_erasmus_doc002(self):
        out = _read_output("doc_002")
        assert "Erasmus MC" not in out

    def test_amsterdam_umc_doc003(self):
        out = _read_output("doc_003")
        assert "Amsterdam UMC" not in out


# ── Email addresses redacted ───────────────────────────────────────

class TestEmails:
    def test_email_doc001(self):
        out = _read_output("doc_001")
        assert "j.vanderberg@gmail.com" not in out

    def test_email_doc003(self):
        out = _read_output("doc_003")
        assert "g.mulder@amsterdamumc.nl" not in out


# ── Redaction format ───────────────────────────────────────────────

class TestRedactionFormat:
    def test_tag_format_present(self):
        out = _read_output("doc_001")
        assert re.search(r'\[[A-Z]+-\d+\]', out), \
            "Expected [TAG-N] redaction markers in output"

    def test_multiple_tags_present(self):
        out = _read_output("doc_001")
        tags = set(re.findall(r'\[([A-Z]+)-\d+\]', out))
        assert len(tags) >= 3, \
            f"Expected at least 3 different tag types, found: {tags}"


# ── Annotation JSON structure ──────────────────────────────────────

class TestAnnotationStructure:
    def test_annotations_is_list(self):
        anns = _read_annotations("doc_001")
        assert isinstance(anns, list)
        assert len(anns) > 0

    def test_annotation_fields(self):
        anns = _read_annotations("doc_001")
        required = {"text", "start_char", "end_char", "tag"}
        for ann in anns:
            assert required.issubset(ann.keys()), \
                f"Annotation missing fields: {required - ann.keys()}"

    def test_annotation_tags_are_strings(self):
        anns = _read_annotations("doc_001")
        for ann in anns:
            assert isinstance(ann["tag"], str)
            assert len(ann["tag"]) > 0

    def test_multiple_tag_types_in_annotations(self):
        anns = _read_annotations("doc_001")
        tags = {a["tag"] for a in anns}
        assert len(tags) >= 3, \
            f"Expected at least 3 different annotation tags, found: {tags}"
