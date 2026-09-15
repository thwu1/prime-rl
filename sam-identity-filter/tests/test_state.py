"""Tests for BAM alignment quality audit.

"""
import json
import os
import subprocess
import pytest

TOLERANCE = 1e-4
MEAN_TOLERANCE = 1e-3


@pytest.fixture(scope="session")
def report():
    """Load the audit report produced by the agent."""
    assert os.path.exists("/app/audit_report.json"), "audit_report.json not found at /app/"
    with open("/app/audit_report.json") as f:
        return json.load(f)


# --- Structural tests ---

def test_report_exists():
    assert os.path.exists("/app/audit_report.json"), "audit_report.json not found"


def test_report_structure(report):
    required_keys = [
        "total_records", "primary_alignments", "supplementary_alignments",
        "secondary_alignments", "unmapped", "passed_filter", "failed_filter",
        "nm_corrections", "reads", "per_reference"
    ]
    for key in required_keys:
        assert key in report, f"Missing key: {key}"


def test_per_read_structure(report):
    """Each read entry must have the required identity fields."""
    required = {"blast_identity", "gc_identity", "gap_excluded_identity",
                "passed", "nm_corrected", "is_chimeric"}
    for qname, data in report["reads"].items():
        for field in required:
            assert field in data, f"Read {qname} missing field: {field}"


# --- Record count tests ---

def test_total_records(report):
    assert report["total_records"] == 20


def test_primary_alignments(report):
    assert report["primary_alignments"] == 17


def test_supplementary_count(report):
    assert report["supplementary_alignments"] == 1


def test_secondary_count(report):
    assert report["secondary_alignments"] == 1


def test_unmapped_count(report):
    assert report["unmapped"] == 1


def test_passed_filter(report):
    assert report["passed_filter"] == 14


def test_failed_filter(report):
    assert report["failed_filter"] == 3


def test_nm_corrections(report):
    assert report["nm_corrections"] == 2


# --- Per-read identity tests ---

def test_read01_perfect_alignment(report):
    """50M, NM=0: perfect alignment, all identities = 1.0."""
    r = report["reads"]["read01"]
    assert abs(r["blast_identity"] - 1.0) < TOLERANCE
    assert abs(r["gc_identity"] - 1.0) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 1.0) < TOLERANCE
    assert r["passed"] is True
    assert r["nm_corrected"] is False
    assert r["is_chimeric"] is False


def test_read02_mismatches_only(report):
    """50M, NM=3: no gaps, all three metrics identical."""
    r = report["reads"]["read02"]
    assert abs(r["blast_identity"] - 0.94) < TOLERANCE
    assert abs(r["gc_identity"] - 0.94) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 0.94) < TOLERANCE


def test_read03_deletion(report):
    """20M3D30M, NM=4: 1 mismatch + 3 del bases."""
    r = report["reads"]["read03"]
    assert abs(r["blast_identity"] - 49 / 53) < TOLERANCE
    assert abs(r["gc_identity"] - 49 / 51) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 49 / 50) < TOLERANCE


def test_read04_insertion_no_mismatches(report):
    """25M2I23M, NM=2: pure insertion, 0 mismatches. gap_excluded should be 1.0."""
    r = report["reads"]["read04"]
    assert abs(r["blast_identity"] - 0.96) < TOLERANCE
    assert abs(r["gc_identity"] - 48 / 49) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 1.0) < TOLERANCE


def test_read05_complex_cigar(report):
    """18M3D2M2D2M1I22M, NM=7: multiple gap events."""
    r = report["reads"]["read05"]
    assert abs(r["blast_identity"] - 0.86) < TOLERANCE
    assert abs(r["gc_identity"] - 43 / 47) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 43 / 44) < TOLERANCE
    assert r["passed"] is True


def test_read06_extended_cigar_no_gaps(report):
    """15=2X3=1X29=, NM=3: extended CIGAR, no gaps."""
    r = report["reads"]["read06"]
    assert abs(r["blast_identity"] - 0.94) < TOLERANCE
    assert abs(r["gc_identity"] - 0.94) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 0.94) < TOLERANCE
    assert r["nm_corrected"] is False


def test_read07_extended_cigar_with_gaps(report):
    """10=1X5=2I3=4D25=, NM=7: extended CIGAR with both gap types."""
    r = report["reads"]["read07"]
    assert abs(r["blast_identity"] - 43 / 50) < TOLERANCE
    assert abs(r["gc_identity"] - 43 / 46) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 43 / 44) < TOLERANCE


def test_read08_soft_clipped(report):
    """5S40M5S, NM=2: soft clips excluded from identity computation."""
    r = report["reads"]["read08"]
    assert abs(r["blast_identity"] - 0.95) < TOLERANCE
    assert abs(r["gc_identity"] - 0.95) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 0.95) < TOLERANCE


def test_read09_hard_clipped(report):
    """10H40M, NM=1: hard clips excluded from identity computation."""
    r = report["reads"]["read09"]
    assert abs(r["blast_identity"] - 0.975) < TOLERANCE
    assert abs(r["gc_identity"] - 0.975) < TOLERANCE


def test_read10_chimeric_detection(report):
    """Chimeric read (SA tag + supplementary record): must be flagged."""
    r = report["reads"]["read10"]
    assert r["is_chimeric"] is True
    assert abs(r["blast_identity"] - 29 / 30) < TOLERANCE
    assert abs(r["gc_identity"] - 29 / 30) < TOLERANCE
    assert r["passed"] is True


def test_read11_secondary_ignored(report):
    """read11 has secondary (NM=5) and primary (NM=2). Must use primary."""
    r = report["reads"]["read11"]
    assert abs(r["blast_identity"] - 0.96) < TOLERANCE
    assert abs(r["gc_identity"] - 0.96) < TOLERANCE


def test_read12_unmapped_excluded(report):
    """Unmapped reads should not appear in per-read results."""
    assert "read12" not in report["reads"]


def test_read13_multiple_gaps_fails(report):
    """10M2I5M3D10M1I5M4D15M, NM=12: 4 gap events, should fail at 0.90."""
    r = report["reads"]["read13"]
    assert abs(r["blast_identity"] - 43 / 55) < TOLERANCE
    assert abs(r["gc_identity"] - 43 / 49) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 43 / 45) < TOLERANCE
    assert r["passed"] is False


def test_read14_high_error(report):
    """50M, NM=15: all metrics identical and low (0.7)."""
    r = report["reads"]["read14"]
    assert abs(r["blast_identity"] - 0.7) < TOLERANCE
    assert abs(r["gc_identity"] - 0.7) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 0.7) < TOLERANCE
    assert r["passed"] is False


def test_read15_large_insertion_identity_gap(report):
    """20M10I20M, NM=11: large insertion. blast=0.78 but gc~0.951."""
    r = report["reads"]["read15"]
    assert abs(r["blast_identity"] - 0.78) < TOLERANCE
    assert abs(r["gc_identity"] - 39 / 41) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 0.975) < TOLERANCE
    assert r["passed"] is True


def test_read16_gc_boundary(report):
    """5=1X10=3I2=2X8=5D20=, NM=11: gc identity exactly 0.9, should pass."""
    r = report["reads"]["read16"]
    assert abs(r["gc_identity"] - 0.9) < TOLERANCE
    assert r["passed"] is True
    assert r["nm_corrected"] is False


def test_read17_nm_corrected_passes(report):
    """20=1X10=2X17=, NM given as 5 but correct is 3. After correction, passes."""
    r = report["reads"]["read17"]
    assert r["nm_corrected"] is True
    assert abs(r["blast_identity"] - 0.94) < TOLERANCE
    assert abs(r["gc_identity"] - 0.94) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 0.94) < TOLERANCE
    assert r["passed"] is True


def test_read18_nm_corrected_fails(report):
    """8=2X5=3I10=1X2D15=1X5=, NM given as 12 but correct is 9. Fails filter."""
    r = report["reads"]["read18"]
    assert r["nm_corrected"] is True
    assert abs(r["blast_identity"] - 43 / 52) < TOLERANCE
    assert abs(r["gc_identity"] - 43 / 49) < TOLERANCE
    assert abs(r["gap_excluded_identity"] - 43 / 47) < TOLERANCE
    assert r["passed"] is False


# --- Per-reference statistics tests ---

def test_chr1_stats(report):
    """chr1 has 11 primary reads, all passing at 0.90 threshold."""
    chr1 = report["per_reference"]["chr1"]
    assert chr1["count"] == 11
    assert chr1["passed"] == 11
    assert chr1["failed"] == 0
    assert abs(chr1["mean_blast_identity"] - 0.93965) < MEAN_TOLERANCE
    assert abs(chr1["mean_gc_identity"] - 0.95652) < MEAN_TOLERANCE
    assert abs(chr1["mean_gap_excluded_identity"] - 0.96966) < MEAN_TOLERANCE


def test_chr2_stats(report):
    """chr2 has 6 primary reads, 3 passing and 3 failing."""
    chr2 = report["per_reference"]["chr2"]
    assert chr2["count"] == 6
    assert chr2["passed"] == 3
    assert chr2["failed"] == 3
    assert abs(chr2["mean_blast_identity"] - 0.80539) < MEAN_TOLERANCE
    assert abs(chr2["mean_gc_identity"] - 0.87439) < MEAN_TOLERANCE
    assert abs(chr2["mean_gap_excluded_identity"] - 0.90382) < MEAN_TOLERANCE


# --- Filtered BAM tests ---

def test_filtered_bam_exists():
    """The filtered BAM file must exist."""
    assert os.path.exists("/app/filtered.bam"), "filtered.bam not found at /app/"


def test_filtered_bam_index_exists():
    """The BAM index must exist alongside the filtered BAM."""
    assert os.path.exists("/app/filtered.bam.bai"), "filtered.bam.bai not found at /app/"


def test_filtered_bam_is_sorted():
    """The filtered BAM must be coordinate-sorted."""
    result = subprocess.run(
        ["samtools", "view", "-H", "/app/filtered.bam"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"samtools view -H failed: {result.stderr}"
    assert "SO:coordinate" in result.stdout, "filtered.bam is not coordinate-sorted"


def test_filtered_bam_record_count():
    """The filtered BAM must contain exactly 14 passing primary alignments."""
    result = subprocess.run(
        ["samtools", "view", "-c", "/app/filtered.bam"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"samtools view -c failed: {result.stderr}"
    assert int(result.stdout.strip()) == 14, (
        f"Expected 14 records, got {result.stdout.strip()}"
    )


def test_filtered_bam_read_names():
    """The filtered BAM must contain exactly the 14 passing primary reads."""
    result = subprocess.run(
        ["samtools", "view", "/app/filtered.bam"],
        capture_output=True, text=True
    )
    assert result.returncode == 0, f"samtools view failed: {result.stderr}"

    qnames = set(
        line.split("\t")[0]
        for line in result.stdout.strip().split("\n")
        if line
    )

    # Failing reads must NOT be present
    assert "read13" not in qnames, "read13 should be filtered out (fails gc threshold)"
    assert "read14" not in qnames, "read14 should be filtered out (fails gc threshold)"
    assert "read18" not in qnames, "read18 should be filtered out (fails gc threshold)"

    # Unmapped/secondary/supplementary must NOT be present
    assert "read12" not in qnames, "unmapped read12 should not appear"

    # All passing primary reads must be present
    expected = {"read01", "read02", "read03", "read04", "read05",
                "read06", "read07", "read08", "read09", "read10",
                "read11", "read15", "read16", "read17"}
    assert expected == qnames, f"Expected {expected}, got {qnames}"


def test_filtered_bam_nm_corrected():
    """read17 must have NM:i:3 in the filtered BAM (corrected from 5)."""
    result = subprocess.run(
        ["samtools", "view", "/app/filtered.bam"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    for line in result.stdout.strip().split("\n"):
        fields = line.split("\t")
        if fields[0] == "read17":
            nm_tags = [f for f in fields[11:] if f.startswith("NM:i:")]
            assert len(nm_tags) == 1, f"read17 should have exactly one NM tag"
            assert nm_tags[0] == "NM:i:3", (
                f"read17 NM should be corrected to 3, got {nm_tags[0]}"
            )
            return
    pytest.fail("read17 not found in filtered BAM")
