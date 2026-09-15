"""Tests for CNV detection pipeline outputs.

"""
import csv
import gzip
import os

import pytest

OUTPUT_DIR = "/app/output"
WIN_SIZE = 1_000_000

TUMOR_SAMPLES = ["T1", "T2", "T3", "T4", "T5", "T6"]

# Ground truth: major CNV events that must be detected
# Format: (sample, chromosome, approx_start_mb, approx_end_mb, direction)
EXPECTED_EVENTS = [
    ("T1", "chr1", 20, 35, "loss"),
    ("T1", "chr3", 45, 70, "gain"),
    ("T2", "chr1", 18, 38, "loss"),
    ("T2", "chr3", 50, 68, "gain"),
    ("T3", "chr2", 75, 95, "gain"),
    ("T4", "chr3", 42, 72, "gain"),
    ("T4", "chr5", 10, 30, "loss"),
    ("T5", "chr1", 22, 33, "loss"),
    ("T6", "chr3", 48, 65, "gain"),
    ("T6", "chr4", 25, 50, "loss"),
]

RECURRENT_LOSS_MIN_SAMPLES = 3
RECURRENT_GAIN_MIN_SAMPLES = 3

EXPECTED_LOSS_GENES = {"RB1", "CDKN2A"}
EXPECTED_GAIN_GENES = {"CCND1", "FGFR1", "MYB", "FGF19", "CCNE1"}

TRUE_PURITIES = {
    "T1": 0.80, "T2": 0.60, "T3": 0.90,
    "T4": 0.70, "T5": 0.50, "T6": 0.75,
}
PURITY_TOLERANCE = 0.15
MIN_ACCURATE_PURITY = 4


def is_loss_type(t):
    return t.lower().strip() in ("loss", "deletion", "del")


def is_gain_type(t):
    return t.lower().strip() in ("gain", "amplification", "amp")


def read_csv_file(path):
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        return list(reader)


class TestOutputFiles:
    def test_cnv_segments_exists(self):
        path = os.path.join(OUTPUT_DIR, "cnv_segments.csv")
        assert os.path.isfile(path), f"Missing {path}"

    def test_recurrent_regions_exists(self):
        path = os.path.join(OUTPUT_DIR, "recurrent_regions.csv")
        assert os.path.isfile(path), f"Missing {path}"

    def test_affected_genes_exists(self):
        path = os.path.join(OUTPUT_DIR, "affected_genes.csv")
        assert os.path.isfile(path), f"Missing {path}"

    def test_purity_estimates_exists(self):
        path = os.path.join(OUTPUT_DIR, "purity_estimates.csv")
        assert os.path.isfile(path), f"Missing {path}"


class TestBEDOutputs:
    """Tests for BED-format outputs and bedtools-generated artifacts."""

    def test_per_sample_bed_files_exist(self):
        """Each tumor sample must have a per-sample BED file."""
        for sample in TUMOR_SAMPLES:
            path = f"{OUTPUT_DIR}/per_sample/{sample}.bed"
            assert os.path.isfile(path), f"Missing per-sample BED: {path}"

    def test_bed_format_valid(self):
        """BED files must be tab-delimited with >= 5 columns and valid coords."""
        for sample in TUMOR_SAMPLES:
            path = f"{OUTPUT_DIR}/per_sample/{sample}.bed"
            with open(path) as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]
            if not lines:
                continue
            for i, line in enumerate(lines):
                fields = line.split("\t")
                assert len(fields) >= 5, (
                    f"{sample}.bed line {i}: expected >= 5 tab-separated fields, "
                    f"got {len(fields)}"
                )
                start, end = int(fields[1]), int(fields[2])
                assert start < end, (
                    f"{sample}.bed line {i}: invalid coordinates {start} >= {end}"
                )

    def test_bed_files_sorted(self):
        """BED files must be coordinate-sorted within each chromosome."""
        for sample in TUMOR_SAMPLES:
            path = f"{OUTPUT_DIR}/per_sample/{sample}.bed"
            prev_chrom = ""
            prev_start = -1
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    fields = line.split("\t")
                    chrom = fields[0]
                    start = int(fields[1])
                    if chrom != prev_chrom:
                        prev_chrom = chrom
                        prev_start = -1
                    assert start >= prev_start, (
                        f"{sample}.bed: unsorted - {chrom}:{start} after "
                        f"{chrom}:{prev_start}"
                    )
                    prev_start = start

    def test_combined_bed_gz_exists(self):
        """Combined bgzip-compressed BED must exist."""
        path = f"{OUTPUT_DIR}/all_cnv_segments.bed.gz"
        assert os.path.isfile(path), f"Missing combined bgzipped BED: {path}"

    def test_tabix_index_exists(self):
        """Tabix index (.tbi) must exist alongside the bgzipped BED."""
        path = f"{OUTPUT_DIR}/all_cnv_segments.bed.gz.tbi"
        assert os.path.isfile(path), f"Missing tabix index: {path}"

    def test_combined_bed_readable(self):
        """The bgzipped file must contain valid, non-empty BED records."""
        path = f"{OUTPUT_DIR}/all_cnv_segments.bed.gz"
        with gzip.open(path, "rt") as f:
            lines = [l for l in f if l.strip() and not l.startswith("#")]
        assert len(lines) > 0, "Combined BED file is empty"
        for line in lines[:10]:
            fields = line.strip().split("\t")
            assert len(fields) >= 3, f"Invalid BED line: {line.strip()}"
            int(fields[1])
            int(fields[2])


class TestCNVSegments:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.segments = read_csv_file(os.path.join(OUTPUT_DIR, "cnv_segments.csv"))

    def test_required_columns(self):
        required = {"sample", "chromosome", "start", "end", "log2_ratio", "copy_number"}
        actual = set(self.segments[0].keys()) if self.segments else set()
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_has_data(self):
        assert len(self.segments) > 0, "No CNV segments found"

    def test_segments_have_valid_coordinates(self):
        for seg in self.segments:
            assert int(seg["start"]) < int(seg["end"]), (
                f"Invalid coordinates: start={seg['start']} >= end={seg['end']}"
            )

    def test_copy_numbers_are_valid(self):
        for seg in self.segments:
            cn = float(seg["copy_number"])
            assert 0 <= cn <= 10, f"Invalid copy number: {cn}"

    def _find_overlapping_segments(self, sample, chrom, start_mb, end_mb):
        matching = []
        for seg in self.segments:
            if seg["sample"] != sample or seg["chromosome"] != chrom:
                continue
            seg_start = int(seg["start"]) / WIN_SIZE
            seg_end = int(seg["end"]) / WIN_SIZE
            if seg_start < end_mb and seg_end > start_mb:
                matching.append(seg)
        return matching

    def test_major_events_detected(self):
        """At least 70% of major CNV events should be detected."""
        detected = 0
        for sample, chrom, start_mb, end_mb, direction in EXPECTED_EVENTS:
            overlapping = self._find_overlapping_segments(
                sample, chrom, start_mb, end_mb
            )
            if not overlapping:
                continue
            cn_values = [float(s["copy_number"]) for s in overlapping]
            mean_cn = sum(cn_values) / len(cn_values)
            if direction == "loss" and mean_cn < 2.0:
                detected += 1
            elif direction == "gain" and mean_cn > 2.0:
                detected += 1

        sensitivity = detected / len(EXPECTED_EVENTS)
        assert sensitivity >= 0.7, (
            f"Only {detected}/{len(EXPECTED_EVENTS)} events detected "
            f"(sensitivity={sensitivity:.2f}, need >=0.70)"
        )

    def test_chr1_deletions_detected(self):
        """T1, T2, T5 should have chr1 deletions."""
        for sample in ["T1", "T2", "T5"]:
            overlapping = self._find_overlapping_segments(sample, "chr1", 20, 35)
            assert len(overlapping) > 0, f"chr1 deletion not found in {sample}"
            cn_values = [float(s["copy_number"]) for s in overlapping]
            mean_cn = sum(cn_values) / len(cn_values)
            assert mean_cn < 2.0, (
                f"chr1 region in {sample} has CN={mean_cn:.1f}, expected < 2"
            )

    def test_chr3_gains_detected(self):
        """T1, T4, T6 should have chr3 gains."""
        for sample in ["T1", "T4", "T6"]:
            overlapping = self._find_overlapping_segments(sample, "chr3", 45, 70)
            assert len(overlapping) > 0, f"chr3 gain not found in {sample}"
            cn_values = [float(s["copy_number"]) for s in overlapping]
            mean_cn = sum(cn_values) / len(cn_values)
            assert mean_cn > 2.0, (
                f"chr3 region in {sample} has CN={mean_cn:.1f}, expected > 2"
            )


class TestRecurrentRegions:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.regions = read_csv_file(
            os.path.join(OUTPUT_DIR, "recurrent_regions.csv")
        )

    def test_required_columns(self):
        required = {"chromosome", "start", "end", "n_samples", "type"}
        actual = set(self.regions[0].keys()) if self.regions else set()
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_has_recurrent_regions(self):
        assert len(self.regions) >= 2, (
            f"Expected at least 2 recurrent regions, found {len(self.regions)}"
        )

    def test_chr1_recurrent_loss(self):
        """chr1 should have a recurrently deleted region covering ~20-35 Mb."""
        chr1_losses = [
            r for r in self.regions
            if r["chromosome"] == "chr1" and is_loss_type(r["type"])
        ]
        assert len(chr1_losses) > 0, "No recurrent loss found on chr1"
        found = False
        for r in chr1_losses:
            start_mb = int(r["start"]) / WIN_SIZE
            end_mb = int(r["end"]) / WIN_SIZE
            n = int(r["n_samples"])
            if start_mb <= 25 and end_mb >= 30 and n >= RECURRENT_LOSS_MIN_SAMPLES:
                found = True
        assert found, (
            "chr1 recurrent loss region doesn't span expected coordinates "
            "or doesn't meet minimum sample count"
        )

    def test_chr3_recurrent_gain(self):
        """chr3 should have a recurrently amplified region covering ~45-70 Mb."""
        chr3_gains = [
            r for r in self.regions
            if r["chromosome"] == "chr3" and is_gain_type(r["type"])
        ]
        assert len(chr3_gains) > 0, "No recurrent gain found on chr3"
        found = False
        for r in chr3_gains:
            start_mb = int(r["start"]) / WIN_SIZE
            end_mb = int(r["end"]) / WIN_SIZE
            n = int(r["n_samples"])
            if start_mb <= 55 and end_mb >= 60 and n >= RECURRENT_GAIN_MIN_SAMPLES:
                found = True
        assert found, (
            "chr3 recurrent gain region doesn't span expected coordinates "
            "or doesn't meet minimum sample count"
        )


class TestAffectedGenes:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.genes = read_csv_file(os.path.join(OUTPUT_DIR, "affected_genes.csv"))

    def test_required_columns(self):
        required = {"gene", "chromosome", "region_type", "n_samples"}
        actual = set(self.genes[0].keys()) if self.genes else set()
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_has_affected_genes(self):
        assert len(self.genes) >= 3, (
            f"Expected at least 3 affected genes, found {len(self.genes)}"
        )

    def test_key_loss_genes(self):
        """RB1 and/or CDKN2A should appear (chr1 recurrent deletion)."""
        gene_names = {g["gene"] for g in self.genes}
        found = EXPECTED_LOSS_GENES & gene_names
        assert len(found) >= 1, (
            f"Expected at least 1 of {EXPECTED_LOSS_GENES} in affected genes, "
            f"found none"
        )

    def test_key_gain_genes(self):
        """At least 3 chr3 oncogenes should appear (chr3 recurrent gain)."""
        gene_names = {g["gene"] for g in self.genes}
        found = EXPECTED_GAIN_GENES & gene_names
        assert len(found) >= 3, (
            f"Expected at least 3 of {EXPECTED_GAIN_GENES} in affected genes, "
            f"found only {found}"
        )

    def test_gene_sample_counts(self):
        """Affected genes should have n_samples >= 2."""
        for g in self.genes:
            n = int(g["n_samples"])
            assert n >= 2, f"Gene {g['gene']} has n_samples={n}, expected >= 2"


class TestPurityEstimates:
    @pytest.fixture(autouse=True)
    def load_data(self):
        self.estimates = read_csv_file(
            os.path.join(OUTPUT_DIR, "purity_estimates.csv")
        )

    def test_required_columns(self):
        required = {"sample", "purity"}
        actual = set(self.estimates[0].keys()) if self.estimates else set()
        missing = required - actual
        assert not missing, f"Missing columns: {missing}"

    def test_all_tumor_samples_present(self):
        """All 6 tumor samples must have purity estimates."""
        samples = {e["sample"] for e in self.estimates}
        for s in TUMOR_SAMPLES:
            assert s in samples, f"Missing purity estimate for {s}"

    def test_purity_values_valid(self):
        """Purity values must be in (0, 1]."""
        for e in self.estimates:
            p = float(e["purity"])
            assert 0.0 < p <= 1.0, (
                f"Invalid purity for {e['sample']}: {p}, must be in (0, 1]"
            )

    def test_purity_accuracy(self):
        """At least 4 of 6 purity estimates must be within tolerance."""
        est_map = {e["sample"]: float(e["purity"]) for e in self.estimates}
        accurate = 0
        details = []
        for sample, true_p in TRUE_PURITIES.items():
            est_p = est_map.get(sample)
            if est_p is not None and abs(est_p - true_p) <= PURITY_TOLERANCE:
                accurate += 1
                details.append(f"{sample}: est={est_p:.3f} true={true_p:.2f} OK")
            else:
                details.append(
                    f"{sample}: est={est_p:.3f} true={true_p:.2f} "
                    f"err={abs(est_p - true_p):.3f}" if est_p else
                    f"{sample}: MISSING"
                )
        assert accurate >= MIN_ACCURATE_PURITY, (
            f"Only {accurate}/{len(TRUE_PURITIES)} purity estimates within "
            f"tolerance {PURITY_TOLERANCE}. Details: {'; '.join(details)}"
        )
