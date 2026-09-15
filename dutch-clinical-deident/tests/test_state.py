#!/usr/bin/env python3
"""
Test suite for Dutch clinical text de-identification pipeline.
Verifies correct detection and redaction of PHI in Dutch clinical notes.
"""

import json
import os
import subprocess
import sys
import pytest


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Execute the de-identification pipeline before any tests."""
    result = subprocess.run(
        [sys.executable, "/app/deidentify.py"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Pipeline script failed.\nstderr:\n{result.stderr}\nstdout:\n{result.stdout}"
    )


def load_annotations(note_id):
    path = f"/app/output/{note_id}_annotations.json"
    assert os.path.exists(path), f"Annotation file not found: {path}"
    with open(path) as f:
        return json.load(f)


def load_redacted(note_id):
    path = f"/app/output/{note_id}_redacted.txt"
    assert os.path.exists(path), f"Redacted file not found: {path}"
    with open(path) as f:
        return f.read()


ALL_NOTES = ["note_001", "note_002", "note_003", "note_004", "note_005"]


# ---------------------------------------------------------------------------
# Output format validation
# ---------------------------------------------------------------------------


class TestOutputFormat:

    @pytest.mark.parametrize("note_id", ALL_NOTES)
    def test_output_files_exist(self, note_id):
        assert os.path.exists(f"/app/output/{note_id}_annotations.json")
        assert os.path.exists(f"/app/output/{note_id}_redacted.txt")

    @pytest.mark.parametrize("note_id", ALL_NOTES)
    def test_annotation_structure(self, note_id):
        annotations = load_annotations(note_id)
        assert isinstance(annotations, list)
        assert len(annotations) > 0, "No annotations found"
        for ann in annotations:
            assert "text" in ann, "Missing 'text' field"
            assert "tag" in ann, "Missing 'tag' field"
            assert "start" in ann, "Missing 'start' field"
            assert "end" in ann, "Missing 'end' field"
            assert isinstance(ann["start"], int)
            assert isinstance(ann["end"], int)
            assert ann["end"] > ann["start"]

    @pytest.mark.parametrize("note_id", ALL_NOTES)
    def test_annotation_positions_match_text(self, note_id):
        with open(f"/app/clinical_notes/{note_id}.txt") as f:
            original = f.read()
        annotations = load_annotations(note_id)
        for ann in annotations:
            extracted = original[ann["start"] : ann["end"]]
            assert extracted == ann["text"], (
                f"Position mismatch: annotation says '{ann['text']}' "
                f"but text[{ann['start']}:{ann['end']}] = '{extracted}'"
            )

    @pytest.mark.parametrize("note_id", ALL_NOTES)
    def test_valid_tags(self, note_id):
        valid_tags = {
            "naam", "datum", "bsn", "telefoonnummer",
            "email", "url", "locatie", "instelling",
        }
        annotations = load_annotations(note_id)
        for ann in annotations:
            assert ann["tag"] in valid_tags, f"Invalid tag: {ann['tag']}"

    @pytest.mark.parametrize("note_id", ALL_NOTES)
    def test_no_overlapping_annotations(self, note_id):
        annotations = load_annotations(note_id)
        sorted_anns = sorted(annotations, key=lambda a: a["start"])
        for i in range(1, len(sorted_anns)):
            assert sorted_anns[i]["start"] >= sorted_anns[i - 1]["end"], (
                f"Overlapping annotations: {sorted_anns[i-1]} and {sorted_anns[i]}"
            )


# ---------------------------------------------------------------------------
# BSN elfproef validation
# ---------------------------------------------------------------------------


class TestBsnElfproef:

    def test_valid_bsn_123456782(self):
        """BSN 123456782 passes elfproef (sum=154, 154%11=0)."""
        annotations = load_annotations("note_001")
        bsn_anns = [a for a in annotations if a["tag"] == "bsn"]
        assert any(
            a["text"] == "123456782" for a in bsn_anns
        ), "Valid BSN 123456782 not detected"

    def test_valid_bsn_111222333(self):
        """BSN 111222333 passes elfproef (sum=66, 66%11=0)."""
        annotations = load_annotations("note_002")
        bsn_anns = [a for a in annotations if a["tag"] == "bsn"]
        assert any(
            a["text"] == "111222333" for a in bsn_anns
        ), "Valid BSN 111222333 not detected"

    def test_invalid_bsn_246813579_not_annotated(self):
        """246813579 fails elfproef (sum=177, 177%11=1) and MUST NOT be tagged as bsn."""
        annotations = load_annotations("note_002")
        bsn_anns = [a for a in annotations if a["tag"] == "bsn"]
        assert not any(
            "246813579" in a["text"] for a in bsn_anns
        ), "Invalid BSN 246813579 was incorrectly annotated"

    def test_valid_bsn_999999990(self):
        """BSN 999999990 passes elfproef (sum=396, 396%11=0)."""
        annotations = load_annotations("note_003")
        bsn_anns = [a for a in annotations if a["tag"] == "bsn"]
        assert any(
            a["text"] == "999999990" for a in bsn_anns
        ), "Valid BSN 999999990 not detected"

    def test_valid_bsn_287654321(self):
        """BSN 287654321 passes elfproef (sum=220, 220%11=0)."""
        annotations = load_annotations("note_004")
        bsn_anns = [a for a in annotations if a["tag"] == "bsn"]
        assert any(
            a["text"] == "287654321" for a in bsn_anns
        ), "Valid BSN 287654321 not detected"

    def test_valid_bsn_736281940(self):
        """BSN 736281940 passes elfproef (sum=220, 220%11=0)."""
        annotations = load_annotations("note_005")
        bsn_anns = [a for a in annotations if a["tag"] == "bsn"]
        assert any(
            a["text"] == "736281940" for a in bsn_anns
        ), "Valid BSN 736281940 not detected"

    def test_invalid_id_483726159_not_annotated(self):
        """483726159 fails elfproef (sum=201, 201%11=3) and MUST NOT be tagged as bsn."""
        annotations = load_annotations("note_005")
        bsn_anns = [a for a in annotations if a["tag"] == "bsn"]
        assert not any(
            "483726159" in a["text"] for a in bsn_anns
        ), "Invalid ID 483726159 was incorrectly annotated as BSN"


# ---------------------------------------------------------------------------
# Note 001 redaction checks
# ---------------------------------------------------------------------------


class TestNote001Redaction:

    def test_patient_name_redacted(self):
        text = load_redacted("note_001")
        assert "Jan van der Berg" not in text, "Patient name not redacted"

    def test_dates_redacted(self):
        text = load_redacted("note_001")
        assert "15-03-2024" not in text, "Date 15-03-2024 not redacted"
        assert "12/05/1985" not in text, "Date 12/05/1985 not redacted"

    def test_bsn_redacted(self):
        text = load_redacted("note_001")
        assert "123456782" not in text, "BSN not redacted"

    def test_doctor_name_redacted(self):
        text = load_redacted("note_001")
        assert "Jansen" not in text, "Doctor surname 'Jansen' not redacted"

    def test_hospital_redacted(self):
        text = load_redacted("note_001")
        assert "Erasmus MC" not in text, "Hospital not redacted"

    def test_cities_redacted(self):
        text = load_redacted("note_001")
        assert "Rotterdam" not in text, "City Rotterdam not redacted"
        assert "Amsterdam" not in text, "City Amsterdam not redacted"

    def test_phone_redacted(self):
        text = load_redacted("note_001")
        assert "06-12345678" not in text, "Phone number not redacted"

    def test_email_redacted(self):
        text = load_redacted("note_001")
        assert "j.vanderberg@gmail.com" not in text, "Email not redacted"

    def test_eponymous_alzheimer_preserved(self):
        text = load_redacted("note_001")
        assert "Alzheimer" in text, "Eponymous 'Alzheimer' was incorrectly redacted"

    def test_eponymous_parkinson_preserved(self):
        text = load_redacted("note_001")
        assert "Parkinson" in text, "Eponymous 'Parkinson' was incorrectly redacted"


# ---------------------------------------------------------------------------
# Note 002 redaction checks
# ---------------------------------------------------------------------------


class TestNote002Redaction:

    def test_patient_name_redacted(self):
        text = load_redacted("note_002")
        assert "Maria de Groot" not in text, "Patient name not redacted"

    def test_dates_redacted(self):
        text = load_redacted("note_002")
        assert "02-01-2024" not in text, "Date 02-01-2024 not redacted"
        assert "08-01-2024" not in text, "Date 08-01-2024 not redacted"
        assert "28-02-1970" not in text, "Date 28-02-1970 not redacted"

    def test_bsn_redacted(self):
        text = load_redacted("note_002")
        assert "111222333" not in text, "BSN not redacted"

    def test_invalid_bsn_preserved(self):
        text = load_redacted("note_002")
        assert "246813579" in text, "Invalid BSN 246813579 was incorrectly redacted"

    def test_doctor_names_redacted(self):
        text = load_redacted("note_002")
        assert "van Dijk" not in text, "Doctor surname 'van Dijk' not redacted"
        assert "Bakker" not in text, "Doctor surname 'Bakker' not redacted"

    def test_hospital_redacted(self):
        text = load_redacted("note_002")
        assert "Amsterdam UMC" not in text, "Hospital 'Amsterdam UMC' not redacted"

    def test_phone_landline_redacted(self):
        text = load_redacted("note_002")
        assert "020-5551234" not in text, "Landline phone not redacted"

    def test_phone_mobile_redacted(self):
        text = load_redacted("note_002")
        assert "44556677" not in text, "Mobile phone digits not redacted"

    def test_cities_redacted(self):
        text = load_redacted("note_002")
        assert "Utrecht" not in text, "City Utrecht not redacted"
        assert "Amersfoort" not in text, "City Amersfoort not redacted"

    def test_eponymous_brugada_preserved(self):
        text = load_redacted("note_002")
        assert "Brugada" in text, "Eponymous 'Brugada' was incorrectly redacted"

    def test_eponymous_marfan_preserved(self):
        text = load_redacted("note_002")
        assert "Marfan" in text, "Eponymous 'Marfan' was incorrectly redacted"


# ---------------------------------------------------------------------------
# Note 003 redaction checks
# ---------------------------------------------------------------------------


class TestNote003Redaction:

    def test_patient_name_redacted(self):
        text = load_redacted("note_003")
        assert "Pieter de Vries" not in text, "Patient name not redacted"

    def test_dutch_date_redacted(self):
        text = load_redacted("note_003")
        assert "3 maart 2024" not in text, "Dutch-format date not redacted"

    def test_numeric_dates_redacted(self):
        text = load_redacted("note_003")
        assert "01-11-1995" not in text, "Date 01-11-1995 not redacted"
        assert "14-04-2024" not in text, "Date 14-04-2024 not redacted"

    def test_bsn_redacted(self):
        text = load_redacted("note_003")
        assert "999999990" not in text, "BSN not redacted"

    def test_doctor_de_wit_redacted(self):
        text = load_redacted("note_003")
        assert "de Wit" not in text, "Doctor surname 'de Wit' not redacted"

    def test_doctor_smit_redacted(self):
        text = load_redacted("note_003")
        assert "Smit" not in text, "Doctor surname 'Smit' not redacted"

    def test_hospital_redacted(self):
        text = load_redacted("note_003")
        assert "UMCG" not in text, "Hospital UMCG not redacted"

    def test_cities_redacted(self):
        text = load_redacted("note_003")
        assert "Groningen" not in text, "City Groningen not redacted"
        assert "Assen" not in text, "City Assen not redacted"

    def test_phone_redacted(self):
        text = load_redacted("note_003")
        assert "050-3612345" not in text, "Phone not redacted"

    def test_email_redacted(self):
        text = load_redacted("note_003")
        assert "p.devries@hotmail.com" not in text, "Email not redacted"

    def test_eponymous_tourette_preserved(self):
        text = load_redacted("note_003")
        assert "Tourette" in text, "'Tourette' was incorrectly redacted"

    def test_eponymous_huntington_preserved(self):
        text = load_redacted("note_003")
        assert "Huntington" in text, "'Huntington' was incorrectly redacted"

    def test_eponymous_sydenham_preserved(self):
        text = load_redacted("note_003")
        assert "Sydenham" in text, "'Sydenham' was incorrectly redacted"


# ---------------------------------------------------------------------------
# Note 004 redaction checks
# ---------------------------------------------------------------------------


class TestNote004Redaction:

    def test_patient_name_redacted(self):
        text = load_redacted("note_004")
        assert "Willem van den Heuvel" not in text, "Patient name not redacted"

    def test_dutch_date_redacted(self):
        text = load_redacted("note_004")
        assert "22 mei 2024" not in text, "Dutch-format date '22 mei 2024' not redacted"

    def test_numeric_date_redacted(self):
        text = load_redacted("note_004")
        assert "17/06/1982" not in text, "Date 17/06/1982 not redacted"

    def test_bsn_redacted(self):
        text = load_redacted("note_004")
        assert "287654321" not in text, "BSN not redacted"

    def test_doctor_de_lange_redacted(self):
        text = load_redacted("note_004")
        assert "de Lange" not in text, "Doctor surname 'de Lange' not redacted"

    def test_doctor_van_leeuwen_redacted(self):
        text = load_redacted("note_004")
        assert "van Leeuwen" not in text, "Doctor surname 'van Leeuwen' not redacted"

    def test_hospitals_redacted(self):
        text = load_redacted("note_004")
        assert "LUMC" not in text, "Hospital LUMC not redacted"
        assert "Catharina Ziekenhuis" not in text, "Hospital Catharina Ziekenhuis not redacted"

    def test_cities_redacted(self):
        text = load_redacted("note_004")
        assert "Leiden" not in text, "City Leiden not redacted"
        assert "Eindhoven" not in text, "City Eindhoven not redacted"
        assert "Haarlem" not in text, "City Haarlem not redacted"

    def test_phone_landline_redacted(self):
        text = load_redacted("note_004")
        assert "071-5234567" not in text, "Landline phone not redacted"

    def test_phone_intl_redacted(self):
        text = load_redacted("note_004")
        assert "+31 71 5234567" not in text, "International phone not redacted"

    def test_email_redacted(self):
        text = load_redacted("note_004")
        assert "w.vandenheuvel@outlook.com" not in text, "Email not redacted"

    def test_url_redacted(self):
        text = load_redacted("note_004")
        assert "https://gc-west.nl/contact" not in text, "URL not redacted"

    def test_eponymous_ehlers_danlos_preserved(self):
        text = load_redacted("note_004")
        assert "Ehlers-Danlos" in text, "Eponymous 'Ehlers-Danlos' was incorrectly redacted"

    def test_eponymous_sjogren_preserved(self):
        text = load_redacted("note_004")
        assert "Sjogren" in text, "Eponymous 'Sjogren' was incorrectly redacted"

    def test_eponymous_raynaud_preserved(self):
        text = load_redacted("note_004")
        assert "Raynaud" in text, "Eponymous 'Raynaud' was incorrectly redacted"


# ---------------------------------------------------------------------------
# Note 005 redaction checks
# ---------------------------------------------------------------------------


class TestNote005Redaction:

    def test_patient_name_redacted(self):
        text = load_redacted("note_005")
        assert "Anna de Boer" not in text, "Patient name not redacted"

    def test_dates_redacted(self):
        text = load_redacted("note_005")
        assert "10-06-2024" not in text, "Date 10-06-2024 not redacted"
        assert "05-09-1958" not in text, "Date 05-09-1958 not redacted"
        assert "15 januari 2024" not in text, "Dutch-format date not redacted"
        assert "28-05-2024" not in text, "Date 28-05-2024 not redacted"

    def test_bsn_redacted(self):
        text = load_redacted("note_005")
        assert "736281940" not in text, "BSN not redacted"

    def test_invalid_id_preserved(self):
        text = load_redacted("note_005")
        assert "483726159" in text, "Invalid ID 483726159 was incorrectly redacted"

    def test_doctor_names_redacted(self):
        text = load_redacted("note_005")
        assert "Kuipers" not in text, "Doctor surname 'Kuipers' not redacted"
        assert "Dijkstra" not in text, "Doctor surname 'Dijkstra' not redacted"
        assert "Hermans" not in text, "Doctor surname 'Hermans' not redacted"
        assert "Postma" not in text, "Doctor surname 'Postma' not redacted"

    def test_hospitals_redacted(self):
        text = load_redacted("note_005")
        assert "Radboudumc" not in text, "Hospital Radboudumc not redacted"
        assert "Maxima Medisch Centrum" not in text, "Hospital Maxima Medisch Centrum not redacted"

    def test_cities_redacted(self):
        text = load_redacted("note_005")
        assert "Nijmegen" not in text, "City Nijmegen not redacted"
        assert "Eindhoven" not in text, "City Eindhoven not redacted"
        assert "Deventer" not in text, "City Deventer not redacted"

    def test_phone_landline_redacted(self):
        text = load_redacted("note_005")
        assert "024-3611111" not in text, "Landline phone not redacted"

    def test_phone_mobile_redacted(self):
        text = load_redacted("note_005")
        assert "06-98765432" not in text, "Mobile phone not redacted"

    def test_email_redacted(self):
        text = load_redacted("note_005")
        assert "oncologie-mdo@radboudumc.nl" not in text, "Email not redacted"

    def test_eponymous_cushing_preserved(self):
        text = load_redacted("note_005")
        assert "Cushing" in text, "Eponymous 'Cushing' was incorrectly redacted"

    def test_eponymous_addison_preserved(self):
        text = load_redacted("note_005")
        assert "Addison" in text, "Eponymous 'Addison' was incorrectly redacted"


# ---------------------------------------------------------------------------
# Overlap resolution
# ---------------------------------------------------------------------------


class TestOverlapResolution:

    def test_amsterdam_umc_tagged_as_instelling(self):
        """'Amsterdam UMC' should be tagged as instelling, not split into locatie + instelling."""
        annotations = load_annotations("note_002")
        umc_anns = [a for a in annotations if "Amsterdam UMC" in a["text"]]
        assert len(umc_anns) > 0, "'Amsterdam UMC' not found in annotations"
        assert umc_anns[0]["tag"] == "instelling", (
            f"'Amsterdam UMC' should be tagged 'instelling', got '{umc_anns[0]['tag']}'"
        )

    def test_no_standalone_amsterdam_overlapping_umc(self):
        """No separate 'Amsterdam' locatie should overlap with 'Amsterdam UMC'."""
        annotations = load_annotations("note_002")
        umc_anns = [a for a in annotations if "Amsterdam UMC" in a["text"]]
        if not umc_anns:
            pytest.skip("Amsterdam UMC not detected")
        umc = umc_anns[0]
        locatie_amsterdam = [
            a for a in annotations
            if a["tag"] == "locatie" and a["text"] == "Amsterdam"
        ]
        for la in locatie_amsterdam:
            assert la["start"] >= umc["end"] or la["end"] <= umc["start"], (
                "Standalone 'Amsterdam' annotation overlaps with 'Amsterdam UMC'"
            )
