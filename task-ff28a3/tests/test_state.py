
import json
import os
import pytest

REPORT_PATH = "/app/report.json"
TOL = 1e-5
COV_TOL = 0.05

# ---- Expected identity metrics (9 primary, non-dup, mapped alignments) ----
# Sorted by coordinate: chr1 first (positions 10, 150, 300, 450, 550), then chr2 (100, 200, 350, 500)
EXPECTED_ALIGNMENT_IDENTITIES = [
    {
        "read_name": "read01",
        "flag": 0,
        "cigar": "100M",
        "ref_name": "chr1",
        "position": 10,
        "blast_identity": 0.97,
        "gap_compressed_identity": 0.97,
        "gap_excluded_identity": 0.97,
    },
    {
        "read_name": "read02",
        "flag": 0,
        "cigar": "30M5D70M",
        "ref_name": "chr1",
        "position": 150,
        "blast_identity": 0.933333,
        "gap_compressed_identity": 0.970297,
        "gap_excluded_identity": 0.98,
    },
    {
        "read_name": "read03",
        "flag": 0,
        "cigar": "40M3I57M",
        "ref_name": "chr1",
        "position": 300,
        "blast_identity": 0.95,
        "gap_compressed_identity": 0.969388,
        "gap_excluded_identity": 0.979381,
    },
    {
        "read_name": "read04",
        "flag": 0,
        "cigar": "18M3D2M2D2M1I22M",
        "ref_name": "chr1",
        "position": 450,
        "blast_identity": 0.86,
        "gap_compressed_identity": 0.914894,
        "gap_excluded_identity": 0.977273,
    },
    {
        "read_name": "read05",
        "flag": 0,
        "cigar": "5S45M2I48M",
        "ref_name": "chr1",
        "position": 550,
        "blast_identity": 0.957895,
        "gap_compressed_identity": 0.968085,
        "gap_excluded_identity": 0.978495,
    },
    {
        "read_name": "read09",
        "flag": 0,
        "cigar": "10H25M1I2M3D20M5H",
        "ref_name": "chr2",
        "position": 100,
        "blast_identity": 0.882353,
        "gap_compressed_identity": 0.918367,
        "gap_excluded_identity": 0.957447,
    },
    {
        "read_name": "read10",
        "flag": 99,
        "cigar": "75M",
        "ref_name": "chr2",
        "position": 200,
        "blast_identity": 1.0,
        "gap_compressed_identity": 1.0,
        "gap_excluded_identity": 1.0,
    },
    {
        "read_name": "read10",
        "flag": 147,
        "cigar": "75M",
        "ref_name": "chr2",
        "position": 350,
        "blast_identity": 0.986667,
        "gap_compressed_identity": 0.986667,
        "gap_excluded_identity": 0.986667,
    },
    {
        "read_name": "read11",
        "flag": 0,
        "cigar": "20=2X3=1I5=3D15=2X8=",
        "ref_name": "chr2",
        "position": 500,
        "blast_identity": 0.864407,
        "gap_compressed_identity": 0.894737,
        "gap_excluded_identity": 0.927273,
    },
]

EXPECTED_IDENTITY_SUMMARY = {
    "num_alignments": 9,
    "mean_blast_identity": 0.933851,
    "mean_gap_compressed_identity": 0.954715,
    "mean_gap_excluded_identity": 0.972948,
    "high_quality_count": 6,
    "medium_quality_count": 3,
    "low_quality_count": 0,
}

EXPECTED_MAPPING_STATS = {
    "total_reads": 14,
    "mapped_reads": 13,
    "duplicates": 2,
    "mapping_rate": 0.928571,
}

EXPECTED_TARGET_COVERAGE = [
    {"chrom": "chr1", "start": 5, "end": 115, "mean_depth": 0.91},
    {"chrom": "chr1", "start": 290, "end": 400, "mean_depth": 0.88},
    {"chrom": "chr2", "start": 195, "end": 280, "mean_depth": 0.88},
    {"chrom": "chr2", "start": 340, "end": 430, "mean_depth": 0.83},
]

EXPECTED_ASSEMBLY_STATS = {
    "num_contigs": 7,
    "total_length": 1460,
    "largest_contig": 520,
    "n50": 380,
    "l50": 2,
    "aun": 348.630137,
    "gc_content": 0.436986,
}


@pytest.fixture(scope="module")
def report():
    assert os.path.exists(REPORT_PATH), f"Report file not found at {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


# ---- Data Issues ----

class TestDataIssues:
    def test_data_issues_exist(self, report):
        issues = report.get("data_issues", [])
        assert len(issues) >= 2, (
            f"Expected at least 2 data issues, found {len(issues)}. "
            "The alignment data has multiple quality problems that must be identified."
        )

    def test_naming_issue_identified(self, report):
        issues = report.get("data_issues", [])
        text = " ".join(issues).lower()
        naming_keywords = ["chromosome", "scaffold", "naming", "rename", "mismatch", "contig name", "sequence name", "chrom"]
        assert any(kw in text for kw in naming_keywords), (
            "No data issue mentions chromosome/scaffold naming mismatch. "
            "The SAM file uses 'scaffold_*' names while the reference uses 'chr*'."
        )

    def test_duplicate_issue_identified(self, report):
        issues = report.get("data_issues", [])
        text = " ".join(issues).lower()
        dup_keywords = ["duplicate", "pcr", "dedup", "markdup", "dup"]
        assert any(kw in text for kw in dup_keywords), (
            "No data issue mentions PCR duplicates. "
            "The alignment contains duplicate read pairs that need marking/removal."
        )


# ---- Report Structure ----

class TestReportStructure:
    def test_has_alignment_identities(self, report):
        assert "alignment_identities" in report, "Missing 'alignment_identities' key"

    def test_has_identity_summary(self, report):
        assert "identity_summary" in report, "Missing 'identity_summary' key"

    def test_has_mapping_stats(self, report):
        assert "mapping_stats" in report, "Missing 'mapping_stats' key"

    def test_has_target_coverage(self, report):
        assert "target_coverage" in report, "Missing 'target_coverage' key"

    def test_has_assembly_stats(self, report):
        assert "assembly_stats" in report, "Missing 'assembly_stats' key"

    def test_correct_number_of_alignments(self, report):
        metrics = report["alignment_identities"]
        assert len(metrics) == 9, (
            f"Expected 9 non-redundant primary mapped alignments, got {len(metrics)}. "
            "Must exclude unmapped, secondary (FLAG 0x100), supplementary (FLAG 0x800), "
            "and duplicate records."
        )


# ---- Alignment Identity Metrics ----

class TestAlignmentIdentities:
    @pytest.mark.parametrize("idx", range(len(EXPECTED_ALIGNMENT_IDENTITIES)))
    def test_read_name(self, report, idx):
        actual = report["alignment_identities"][idx]
        expected = EXPECTED_ALIGNMENT_IDENTITIES[idx]
        assert actual["read_name"] == expected["read_name"], (
            f"Alignment {idx}: expected read_name '{expected['read_name']}', "
            f"got '{actual['read_name']}'"
        )

    @pytest.mark.parametrize("idx", range(len(EXPECTED_ALIGNMENT_IDENTITIES)))
    def test_ref_name_uses_chr_convention(self, report, idx):
        actual = report["alignment_identities"][idx]
        expected = EXPECTED_ALIGNMENT_IDENTITIES[idx]
        assert actual["ref_name"] == expected["ref_name"], (
            f"Alignment {idx} ({expected['read_name']}): "
            f"expected ref_name '{expected['ref_name']}' (reference convention), "
            f"got '{actual['ref_name']}'"
        )

    @pytest.mark.parametrize("idx", range(len(EXPECTED_ALIGNMENT_IDENTITIES)))
    def test_blast_identity(self, report, idx):
        actual = report["alignment_identities"][idx]
        expected = EXPECTED_ALIGNMENT_IDENTITIES[idx]
        assert abs(actual["blast_identity"] - expected["blast_identity"]) < TOL, (
            f"Alignment {idx} ({expected['read_name']}, CIGAR={expected['cigar']}): "
            f"BLAST identity expected {expected['blast_identity']}, "
            f"got {actual['blast_identity']}"
        )

    @pytest.mark.parametrize("idx", range(len(EXPECTED_ALIGNMENT_IDENTITIES)))
    def test_gap_compressed_identity(self, report, idx):
        actual = report["alignment_identities"][idx]
        expected = EXPECTED_ALIGNMENT_IDENTITIES[idx]
        assert abs(
            actual["gap_compressed_identity"] - expected["gap_compressed_identity"]
        ) < TOL, (
            f"Alignment {idx} ({expected['read_name']}, CIGAR={expected['cigar']}): "
            f"gap-compressed identity expected "
            f"{expected['gap_compressed_identity']}, "
            f"got {actual['gap_compressed_identity']}"
        )

    @pytest.mark.parametrize("idx", range(len(EXPECTED_ALIGNMENT_IDENTITIES)))
    def test_gap_excluded_identity(self, report, idx):
        actual = report["alignment_identities"][idx]
        expected = EXPECTED_ALIGNMENT_IDENTITIES[idx]
        assert abs(
            actual["gap_excluded_identity"] - expected["gap_excluded_identity"]
        ) < TOL, (
            f"Alignment {idx} ({expected['read_name']}, CIGAR={expected['cigar']}): "
            f"gap-excluded identity expected "
            f"{expected['gap_excluded_identity']}, "
            f"got {actual['gap_excluded_identity']}"
        )

    @pytest.mark.parametrize("idx", range(len(EXPECTED_ALIGNMENT_IDENTITIES)))
    def test_position(self, report, idx):
        actual = report["alignment_identities"][idx]
        expected = EXPECTED_ALIGNMENT_IDENTITIES[idx]
        assert actual["position"] == expected["position"], (
            f"Alignment {idx}: expected position {expected['position']}, "
            f"got {actual['position']}"
        )


# ---- Identity Summary ----

class TestIdentitySummary:
    def test_num_alignments(self, report):
        actual = report["identity_summary"]["num_alignments"]
        expected = EXPECTED_IDENTITY_SUMMARY["num_alignments"]
        assert actual == expected, (
            f"Expected {expected} alignments, got {actual}"
        )

    def test_mean_blast_identity(self, report):
        actual = report["identity_summary"]["mean_blast_identity"]
        expected = EXPECTED_IDENTITY_SUMMARY["mean_blast_identity"]
        assert abs(actual - expected) < TOL, (
            f"Mean BLAST identity: expected {expected}, got {actual}"
        )

    def test_mean_gap_compressed_identity(self, report):
        actual = report["identity_summary"]["mean_gap_compressed_identity"]
        expected = EXPECTED_IDENTITY_SUMMARY["mean_gap_compressed_identity"]
        assert abs(actual - expected) < TOL, (
            f"Mean gap-compressed identity: expected {expected}, got {actual}"
        )

    def test_mean_gap_excluded_identity(self, report):
        actual = report["identity_summary"]["mean_gap_excluded_identity"]
        expected = EXPECTED_IDENTITY_SUMMARY["mean_gap_excluded_identity"]
        assert abs(actual - expected) < TOL, (
            f"Mean gap-excluded identity: expected {expected}, got {actual}"
        )

    def test_high_quality_count(self, report):
        actual = report["identity_summary"]["high_quality_count"]
        expected = EXPECTED_IDENTITY_SUMMARY["high_quality_count"]
        assert actual == expected, (
            f"High quality count (gc_id >= 0.95): expected {expected}, got {actual}"
        )

    def test_medium_quality_count(self, report):
        actual = report["identity_summary"]["medium_quality_count"]
        expected = EXPECTED_IDENTITY_SUMMARY["medium_quality_count"]
        assert actual == expected, (
            f"Medium quality count (0.85 <= gc_id < 0.95): expected {expected}, got {actual}"
        )

    def test_low_quality_count(self, report):
        actual = report["identity_summary"]["low_quality_count"]
        expected = EXPECTED_IDENTITY_SUMMARY["low_quality_count"]
        assert actual == expected, (
            f"Low quality count (gc_id < 0.85): expected {expected}, got {actual}"
        )


# ---- Mapping Stats ----

class TestMappingStats:
    def test_total_reads(self, report):
        actual = report["mapping_stats"]["total_reads"]
        expected = EXPECTED_MAPPING_STATS["total_reads"]
        assert actual == expected, (
            f"Total reads: expected {expected}, got {actual}"
        )

    def test_mapped_reads(self, report):
        actual = report["mapping_stats"]["mapped_reads"]
        expected = EXPECTED_MAPPING_STATS["mapped_reads"]
        assert actual == expected, (
            f"Mapped reads: expected {expected}, got {actual}"
        )

    def test_duplicates(self, report):
        actual = report["mapping_stats"]["duplicates"]
        expected = EXPECTED_MAPPING_STATS["duplicates"]
        assert actual == expected, (
            f"Duplicates: expected {expected}, got {actual}"
        )

    def test_mapping_rate(self, report):
        actual = report["mapping_stats"]["mapping_rate"]
        expected = EXPECTED_MAPPING_STATS["mapping_rate"]
        assert abs(actual - expected) < TOL, (
            f"Mapping rate: expected {expected}, got {actual}"
        )


# ---- Target Coverage ----

class TestTargetCoverage:
    def test_correct_number_of_regions(self, report):
        coverage = report["target_coverage"]
        assert len(coverage) == 4, (
            f"Expected 4 target regions, got {len(coverage)}"
        )

    @pytest.mark.parametrize("idx", range(len(EXPECTED_TARGET_COVERAGE)))
    def test_region_coverage(self, report, idx):
        actual = report["target_coverage"][idx]
        expected = EXPECTED_TARGET_COVERAGE[idx]
        assert actual["chrom"] == expected["chrom"], (
            f"Region {idx}: expected chrom '{expected['chrom']}', got '{actual['chrom']}'"
        )
        assert actual["start"] == expected["start"], (
            f"Region {idx}: expected start {expected['start']}, got {actual['start']}"
        )
        assert actual["end"] == expected["end"], (
            f"Region {idx}: expected end {expected['end']}, got {actual['end']}"
        )
        assert abs(actual["mean_depth"] - expected["mean_depth"]) < COV_TOL, (
            f"Region {idx} ({expected['chrom']}:{expected['start']}-{expected['end']}): "
            f"mean_depth expected {expected['mean_depth']}, got {actual['mean_depth']}"
        )


# ---- Assembly Stats ----

class TestAssemblyStats:
    def test_num_contigs(self, report):
        actual = report["assembly_stats"]["num_contigs"]
        expected = EXPECTED_ASSEMBLY_STATS["num_contigs"]
        assert actual == expected, (
            f"Number of contigs: expected {expected}, got {actual}"
        )

    def test_total_length(self, report):
        actual = report["assembly_stats"]["total_length"]
        expected = EXPECTED_ASSEMBLY_STATS["total_length"]
        assert actual == expected, (
            f"Total length: expected {expected}, got {actual}"
        )

    def test_largest_contig(self, report):
        actual = report["assembly_stats"]["largest_contig"]
        expected = EXPECTED_ASSEMBLY_STATS["largest_contig"]
        assert actual == expected, (
            f"Largest contig: expected {expected}, got {actual}"
        )

    def test_n50(self, report):
        actual = report["assembly_stats"]["n50"]
        expected = EXPECTED_ASSEMBLY_STATS["n50"]
        assert actual == expected, (
            f"N50: expected {expected}, got {actual}"
        )

    def test_l50(self, report):
        actual = report["assembly_stats"]["l50"]
        expected = EXPECTED_ASSEMBLY_STATS["l50"]
        assert actual == expected, (
            f"L50: expected {expected}, got {actual}"
        )

    def test_aun(self, report):
        actual = report["assembly_stats"]["aun"]
        expected = EXPECTED_ASSEMBLY_STATS["aun"]
        assert abs(actual - expected) < TOL, (
            f"auN: expected {expected}, got {actual}"
        )

    def test_gc_content(self, report):
        actual = report["assembly_stats"]["gc_content"]
        expected = EXPECTED_ASSEMBLY_STATS["gc_content"]
        assert abs(actual - expected) < TOL, (
            f"GC content: expected {expected}, got {actual}"
        )
