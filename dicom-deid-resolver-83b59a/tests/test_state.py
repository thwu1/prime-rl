
import glob
import json
import os
import subprocess
import tempfile

import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
import pytest


TOOL = "/app/deid_tool.py"


def run_tool(*args):
    """Run the deid_tool.py with given arguments, return parsed JSON."""
    cmd = ["python3", TOOL] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"Tool failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(result.stdout)


# ======================================================================
# Helper: create synthetic DICOM files
# ======================================================================

def create_test_dicom(tags_with_values, filename):
    """Create a minimal DICOM file with specific tags set."""
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(filename, {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    for tag, vr, value in tags_with_values:
        ds.add_new(tag, vr, value)

    ds.save_as(filename)
    return filename


def create_test_dicom_with_sequence(tags_with_values, seq_tag, seq_items, filename):
    """Create a DICOM file with specific tags and a sequence containing items.

    seq_items is a list of lists: each inner list is [(tag, vr, value), ...] for one item.
    """
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(filename, {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    for tag, vr, value in tags_with_values:
        ds.add_new(tag, vr, value)

    items = []
    for item_tags in seq_items:
        item = Dataset()
        for tag, vr, value in item_tags:
            item.add_new(tag, vr, value)
        items.append(item)
    ds.add_new(seq_tag, "SQ", Sequence(items))

    ds.save_as(filename)
    return filename


# ======================================================================
# RESOLVE tests: basic profile actions without options
# ======================================================================

class TestResolveBasicProfile:
    def test_accession_number_z(self):
        """(0008,0050) Accession Number -> Z in basic profile"""
        data = run_tool("resolve", "--tag", "(0008,0050)")
        assert data["resolved_action"] == "Z"
        assert data["source"] == "basic_profile"

    def test_patient_name_z(self):
        """(0010,0010) Patient's Name -> Z in basic profile"""
        data = run_tool("resolve", "--tag", "(0010,0010)")
        assert data["resolved_action"] == "Z"
        assert data["source"] == "basic_profile"

    def test_patient_birth_date_z(self):
        """(0010,0030) Patient's Birth Date -> Z in basic profile"""
        data = run_tool("resolve", "--tag", "(0010,0030)")
        assert data["resolved_action"] == "Z"

    def test_acquisition_comments_x(self):
        """(0018,4000) Acquisition Comments -> X in basic profile"""
        data = run_tool("resolve", "--tag", "(0018,4000)")
        assert data["resolved_action"] == "X"
        assert data["source"] == "basic_profile"

    def test_study_instance_uid_u(self):
        """(0020,000D) Study Instance UID -> U in basic profile"""
        data = run_tool("resolve", "--tag", "(0020,000D)")
        assert data["resolved_action"] == "U"
        assert data["source"] == "basic_profile"

    def test_graphic_annotation_d(self):
        """(0070,0001) Graphic Annotation Sequence -> D in basic profile"""
        data = run_tool("resolve", "--tag", "(0070,0001)")
        assert data["resolved_action"] == "D"
        assert data["source"] == "basic_profile"

    def test_person_name_d(self):
        """(0040,A123) Person Name -> D in basic profile (no option overrides)"""
        data = run_tool("resolve", "--tag", "(0040,A123)")
        assert data["resolved_action"] == "D"
        assert data["source"] == "basic_profile"

    def test_clinical_trial_protocol_id_d(self):
        """(0012,0020) Clinical Trial Protocol ID -> D in basic profile"""
        data = run_tool("resolve", "--tag", "(0012,0020)")
        assert data["resolved_action"] == "D"
        assert data["source"] == "basic_profile"

    def test_unknown_tag_null(self):
        """Unknown tag should return null action"""
        data = run_tool("resolve", "--tag", "(0099,0099)")
        assert data["resolved_action"] is None
        assert data["source"] is None


# ======================================================================
# RESOLVE tests: compound action codes
# ======================================================================

class TestResolveCompoundActions:
    def test_xz_no_iod_type(self):
        """(0008,0022) Acquisition Date -> X/Z without IOD type"""
        data = run_tool("resolve", "--tag", "(0008,0022)")
        assert data["resolved_action"] == "X/Z"

    def test_xz_type3(self):
        """(0008,0022) X/Z with Type 3 -> X"""
        data = run_tool("resolve", "--tag", "(0008,0022)", "--iod-type", "3")
        assert data["resolved_action"] == "X"

    def test_xz_type2(self):
        """(0008,0022) X/Z with Type 2 -> Z"""
        data = run_tool("resolve", "--tag", "(0008,0022)", "--iod-type", "2")
        assert data["resolved_action"] == "Z"

    def test_xzd_type1(self):
        """(0008,002A) Acquisition DateTime -> X/Z/D; Type 1 -> D"""
        data = run_tool("resolve", "--tag", "(0008,002A)", "--iod-type", "1")
        assert data["resolved_action"] == "D"

    def test_xzd_type2(self):
        """(0008,002A) X/Z/D; Type 2 -> Z"""
        data = run_tool("resolve", "--tag", "(0008,002A)", "--iod-type", "2")
        assert data["resolved_action"] == "Z"

    def test_xzd_type3(self):
        """(0008,002A) X/Z/D; Type 3 -> X"""
        data = run_tool("resolve", "--tag", "(0008,002A)", "--iod-type", "3")
        assert data["resolved_action"] == "X"

    def test_zd_type1(self):
        """(0010,0020) Patient ID -> Z/D; Type 1 -> D"""
        data = run_tool("resolve", "--tag", "(0010,0020)", "--iod-type", "1")
        assert data["resolved_action"] == "D"

    def test_zd_type2(self):
        """(0010,0020) Patient ID -> Z/D; Type 2 -> Z"""
        data = run_tool("resolve", "--tag", "(0010,0020)", "--iod-type", "2")
        assert data["resolved_action"] == "Z"

    def test_xd_type1(self):
        """(0018,1400) Acquisition Device Processing Description -> X/D; Type 1 -> D"""
        data = run_tool("resolve", "--tag", "(0018,1400)", "--iod-type", "1")
        assert data["resolved_action"] == "D"

    def test_xd_type3(self):
        """(0018,1400) X/D; Type 3 -> X"""
        data = run_tool("resolve", "--tag", "(0018,1400)", "--iod-type", "3")
        assert data["resolved_action"] == "X"

    def test_xzu_star_type1(self):
        """(0008,1140) Referenced Image Sequence -> X/Z/U*; Type 1 -> U"""
        data = run_tool("resolve", "--tag", "(0008,1140)", "--iod-type", "1")
        assert data["resolved_action"] == "U"

    def test_xzu_star_type2(self):
        """(0008,1140) X/Z/U*; Type 2 -> Z"""
        data = run_tool("resolve", "--tag", "(0008,1140)", "--iod-type", "2")
        assert data["resolved_action"] == "Z"

    def test_xzu_star_type3(self):
        """(0008,1140) X/Z/U*; Type 3 -> X"""
        data = run_tool("resolve", "--tag", "(0008,1140)", "--iod-type", "3")
        assert data["resolved_action"] == "X"

    def test_device_serial_number_xzd(self):
        """(0018,1000) Device Serial Number -> X/Z/D"""
        data = run_tool("resolve", "--tag", "(0018,1000)")
        assert data["resolved_action"] == "X/Z/D"

    def test_station_name_xzd_type2(self):
        """(0008,1010) Station Name -> X/Z/D; Type 2 -> Z"""
        data = run_tool("resolve", "--tag", "(0008,1010)", "--iod-type", "2")
        assert data["resolved_action"] == "Z"


# ======================================================================
# RESOLVE tests: option overrides
# ======================================================================

class TestResolveOptionOverrides:
    def test_clean_descriptors_override(self):
        """(0018,4000) basic=X, clean_descriptors overrides to C"""
        data = run_tool("resolve", "--tag", "(0018,4000)",
                        "--options", "clean_descriptors")
        assert data["resolved_action"] == "C"
        assert data["source"] == "clean_descriptors"

    def test_retain_full_dates_override(self):
        """(0008,0022) basic=X/Z, retain_full_dates overrides to K"""
        data = run_tool("resolve", "--tag", "(0008,0022)",
                        "--options", "retain_full_dates")
        assert data["resolved_action"] == "K"
        assert data["source"] == "retain_full_dates"

    def test_retain_modified_dates_override(self):
        """(0008,0022) basic=X/Z, retain_modified_dates overrides to C"""
        data = run_tool("resolve", "--tag", "(0008,0022)",
                        "--options", "retain_modified_dates")
        assert data["resolved_action"] == "C"
        assert data["source"] == "retain_modified_dates"

    def test_retain_uids_override(self):
        """(0020,000D) Study Instance UID: basic=U, retain_uids overrides to K"""
        data = run_tool("resolve", "--tag", "(0020,000D)",
                        "--options", "retain_uids")
        assert data["resolved_action"] == "K"
        assert data["source"] == "retain_uids"

    def test_retain_device_id_override(self):
        """(0018,1000) Device Serial Number: basic=X/Z/D, retain_device_id -> K"""
        data = run_tool("resolve", "--tag", "(0018,1000)",
                        "--options", "retain_device_id")
        assert data["resolved_action"] == "K"
        assert data["source"] == "retain_device_id"

    def test_retain_patient_chars_override(self):
        """(0010,0040) Patient's Sex: basic=Z, retain_patient_chars -> K"""
        data = run_tool("resolve", "--tag", "(0010,0040)",
                        "--options", "retain_patient_chars")
        assert data["resolved_action"] == "K"
        assert data["source"] == "retain_patient_chars"

    def test_retain_institution_id_override(self):
        """(0008,0080) Institution Name: basic=X/Z/D, retain_institution_id -> K"""
        data = run_tool("resolve", "--tag", "(0008,0080)",
                        "--options", "retain_institution_id")
        assert data["resolved_action"] == "K"
        assert data["source"] == "retain_institution_id"

    def test_clean_graphics_override(self):
        """(0070,0001) Graphic Annotation Sequence: basic=D, clean_graphics -> C"""
        data = run_tool("resolve", "--tag", "(0070,0001)",
                        "--options", "clean_graphics")
        assert data["resolved_action"] == "C"
        assert data["source"] == "clean_graphics"

    def test_clean_structured_content_override(self):
        """(0040,0555) Acquisition Context Sequence: basic=X/Z, clean_structured_content -> C"""
        data = run_tool("resolve", "--tag", "(0040,0555)",
                        "--options", "clean_structured_content")
        assert data["resolved_action"] == "C"
        assert data["source"] == "clean_structured_content"

    def test_option_not_applicable(self):
        """Option that doesn't affect this tag should not override"""
        data = run_tool("resolve", "--tag", "(0008,0050)",
                        "--options", "clean_descriptors,retain_full_dates")
        assert data["resolved_action"] == "Z"
        assert data["source"] == "basic_profile"

    def test_multiple_options_last_wins(self):
        """When two options both override, last listed wins"""
        # (0008,0022) Acquisition Date: retain_full_dates=K, retain_modified_dates=C
        data = run_tool("resolve", "--tag", "(0008,0022)",
                        "--options", "retain_modified_dates,retain_full_dates")
        assert data["resolved_action"] == "K"
        assert data["source"] == "retain_full_dates"

        data2 = run_tool("resolve", "--tag", "(0008,0022)",
                         "--options", "retain_full_dates,retain_modified_dates")
        assert data2["resolved_action"] == "C"
        assert data2["source"] == "retain_modified_dates"

    def test_option_overrides_compound_bypasses_iod_type(self):
        """When an option overrides a compound action, IOD type is irrelevant"""
        data = run_tool("resolve", "--tag", "(0008,002A)",
                        "--options", "retain_full_dates", "--iod-type", "3")
        assert data["resolved_action"] == "K"
        assert data["source"] == "retain_full_dates"

    def test_three_option_tag(self):
        """(0018,1203) Calibration DateTime: basic=Z, has 3 option overrides"""
        data = run_tool("resolve", "--tag", "(0018,1203)",
                        "--options", "retain_device_id")
        assert data["resolved_action"] == "K"
        assert data["source"] == "retain_device_id"

        data2 = run_tool("resolve", "--tag", "(0018,1203)",
                         "--options", "retain_device_id,retain_modified_dates")
        assert data2["resolved_action"] == "C"
        assert data2["source"] == "retain_modified_dates"


# ======================================================================
# BATCH-RESOLVE tests
# ======================================================================

class TestBatchResolve:
    def test_basic_profile_only(self):
        """Batch resolve with no options returns all 656 entries"""
        data = run_tool("batch-resolve", "--options", "")
        assert len(data) == 656

    def test_spot_check_basic(self):
        """Spot-check specific tags in batch output"""
        data = run_tool("batch-resolve", "--options", "")
        tag_map = {e["tag"]: e for e in data}
        assert tag_map["(0008,0050)"]["resolved_action"] == "Z"
        assert tag_map["(0010,0010)"]["resolved_action"] == "Z"
        assert tag_map["(0020,000D)"]["resolved_action"] == "U"
        assert tag_map["(0018,4000)"]["resolved_action"] == "X"

    def test_batch_with_retain_full_dates(self):
        """Batch resolve with retain_full_dates changes date attributes to K"""
        data = run_tool("batch-resolve", "--options", "retain_full_dates")
        tag_map = {e["tag"]: e for e in data}
        assert tag_map["(0008,0022)"]["resolved_action"] == "K"
        assert tag_map["(0008,0022)"]["source"] == "retain_full_dates"
        assert tag_map["(0010,0010)"]["resolved_action"] == "Z"
        assert tag_map["(0010,0010)"]["source"] == "basic_profile"

    def test_batch_with_iod_type(self):
        """Batch resolve with IOD type resolves compound codes"""
        data = run_tool("batch-resolve", "--options", "", "--iod-type", "2")
        tag_map = {e["tag"]: e for e in data}
        assert tag_map["(0008,0022)"]["resolved_action"] == "Z"
        assert tag_map["(0008,002A)"]["resolved_action"] == "Z"
        assert tag_map["(0010,0020)"]["resolved_action"] == "Z"

    def test_batch_with_multiple_options(self):
        """Batch resolve with retain_device_id + clean_descriptors"""
        data = run_tool("batch-resolve",
                        "--options", "retain_device_id,clean_descriptors")
        tag_map = {e["tag"]: e for e in data}
        assert tag_map["(0018,1000)"]["resolved_action"] == "K"
        assert tag_map["(0018,4000)"]["resolved_action"] == "C"
        assert tag_map["(0008,0050)"]["resolved_action"] == "Z"

    def test_batch_all_entries_have_required_fields(self):
        """Every entry in batch output must have tag, attribute_name, resolved_action, source"""
        data = run_tool("batch-resolve", "--options", "")
        for entry in data:
            assert "tag" in entry
            assert "attribute_name" in entry
            assert "resolved_action" in entry
            assert "source" in entry

    def test_batch_d_tags_present(self):
        """Batch resolve includes pure D-action tags correctly"""
        data = run_tool("batch-resolve", "--options", "")
        tag_map = {e["tag"]: e for e in data}
        assert tag_map["(0040,A123)"]["resolved_action"] == "D"
        assert tag_map["(0040,A123)"]["source"] == "basic_profile"
        assert tag_map["(0012,0020)"]["resolved_action"] == "D"

    def test_batch_compound_without_iod_type_stays_compound(self):
        """Compound codes without IOD type should remain compound in batch"""
        data = run_tool("batch-resolve", "--options", "")
        tag_map = {e["tag"]: e for e in data}
        assert tag_map["(0008,0022)"]["resolved_action"] == "X/Z"
        assert tag_map["(0008,002A)"]["resolved_action"] == "X/Z/D"
        assert tag_map["(0008,1140)"]["resolved_action"] == "X/Z/U*"


# ======================================================================
# AUDIT tests with synthetic DICOM files
# ======================================================================

class TestAudit:
    def test_x_violation_detected(self):
        """Audit should detect tags present that should be removed (X action)"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x00380010, "LO", "ADM12345"),
                (0x001021B0, "LT", "Patient history"),
                (0x00080050, "SH", ""),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            violation_tags = [v["tag"] for v in data["violations"]]
            assert "(0038,0010)" in violation_tags
            assert "(0010,21B0)" in violation_tags
            assert len(data["violations"]) >= 2
        finally:
            os.unlink(fname)

    def test_z_violation_detected(self):
        """Audit should detect non-empty tags that should be zeroed (Z action)"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x00100010, "PN", "DOE^JOHN"),
                (0x00100030, "DA", "19800101"),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            violation_tags = [v["tag"] for v in data["violations"]]
            assert "(0010,0010)" in violation_tags
            assert "(0010,0030)" in violation_tags
            findings = {v["tag"]: v["finding"] for v in data["violations"]}
            assert findings["(0010,0010)"] == "non_empty_but_should_be_zeroed"
            assert findings["(0010,0030)"] == "non_empty_but_should_be_zeroed"
        finally:
            os.unlink(fname)

    def test_d_violation_empty_value(self):
        """Audit should detect tags with empty value when D requires non-zero-length dummy"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x0040A123, "PN", ""),
                (0x00120020, "LO", ""),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            violation_tags = [v["tag"] for v in data["violations"]]
            assert "(0040,A123)" in violation_tags
            assert "(0012,0020)" in violation_tags
            findings = {v["tag"]: v["finding"] for v in data["violations"]}
            assert findings["(0040,A123)"] == "empty_but_should_have_dummy"
            assert findings["(0012,0020)"] == "empty_but_should_have_dummy"
        finally:
            os.unlink(fname)

    def test_d_tag_with_value_no_violation(self):
        """A D-action tag with a non-empty value should not be a violation"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x0040A123, "PN", "ANONYMOUS"),
                (0x00120020, "LO", "PROTOCOL001"),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            violation_tags = [v["tag"] for v in data["violations"]]
            assert "(0040,A123)" not in violation_tags
            assert "(0012,0020)" not in violation_tags
        finally:
            os.unlink(fname)

    def test_compliant_file_no_violations(self):
        """A properly de-identified file should have no X/Z violations"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x00080050, "SH", ""),
                (0x00100010, "PN", ""),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            assert len(data["violations"]) == 0
        finally:
            os.unlink(fname)

    def test_audit_with_option_changes_expectation(self):
        """When retain_full_dates is enabled, dates should be K (kept) not removed"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x00080022, "DA", "20230615"),
                (0x00100010, "PN", "DOE^JOHN"),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "retain_full_dates", "--iod-type", "2")
            violation_tags = [v["tag"] for v in data["violations"]]
            assert "(0008,0022)" not in violation_tags
            assert "(0010,0010)" in violation_tags
        finally:
            os.unlink(fname)

    def test_audit_x_resolved_from_compound(self):
        """Compound X/Z resolved to X with Type 3 means tag must be absent"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x00080022, "DA", "20230615"),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "3")
            violation_tags = [v["tag"] for v in data["violations"]]
            assert "(0008,0022)" in violation_tags
            findings = {v["tag"]: v["finding"] for v in data["violations"]}
            assert findings["(0008,0022)"] == "present_but_should_be_removed"
        finally:
            os.unlink(fname)

    def test_audit_d_resolved_from_compound(self):
        """Compound X/Z/D resolved to D with Type 1; empty value is violation"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x0008002A, "DT", ""),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "1")
            violation_tags = [v["tag"] for v in data["violations"]]
            assert "(0008,002A)" in violation_tags
            findings = {v["tag"]: v["finding"] for v in data["violations"]}
            assert findings["(0008,002A)"] == "empty_but_should_have_dummy"
        finally:
            os.unlink(fname)

    def test_audit_reports_total_checked(self):
        """Audit output includes total_checked count"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x00080050, "SH", ""),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            assert "total_checked" in data
            assert isinstance(data["total_checked"], int)
            assert data["total_checked"] > 0
        finally:
            os.unlink(fname)

    def test_audit_mixed_violations(self):
        """Audit should detect X, Z, and D violations simultaneously"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x00380010, "LO", "ADM12345"),
                (0x00100010, "PN", "DOE^JOHN"),
                (0x0040A123, "PN", ""),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            violations = {v["tag"]: v["finding"] for v in data["violations"]}
            assert violations["(0038,0010)"] == "present_but_should_be_removed"
            assert violations["(0010,0010)"] == "non_empty_but_should_be_zeroed"
            assert violations["(0040,A123)"] == "empty_but_should_have_dummy"
        finally:
            os.unlink(fname)


# ======================================================================
# AUDIT tests: recursive sequence traversal
# ======================================================================

class TestAuditSequenceRecursion:
    """Audit must detect violations inside Sequence items per PS3.15 E.1."""

    def test_z_violation_inside_sequence(self):
        """Audit detects Z violation within a sequence item"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            # Use (0008,1115) Referenced Series Sequence - NOT in action table
            # so the sequence itself is unaffected. Items inside contain table tags.
            create_test_dicom_with_sequence(
                tags_with_values=[
                    (0x00080050, "SH", ""),  # top-level Z compliant
                ],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        (0x00100010, "PN", "DOE^JOHN"),  # Z violation inside SQ
                    ],
                ],
                filename=fname,
            )

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            # There should be a violation for (0010,0010) from inside the sequence
            seq_violations = [
                v for v in data["violations"]
                if v["tag"] == "(0010,0010)" and v.get("location") == "sequence"
            ]
            assert len(seq_violations) >= 1
            assert seq_violations[0]["finding"] == "non_empty_but_should_be_zeroed"
        finally:
            os.unlink(fname)

    def test_x_violation_inside_sequence(self):
        """Audit detects X violation within a sequence item"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom_with_sequence(
                tags_with_values=[],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        (0x00380010, "LO", "ADM12345"),  # X violation inside SQ
                    ],
                ],
                filename=fname,
            )

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            seq_violations = [
                v for v in data["violations"]
                if v["tag"] == "(0038,0010)" and v.get("location") == "sequence"
            ]
            assert len(seq_violations) >= 1
            assert seq_violations[0]["finding"] == "present_but_should_be_removed"
        finally:
            os.unlink(fname)

    def test_d_violation_inside_sequence(self):
        """Audit detects D violation (empty dummy) within a sequence item"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom_with_sequence(
                tags_with_values=[],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        (0x0040A123, "PN", ""),  # D violation inside SQ: empty
                    ],
                ],
                filename=fname,
            )

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            seq_violations = [
                v for v in data["violations"]
                if v["tag"] == "(0040,A123)" and v.get("location") == "sequence"
            ]
            assert len(seq_violations) >= 1
            assert seq_violations[0]["finding"] == "empty_but_should_have_dummy"
        finally:
            os.unlink(fname)

    def test_no_violation_inside_compliant_sequence(self):
        """Compliant tags inside sequences produce no violations"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom_with_sequence(
                tags_with_values=[],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        (0x00100010, "PN", ""),  # Z compliant
                        (0x0040A123, "PN", "ANONYMOUS"),  # D compliant
                    ],
                ],
                filename=fname,
            )

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            seq_violations = [
                v for v in data["violations"]
                if v.get("location") == "sequence"
            ]
            assert len(seq_violations) == 0
        finally:
            os.unlink(fname)

    def test_audit_location_field_top_level(self):
        """Top-level violations have location='top_level'"""
        with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
            fname = f.name

        try:
            create_test_dicom([
                (0x00100010, "PN", "DOE^JOHN"),
            ], fname)

            data = run_tool("audit", "--input", fname,
                            "--options", "", "--iod-type", "2")
            pn_violations = [v for v in data["violations"] if v["tag"] == "(0010,0010)"]
            assert len(pn_violations) >= 1
            assert pn_violations[0]["location"] == "top_level"
        finally:
            os.unlink(fname)


# ======================================================================
# DEIDENTIFY tests: action code application
# ======================================================================

class TestDeidentifyActions:
    """Verify each action code is applied correctly by deidentify."""

    def test_x_removes_attribute(self):
        """X-action attribute should be absent from output"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00380010, "LO", "ADM12345"),
                (0x00080050, "SH", "ACC999"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0038, 0x0010) not in ds
            assert (0x0008, 0x0050) in ds

    def test_z_zeros_value(self):
        """Z-action attribute should have zero-length value"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00080050, "SH", "ACC123"),
                (0x00100010, "PN", "DOE^JOHN"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0008, 0x0050) in ds
            val1 = ds[0x0008, 0x0050].value
            assert val1 is None or val1 == "" or val1 == b""
            assert (0x0010, 0x0010) in ds
            val2 = ds[0x0010, 0x0010].value
            assert val2 is None or val2 == "" or val2 == b""

    def test_d_provides_dummy_pn(self):
        """D-action on PN VR should produce non-empty dummy value"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x0040A123, "PN", "SMITH^JANE"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0040, 0xA123) in ds
            val = ds[0x0040, 0xA123].value
            assert val is not None and str(val) != ""
            assert str(val) != "SMITH^JANE"

    def test_d_provides_dummy_lo(self):
        """D-action on LO VR should produce non-empty dummy value"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00120020, "LO", "PROTOCOL_ORIGINAL"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0012, 0x0020) in ds
            val = str(ds[0x0012, 0x0020].value)
            assert val != "" and val != "PROTOCOL_ORIGINAL"

    def test_u_remaps_uid(self):
        """U-action UID should be replaced with a different valid UID"""
        original_uid = "1.2.840.113619.2.55.3.604688119.969.1067867600.74"
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x0020000D, "UI", original_uid),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0020, 0x000D) in ds
            new_uid = str(ds[0x0020, 0x000D].value)
            assert new_uid != original_uid
            assert len(new_uid) > 0

    def test_compound_xz_type3_removes(self):
        """Compound X/Z resolved to X via Type 3 removes attribute"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00080022, "DA", "20230615"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "3")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0008, 0x0022) not in ds

    def test_compound_xz_type2_zeros(self):
        """Compound X/Z resolved to Z via Type 2 zeros value"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00080022, "DA", "20230615"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0008, 0x0022) in ds
            val = ds[0x0008, 0x0022].value
            assert val is None or str(val) == ""

    def test_compound_xzd_type1_provides_dummy(self):
        """Compound X/Z/D resolved to D via Type 1 produces dummy"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x0008002A, "DT", "20230615120000"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "1")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0008, 0x002A) in ds
            val = ds[0x0008, 0x002A].value
            assert val is not None and str(val) != ""
            assert str(val) != "20230615120000"


# ======================================================================
# DEIDENTIFY tests: UID consistency
# ======================================================================

class TestDeidentifyUIDConsistency:
    """UID remapping must be internally consistent across the dataset."""

    def test_same_uid_maps_to_same_replacement(self):
        """Same original UID in two U-action attributes produces same new UID"""
        shared_uid = "1.2.840.113619.2.55.3.99999999"
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x0020000D, "UI", shared_uid),
                (0x0020000E, "UI", shared_uid),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            uid1 = str(ds[0x0020, 0x000D].value)
            uid2 = str(ds[0x0020, 0x000E].value)
            assert uid1 != shared_uid
            assert uid2 != shared_uid
            assert uid1 == uid2

    def test_different_uids_map_differently(self):
        """Different original UIDs produce different replacement UIDs"""
        uid_a = "1.2.840.113619.2.55.3.11111111"
        uid_b = "1.2.840.113619.2.55.3.22222222"
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x0020000D, "UI", uid_a),
                (0x0020000E, "UI", uid_b),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            new_a = str(ds[0x0020, 0x000D].value)
            new_b = str(ds[0x0020, 0x000E].value)
            assert new_a != uid_a
            assert new_b != uid_b
            assert new_a != new_b


# ======================================================================
# DEIDENTIFY tests: metadata attributes
# ======================================================================

class TestDeidentifyMetadata:
    """De-identification metadata must be set in output."""

    def test_patient_identity_removed(self):
        """(0012,0062) Patient Identity Removed should be set to 'YES'"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00080050, "SH", "ACC999"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0012, 0x0062) in ds
            assert str(ds[0x0012, 0x0062].value) == "YES"

    def test_deidentification_method(self):
        """(0012,0063) De-identification Method should be non-empty"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00080050, "SH", "ACC999"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0012, 0x0063) in ds
            val = str(ds[0x0012, 0x0063].value)
            assert len(val) > 0


# ======================================================================
# DEIDENTIFY tests: option interaction
# ======================================================================

class TestDeidentifyOptionInteraction:
    """Options should modify deidentify behavior correctly."""

    def test_retain_full_dates_keeps_dates(self):
        """retain_full_dates: date attribute action -> K, value kept"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00080022, "DA", "20230615"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "retain_full_dates", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert str(ds[0x0008, 0x0022].value) == "20230615"

    def test_retain_uids_keeps_uids(self):
        """retain_uids: UID attribute action -> K, UID value kept unchanged"""
        original_uid = "1.2.840.113619.2.55.3.604688119.969"
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x0020000D, "UI", original_uid),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "retain_uids", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert str(ds[0x0020, 0x000D].value) == original_uid

    def test_retain_device_id_keeps_device_serial(self):
        """retain_device_id: device serial number action -> K, value kept"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00181000, "LO", "SN-2023-X500"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "retain_device_id", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert str(ds[0x0018, 0x1000].value) == "SN-2023-X500"

    def test_option_override_x_to_c_keeps_tag(self):
        """clean_descriptors changes X to C: tag is preserved (cleaned, not removed)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00184000, "LT", "Some comment text"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "clean_descriptors", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            assert (0x0018, 0x4000) in ds


# ======================================================================
# DEIDENTIFY tests: recursive sequence traversal
# ======================================================================

class TestDeidentifySequenceRecursion:
    """Per PS3.15 E.1, deidentify must process tags inside Sequence items."""

    def test_z_action_inside_sequence(self):
        """Z-action tag inside sequence item should be zeroed"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            # (0008,1115) Referenced Series Sequence is NOT in action table
            create_test_dicom_with_sequence(
                tags_with_values=[
                    (0x00080050, "SH", "ACC999"),  # top-level Z tag
                ],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        (0x00100010, "PN", "DOE^JOHN"),  # Z inside SQ
                        (0x00100030, "DA", "19800101"),   # Z inside SQ
                    ],
                ],
                filename=inf,
            )
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            # Check top-level Z was applied
            val_top = ds[0x0008, 0x0050].value
            assert val_top is None or val_top == "" or val_top == b""
            # Check inside sequence
            assert (0x0008, 0x1115) in ds  # sequence kept (not in table)
            seq = ds[0x0008, 0x1115].value
            assert len(seq) >= 1
            item = seq[0]
            # Patient Name inside SQ should be zeroed
            if (0x0010, 0x0010) in item:
                val = item[0x0010, 0x0010].value
                assert val is None or val == "" or val == b""
            # Patient Birth Date inside SQ should be zeroed
            if (0x0010, 0x0030) in item:
                val = item[0x0010, 0x0030].value
                assert val is None or val == "" or val == b""

    def test_x_action_inside_sequence(self):
        """X-action tag inside sequence item should be removed"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom_with_sequence(
                tags_with_values=[],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        (0x00380010, "LO", "ADM12345"),  # X inside SQ
                        (0x001021B0, "LT", "History"),    # X inside SQ
                    ],
                ],
                filename=inf,
            )
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            seq = ds[0x0008, 0x1115].value
            assert len(seq) >= 1
            item = seq[0]
            # X-action tags should be removed from item
            assert (0x0038, 0x0010) not in item
            assert (0x0010, 0x21B0) not in item

    def test_d_action_inside_sequence(self):
        """D-action tag inside sequence item should have non-empty dummy"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom_with_sequence(
                tags_with_values=[],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        (0x0040A123, "PN", "SMITH^JANE"),  # D inside SQ
                    ],
                ],
                filename=inf,
            )
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            seq = ds[0x0008, 0x1115].value
            item = seq[0]
            assert (0x0040, 0xA123) in item
            val = str(item[0x0040, 0xA123].value)
            assert val != "" and val != "SMITH^JANE"

    def test_u_action_inside_sequence_consistent_with_top_level(self):
        """U-action UID inside sequence must remap consistently with top-level"""
        shared_uid = "1.2.840.113619.2.55.3.77777777"
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom_with_sequence(
                tags_with_values=[
                    (0x0020000D, "UI", shared_uid),  # Study Instance UID: U at top
                ],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        # Referenced SOP Instance UID (0008,1155): U action, retain_uids=K
                        # Use Study Instance UID (0020,000D) again inside SQ
                        (0x0020000D, "UI", shared_uid),  # Same UID inside SQ
                    ],
                ],
                filename=inf,
            )
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            ds = pydicom.dcmread(outf, force=True)
            top_uid = str(ds[0x0020, 0x000D].value)
            seq = ds[0x0008, 0x1115].value
            item = seq[0]
            seq_uid = str(item[0x0020, 0x000D].value)
            # Both must map to the same replacement
            assert top_uid != shared_uid
            assert seq_uid != shared_uid
            assert top_uid == seq_uid

    def test_deidentify_sequence_then_audit_passes(self):
        """Deidentified file with sequences should pass audit (including in-sequence checks)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom_with_sequence(
                tags_with_values=[
                    (0x00080050, "SH", "ACC123"),
                    (0x00100010, "PN", "DOE^JOHN"),
                ],
                seq_tag=0x00081115,
                seq_items=[
                    [
                        (0x00100010, "PN", "NESTED^NAME"),
                        (0x0040A123, "PN", "NESTED^PERSON"),
                    ],
                ],
                filename=inf,
            )
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            # Audit the output
            audit = run_tool("audit", "--input", outf,
                             "--options", "", "--iod-type", "2")
            assert len(audit["violations"]) == 0


# ======================================================================
# DEIDENTIFY tests: multi-file dataset mode
# ======================================================================

class TestDeidentifyDatasetMode:
    """Dataset mode (--input-dir/--output-dir) with cross-file UID consistency."""

    def test_dataset_processes_all_files(self):
        """Dataset mode processes all .dcm files in directory"""
        with tempfile.TemporaryDirectory() as indir, \
             tempfile.TemporaryDirectory() as outdir:
            # Create 3 DICOM files
            for i in range(3):
                fname = os.path.join(indir, f"file{i}.dcm")
                create_test_dicom([
                    (0x00080050, "SH", f"ACC{i}"),
                    (0x00100010, "PN", f"PAT{i}^NAME"),
                ], fname)

            result = run_tool("deidentify",
                              "--input-dir", indir, "--output-dir", outdir,
                              "--options", "", "--iod-type", "2")
            assert result["status"] == "ok"
            assert result["files_processed"] == 3

            # Verify output files exist and are valid DICOM
            out_files = sorted(glob.glob(os.path.join(outdir, "*.dcm")))
            assert len(out_files) == 3
            for outf in out_files:
                ds = pydicom.dcmread(outf, force=True)
                # Patient Identity Removed should be set
                assert str(ds[0x0012, 0x0062].value) == "YES"

    def test_dataset_cross_file_uid_consistency(self):
        """Same UID across different files must map to same replacement"""
        shared_study_uid = "1.2.840.113619.2.55.3.88888888"
        with tempfile.TemporaryDirectory() as indir, \
             tempfile.TemporaryDirectory() as outdir:
            # Two files sharing the same Study Instance UID
            for i in range(2):
                fname = os.path.join(indir, f"series{i}.dcm")
                create_test_dicom([
                    (0x0020000D, "UI", shared_study_uid),
                    (0x0020000E, "UI", f"1.2.840.113619.2.55.3.{i+1}0000000"),
                    (0x00080050, "SH", f"ACC{i}"),
                ], fname)

            run_tool("deidentify",
                     "--input-dir", indir, "--output-dir", outdir,
                     "--options", "", "--iod-type", "2")

            out_files = sorted(glob.glob(os.path.join(outdir, "*.dcm")))
            assert len(out_files) == 2

            ds0 = pydicom.dcmread(out_files[0], force=True)
            ds1 = pydicom.dcmread(out_files[1], force=True)

            # Study Instance UIDs must be the same (same original -> same replacement)
            uid0 = str(ds0[0x0020, 0x000D].value)
            uid1 = str(ds1[0x0020, 0x000D].value)
            assert uid0 != shared_study_uid  # changed
            assert uid1 != shared_study_uid  # changed
            assert uid0 == uid1              # consistent

            # Series Instance UIDs must be different (different originals)
            series0 = str(ds0[0x0020, 0x000E].value)
            series1 = str(ds1[0x0020, 0x000E].value)
            assert series0 != series1

    def test_dataset_different_uids_stay_different(self):
        """Different UIDs across files must map to different replacements"""
        with tempfile.TemporaryDirectory() as indir, \
             tempfile.TemporaryDirectory() as outdir:
            uid_a = "1.2.840.113619.2.55.3.44444444"
            uid_b = "1.2.840.113619.2.55.3.55555555"
            create_test_dicom([
                (0x0020000D, "UI", uid_a),
            ], os.path.join(indir, "a.dcm"))
            create_test_dicom([
                (0x0020000D, "UI", uid_b),
            ], os.path.join(indir, "b.dcm"))

            run_tool("deidentify",
                     "--input-dir", indir, "--output-dir", outdir,
                     "--options", "", "--iod-type", "2")

            out_files = sorted(glob.glob(os.path.join(outdir, "*.dcm")))
            ds_a = pydicom.dcmread(out_files[0], force=True)
            ds_b = pydicom.dcmread(out_files[1], force=True)
            new_a = str(ds_a[0x0020, 0x000D].value)
            new_b = str(ds_b[0x0020, 0x000D].value)
            assert new_a != uid_a
            assert new_b != uid_b
            assert new_a != new_b

    def test_dataset_z_action_applied_across_files(self):
        """Z-action attributes zeroed consistently across all dataset files"""
        with tempfile.TemporaryDirectory() as indir, \
             tempfile.TemporaryDirectory() as outdir:
            for i in range(2):
                fname = os.path.join(indir, f"pat{i}.dcm")
                create_test_dicom([
                    (0x00100010, "PN", f"PATIENT{i}^NAME"),
                    (0x00080050, "SH", f"ACC{i}"),
                ], fname)

            run_tool("deidentify",
                     "--input-dir", indir, "--output-dir", outdir,
                     "--options", "", "--iod-type", "2")

            out_files = sorted(glob.glob(os.path.join(outdir, "*.dcm")))
            for outf in out_files:
                ds = pydicom.dcmread(outf, force=True)
                pn = ds[0x0010, 0x0010].value
                assert pn is None or pn == "" or pn == b""
                acc = ds[0x0008, 0x0050].value
                assert acc is None or acc == "" or acc == b""

    def test_dataset_audit_chain(self):
        """Each file in de-identified dataset must pass audit"""
        with tempfile.TemporaryDirectory() as indir, \
             tempfile.TemporaryDirectory() as outdir:
            shared_uid = "1.2.840.113619.2.55.3.66666666"
            for i in range(2):
                fname = os.path.join(indir, f"ds{i}.dcm")
                create_test_dicom([
                    (0x0020000D, "UI", shared_uid),
                    (0x00100010, "PN", f"NAME{i}"),
                    (0x00380010, "LO", f"ADM{i}"),
                    (0x0040A123, "PN", f"PERSON{i}"),
                ], fname)

            run_tool("deidentify",
                     "--input-dir", indir, "--output-dir", outdir,
                     "--options", "", "--iod-type", "2")

            out_files = sorted(glob.glob(os.path.join(outdir, "*.dcm")))
            for outf in out_files:
                audit = run_tool("audit", "--input", outf,
                                 "--options", "", "--iod-type", "2")
                assert len(audit["violations"]) == 0
                assert audit["total_checked"] > 0


# ======================================================================
# DEIDENTIFY + AUDIT chain tests (single file)
# ======================================================================

class TestDeidentifyAuditChain:
    """Deidentified output must pass audit with zero violations."""

    def test_basic_deidentify_passes_audit(self):
        """File deidentified with basic profile passes audit with 0 violations"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00380010, "LO", "ADM12345"),
                (0x00080050, "SH", "ACC123"),
                (0x0040A123, "PN", "DOE^JOHN"),
                (0x00100010, "PN", "SMITH^JANE"),
                (0x001021B0, "LT", "Patient history"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "2")
            audit = run_tool("audit", "--input", outf,
                             "--options", "", "--iod-type", "2")
            assert len(audit["violations"]) == 0
            assert audit["total_checked"] > 0

    def test_deidentify_with_options_passes_audit(self):
        """File deidentified with options passes audit using same options"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x00080022, "DA", "20230615"),
                (0x00100010, "PN", "DOE^JOHN"),
                (0x00380010, "LO", "ADM12345"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "retain_full_dates", "--iod-type", "2")
            audit = run_tool("audit", "--input", outf,
                             "--options", "retain_full_dates", "--iod-type", "2")
            assert len(audit["violations"]) == 0

    def test_compound_resolution_chain(self):
        """Compound codes resolved via IOD type pass deidentify->audit chain"""
        with tempfile.TemporaryDirectory() as tmpdir:
            inf = os.path.join(tmpdir, "in.dcm")
            outf = os.path.join(tmpdir, "out.dcm")
            create_test_dicom([
                (0x0008002A, "DT", "20230615120000"),
                (0x00100020, "LO", "PAT12345"),
            ], inf)
            run_tool("deidentify", "--input", inf, "--output", outf,
                     "--options", "", "--iod-type", "1")
            audit = run_tool("audit", "--input", outf,
                             "--options", "", "--iod-type", "1")
            assert len(audit["violations"]) == 0
            ds = pydicom.dcmread(outf, force=True)
            val_dt = ds[0x0008, 0x002A].value
            assert val_dt is not None and str(val_dt) != ""
            assert str(val_dt) != "20230615120000"
            val_id = ds[0x0010, 0x0020].value
            assert val_id is not None and str(val_id) != ""
            assert str(val_id) != "PAT12345"
