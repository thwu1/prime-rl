
"""Tests for the genomic relatedness and variant analysis pipeline."""

import os
import pytest

RESULTS_DIR = "/app/results"

# Ground truth kinship values (deterministic from seed 20240315)
EXPECTED_KINSHIP = {
    ("S1", "S2"): -0.051282,
    ("S1", "S3"): 0.227848,
    ("S1", "S4"): 0.278481,
    ("S1", "S5"): 0.031646,
    ("S1", "S6"): 0.139241,
    ("S2", "S3"): 0.243590,
    ("S2", "S4"): -0.044872,
    ("S2", "S5"): -0.025641,
    ("S2", "S6"): -0.006410,
    ("S3", "S4"): 0.142857,
    ("S3", "S5"): 0.041667,
    ("S3", "S6"): 0.077381,
    ("S4", "S5"): 0.034884,
    ("S4", "S6"): 0.244186,
    ("S5", "S6"): 0.281609,
}

EXPECTED_IBS0 = {
    ("S1", "S2"): 23,
    ("S1", "S3"): 0,
    ("S1", "S4"): 4,
    ("S1", "S5"): 16,
    ("S1", "S6"): 8,
    ("S2", "S3"): 0,
    ("S2", "S4"): 20,
    ("S2", "S5"): 21,
    ("S2", "S6"): 18,
    ("S3", "S4"): 8,
    ("S3", "S5"): 15,
    ("S3", "S6"): 15,
    ("S4", "S5"): 15,
    ("S4", "S6"): 0,
    ("S5", "S6"): 0,
}

# De novo variants (with correct pedigree: S1+S2 -> S3)
EXPECTED_DENOVO = {
    ("chr5", 51000, "A", "G"),
    ("chr5", 63500, "C", "T"),
    ("chr5", 76000, "G", "A"),
}

# Compound het pair
EXPECTED_COMPOUND_HET = {
    ("DISEASE_GENE_A", "chr2", 26000, "chr2", 38500),
}


class TestKinship:
    """Test pairwise kinship computation."""

    def test_kinship_file_exists(self):
        path = os.path.join(RESULTS_DIR, "kinship.tsv")
        assert os.path.isfile(path), "kinship.tsv not found"

    def test_kinship_has_header(self):
        path = os.path.join(RESULTS_DIR, "kinship.tsv")
        with open(path) as f:
            header = f.readline().strip().split("\t")
        assert "sample_1" in header
        assert "sample_2" in header
        assert "kinship" in header

    def test_kinship_has_15_pairs(self):
        path = os.path.join(RESULTS_DIR, "kinship.tsv")
        with open(path) as f:
            lines = [l for l in f.readlines() if l.strip() and not l.startswith("#")]
        # Subtract header
        data_lines = [l for l in lines if not l.strip().startswith("sample_1")]
        assert len(data_lines) == 15, f"Expected 15 pairs, got {len(data_lines)}"

    def test_kinship_values_correct(self):
        path = os.path.join(RESULTS_DIR, "kinship.tsv")
        parsed = {}
        with open(path) as f:
            header = None
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if header is None:
                    header = parts
                    continue
                s1_idx = header.index("sample_1")
                s2_idx = header.index("sample_2")
                k_idx = header.index("kinship")
                s1, s2 = parts[s1_idx], parts[s2_idx]
                # Normalize order
                pair = tuple(sorted([s1, s2]))
                parsed[pair] = float(parts[k_idx])

        for pair, expected_k in EXPECTED_KINSHIP.items():
            assert pair in parsed, f"Missing pair {pair}"
            actual_k = parsed[pair]
            assert abs(actual_k - expected_k) < 0.001, (
                f"Kinship for {pair}: expected {expected_k:.6f}, got {actual_k:.6f}"
            )

    def test_ibs0_values_correct(self):
        path = os.path.join(RESULTS_DIR, "kinship.tsv")
        parsed = {}
        with open(path) as f:
            header = None
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if header is None:
                    header = parts
                    continue
                s1_idx = header.index("sample_1")
                s2_idx = header.index("sample_2")
                ibs0_idx = header.index("ibs0")
                s1, s2 = parts[s1_idx], parts[s2_idx]
                pair = tuple(sorted([s1, s2]))
                parsed[pair] = int(parts[ibs0_idx])

        for pair, expected_ibs0 in EXPECTED_IBS0.items():
            assert pair in parsed, f"Missing pair {pair}"
            assert parsed[pair] == expected_ibs0, (
                f"IBS0 for {pair}: expected {expected_ibs0}, got {parsed[pair]}"
            )

    def test_parent_child_ibs0_zero(self):
        """Parent-child pairs must have IBS0=0 (Mendelian constraint)."""
        path = os.path.join(RESULTS_DIR, "kinship.tsv")
        parsed = {}
        with open(path) as f:
            header = None
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if header is None:
                    header = parts
                    continue
                s1_idx = header.index("sample_1")
                s2_idx = header.index("sample_2")
                ibs0_idx = header.index("ibs0")
                s1, s2 = parts[s1_idx], parts[s2_idx]
                pair = tuple(sorted([s1, s2]))
                parsed[pair] = int(parts[ibs0_idx])

        # True parent-child pairs (with correct pedigree)
        parent_child_pairs = [("S1", "S3"), ("S2", "S3"), ("S4", "S6"), ("S5", "S6")]
        for pair in parent_child_pairs:
            assert parsed[pair] == 0, (
                f"IBS0 for parent-child pair {pair} should be 0, got {parsed[pair]}"
            )


class TestSwapDetection:
    """Test sample swap detection."""

    def test_swapped_file_exists(self):
        path = os.path.join(RESULTS_DIR, "swapped_samples.txt")
        assert os.path.isfile(path), "swapped_samples.txt not found"

    def test_swapped_samples_correct(self):
        path = os.path.join(RESULTS_DIR, "swapped_samples.txt")
        with open(path) as f:
            content = f.read().strip()
        samples = sorted(content.split())
        assert samples == ["S2", "S5"], (
            f"Expected swapped samples ['S2', 'S5'], got {samples}"
        )


class TestCorrectedPedigree:
    """Test corrected pedigree file."""

    def test_corrected_ped_exists(self):
        path = os.path.join(RESULTS_DIR, "corrected.ped")
        assert os.path.isfile(path), "corrected.ped not found"

    def test_s3_mother_is_s2(self):
        """S3's mother should be S2 (not S5)."""
        path = os.path.join(RESULTS_DIR, "corrected.ped")
        found = False
        with open(path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 4 and parts[1] == "S3":
                    assert parts[3] == "S2", (
                        f"S3 maternal_id should be S2, got {parts[3]}"
                    )
                    found = True
        assert found, "S3 not found in corrected pedigree"

    def test_s6_mother_is_s5(self):
        """S6's mother should be S5 (not S2)."""
        path = os.path.join(RESULTS_DIR, "corrected.ped")
        found = False
        with open(path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 4 and parts[1] == "S6":
                    assert parts[3] == "S5", (
                        f"S6 maternal_id should be S5, got {parts[3]}"
                    )
                    found = True
        assert found, "S6 not found in corrected pedigree"

    def test_s3_father_is_s1(self):
        """S3's father should remain S1."""
        path = os.path.join(RESULTS_DIR, "corrected.ped")
        with open(path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 4 and parts[1] == "S3":
                    assert parts[2] == "S1", (
                        f"S3 paternal_id should be S1, got {parts[2]}"
                    )

    def test_s6_father_is_s4(self):
        """S6's father should remain S4."""
        path = os.path.join(RESULTS_DIR, "corrected.ped")
        with open(path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 4 and parts[1] == "S6":
                    assert parts[2] == "S4", (
                        f"S6 paternal_id should be S4, got {parts[2]}"
                    )

    def test_corrected_ped_has_6_samples(self):
        path = os.path.join(RESULTS_DIR, "corrected.ped")
        count = 0
        with open(path) as f:
            for line in f:
                if line.strip() and not line.startswith("#"):
                    count += 1
        assert count == 6, f"Expected 6 samples in corrected pedigree, got {count}"

    def test_mothers_in_correct_families(self):
        """S2 should be in FAM1, S5 should be in FAM2."""
        path = os.path.join(RESULTS_DIR, "corrected.ped")
        family_map = {}
        with open(path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 2:
                    family_map[parts[1]] = parts[0]
        assert family_map.get("S2") == "FAM1", (
            f"S2 should be in FAM1, got {family_map.get('S2')}"
        )
        assert family_map.get("S5") == "FAM2", (
            f"S5 should be in FAM2, got {family_map.get('S5')}"
        )


class TestDeNovo:
    """Test de novo variant detection."""

    def test_denovo_file_exists(self):
        path = os.path.join(RESULTS_DIR, "denovo.tsv")
        assert os.path.isfile(path), "denovo.tsv not found"

    def test_denovo_count(self):
        path = os.path.join(RESULTS_DIR, "denovo.tsv")
        variants = set()
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("chrom"):
                    continue
                parts = line.split("\t")
                variants.add((parts[0], int(parts[1]), parts[2], parts[3]))
        assert len(variants) == 3, f"Expected 3 de novo variants, got {len(variants)}"

    def test_denovo_variants_correct(self):
        path = os.path.join(RESULTS_DIR, "denovo.tsv")
        variants = set()
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("chrom"):
                    continue
                parts = line.split("\t")
                variants.add((parts[0], int(parts[1]), parts[2], parts[3]))
        assert variants == EXPECTED_DENOVO, (
            f"De novo variants mismatch.\nExpected: {EXPECTED_DENOVO}\nGot: {variants}"
        )


class TestCompoundHets:
    """Test compound heterozygote detection."""

    def test_compound_hets_file_exists(self):
        path = os.path.join(RESULTS_DIR, "compound_hets.tsv")
        assert os.path.isfile(path), "compound_hets.tsv not found"

    def test_compound_hets_count(self):
        path = os.path.join(RESULTS_DIR, "compound_hets.tsv")
        pairs = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("gene"):
                    continue
                pairs.append(line)
        assert len(pairs) == 1, f"Expected 1 compound het pair, got {len(pairs)}"

    def test_compound_hets_correct(self):
        path = os.path.join(RESULTS_DIR, "compound_hets.tsv")
        pairs = set()
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("gene"):
                    continue
                parts = line.split("\t")
                gene = parts[0]
                chrom1, pos1 = parts[1], int(parts[2])
                chrom2, pos2 = parts[3], int(parts[4])
                # Normalize order
                if (chrom1, pos1) > (chrom2, pos2):
                    chrom1, pos1, chrom2, pos2 = chrom2, pos2, chrom1, pos1
                pairs.add((gene, chrom1, pos1, chrom2, pos2))
        assert pairs == EXPECTED_COMPOUND_HET, (
            f"Compound het mismatch.\nExpected: {EXPECTED_COMPOUND_HET}\nGot: {pairs}"
        )
