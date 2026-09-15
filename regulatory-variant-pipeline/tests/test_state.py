#!/usr/bin/env python3
"""
Tests for regulatory variant identification pipeline.
Independently re-derives the correct answer from backed-up original data.
"""

import os
import subprocess
import pytest

BACKUP = "/app/.data_backup"
RESULTS = "/app/results"
WORK = "/tmp/test_ref"


def run(cmd):
    """Run a shell command, assert success, return stdout."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    assert r.returncode == 0, f"Reference pipeline command failed: {cmd}\nstderr: {r.stderr}"
    return r.stdout.strip()


@pytest.fixture(scope="session")
def reference():
    """Compute the reference answer from original backed-up data."""
    os.makedirs(WORK, exist_ok=True)

    # 1. Fix variant chromosome naming: add "chr" prefix, sort, deduplicate
    run(
        f'awk \'BEGIN{{OFS="\\t"}}{{$1="chr"$1; print}}\' {BACKUP}/variants.bed'
        f" | sort -k1,1 -k2,2n | uniq > {WORK}/var.bed"
    )

    # 2. Convert enhancers from GFF3 (1-based) to BED (0-based)
    run(
        f"grep -v '^#' {BACKUP}/enhancers.gff"
        f' | awk \'BEGIN{{OFS="\\t"}}{{print $1, $4-1, $5}}\''
        f" | sort -k1,1 -k2,2n > {WORK}/enh.bed"
    )

    # 3. Sort CpG islands
    run(f"sort -k1,1 -k2,2n {BACKUP}/cpg_islands.bed > {WORK}/cpg.bed")

    # 4. Combine promoters (BED3) + enhancers, sort, merge
    run(f"cut -f1-3 {BACKUP}/promoters.bed > {WORK}/prom3.bed")
    run(
        f"cat {WORK}/prom3.bed {WORK}/enh.bed"
        f" | sort -k1,1 -k2,2n | bedtools merge -i - > {WORK}/reg.bed"
    )

    # 5. Intersect with CpG islands
    run(f"bedtools intersect -a {WORK}/reg.bed -b {WORK}/cpg.bed > {WORK}/rc.bed")

    # 6. Subtract repeat elements
    run(f"bedtools subtract -a {WORK}/rc.bed -b {BACKUP}/repeats.bed > {WORK}/rcnr.bed")

    # 7. Identify expressed genes (FPKM >= 10)
    run(
        f"awk -F'\\t' 'NR>1 && $2+0>=10{{print $1}}' {BACKUP}/expression.tsv"
        f" > {WORK}/enames.txt"
    )
    run(
        f"awk 'NR==FNR{{g[$1];next}} $4 in g' {WORK}/enames.txt {BACKUP}/genes.bed"
        f" | sort -k1,1 -k2,2n > {WORK}/egenes.bed"
    )

    # 8. Extend expressed genes by 2000bp, merge overlapping neighborhoods
    run(
        f"bedtools slop -i {WORK}/egenes.bed -g {BACKUP}/genome.txt -b 2000"
        f" | sort -k1,1 -k2,2n | bedtools merge -i - > {WORK}/enbhd.bed"
    )

    # 9. Active regulatory regions = (reg ∩ cpg - repeats) ∩ expressed neighborhoods
    run(
        f"bedtools intersect -a {WORK}/rcnr.bed -b {WORK}/enbhd.bed"
        f" | sort -k1,1 -k2,2n | bedtools merge -i - > {WORK}/active.bed"
    )

    # 10. Find regulatory variants
    run(
        f"bedtools intersect -a {WORK}/var.bed -b {WORK}/active.bed -u"
        f" | sort -k1,1 -k2,2n > {WORK}/regvar.bed"
    )

    # Compute reference statistics
    ref = {}
    ref["reg_var_count"] = int(run(f"wc -l < {WORK}/regvar.bed"))
    ref["total_var_count"] = int(run(f"wc -l < {WORK}/var.bed"))
    ref["active_count"] = int(run(f"wc -l < {WORK}/active.bed"))
    ref["active_bp"] = int(run(
        f"awk '{{s+=$3-$2}}END{{print s+0}}' {WORK}/active.bed"
    ))
    ref["regvar_bed3"] = run(f"sort -k1,1 -k2,2n {WORK}/regvar.bed | cut -f1-3")
    ref["active_bed3"] = run(f"sort -k1,1 -k2,2n {WORK}/active.bed | cut -f1-3")

    # Sanity checks on reference
    assert ref["reg_var_count"] > 0, "Reference pipeline found 0 regulatory variants"
    assert ref["active_count"] > 0, "Reference pipeline found 0 active regions"
    assert ref["total_var_count"] > ref["reg_var_count"], \
        "Reference: all variants are regulatory (unexpected)"

    return ref


class TestOutputFilesExist:
    def test_regulatory_variants_exists(self):
        assert os.path.isfile(f"{RESULTS}/regulatory_variants.bed"), \
            "Missing /app/results/regulatory_variants.bed"

    def test_active_regions_exists(self):
        assert os.path.isfile(f"{RESULTS}/active_regions.bed"), \
            "Missing /app/results/active_regions.bed"

    def test_summary_exists(self):
        assert os.path.isfile(f"{RESULTS}/summary.txt"), \
            "Missing /app/results/summary.txt"


class TestActiveRegions:
    def test_content_matches_reference(self, reference):
        result = run(
            f"sort -k1,1 -k2,2n {RESULTS}/active_regions.bed | cut -f1-3"
        )
        assert result == reference["active_bed3"], \
            f"Active regions mismatch.\nGot:\n{result}\nExpected:\n{reference['active_bed3']}"

    def test_is_sorted(self):
        r = subprocess.run(
            f"sort -k1,1 -k2,2n -c {RESULTS}/active_regions.bed",
            shell=True, capture_output=True, text=True,
        )
        assert r.returncode == 0, "active_regions.bed is not sorted"

    def test_uses_chr_prefix(self):
        with open(f"{RESULTS}/active_regions.bed") as f:
            for i, line in enumerate(f, 1):
                if line.strip():
                    assert line.startswith("chr"), \
                        f"Line {i} missing chr prefix: {line.strip()}"


class TestRegulatoryVariants:
    def test_content_matches_reference(self, reference):
        result = run(
            f"sort -k1,1 -k2,2n {RESULTS}/regulatory_variants.bed | cut -f1-3"
        )
        assert result == reference["regvar_bed3"], \
            f"Regulatory variants mismatch.\nGot:\n{result}\nExpected:\n{reference['regvar_bed3']}"

    def test_is_sorted(self):
        r = subprocess.run(
            f"sort -k1,1 -k2,2n -c {RESULTS}/regulatory_variants.bed",
            shell=True, capture_output=True, text=True,
        )
        assert r.returncode == 0, "regulatory_variants.bed is not sorted"

    def test_no_duplicates(self):
        total = int(run(f"wc -l < {RESULTS}/regulatory_variants.bed"))
        unique = int(run(
            f"sort -k1,1 -k2,2n {RESULTS}/regulatory_variants.bed | uniq | wc -l"
        ))
        assert total == unique, \
            f"Found duplicates: {total} total lines vs {unique} unique"

    def test_uses_chr_prefix(self):
        with open(f"{RESULTS}/regulatory_variants.bed") as f:
            for i, line in enumerate(f, 1):
                if line.strip():
                    assert line.startswith("chr"), \
                        f"Line {i} missing chr prefix: {line.strip()}"


class TestSummaryValues:
    def _parse_summary(self):
        d = {}
        with open(f"{RESULTS}/summary.txt") as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip()
        return d

    def test_regulatory_variant_count(self, reference):
        s = self._parse_summary()
        assert "regulatory_variant_count" in s, \
            "Missing regulatory_variant_count in summary.txt"
        assert int(s["regulatory_variant_count"]) == reference["reg_var_count"], \
            f"regulatory_variant_count: got {s['regulatory_variant_count']}, " \
            f"expected {reference['reg_var_count']}"

    def test_total_variant_count(self, reference):
        s = self._parse_summary()
        assert "total_variant_count" in s, \
            "Missing total_variant_count in summary.txt"
        assert int(s["total_variant_count"]) == reference["total_var_count"], \
            f"total_variant_count: got {s['total_variant_count']}, " \
            f"expected {reference['total_var_count']}"

    def test_active_region_count(self, reference):
        s = self._parse_summary()
        assert "active_region_count" in s, \
            "Missing active_region_count in summary.txt"
        assert int(s["active_region_count"]) == reference["active_count"], \
            f"active_region_count: got {s['active_region_count']}, " \
            f"expected {reference['active_count']}"

    def test_active_region_total_bp(self, reference):
        s = self._parse_summary()
        assert "active_region_total_bp" in s, \
            "Missing active_region_total_bp in summary.txt"
        assert int(s["active_region_total_bp"]) == reference["active_bp"], \
            f"active_region_total_bp: got {s['active_region_total_bp']}, " \
            f"expected {reference['active_bp']}"

    def test_fraction_regulatory(self, reference):
        s = self._parse_summary()
        assert "fraction_regulatory" in s, \
            "Missing fraction_regulatory in summary.txt"
        val = float(s["fraction_regulatory"])
        expected = reference["reg_var_count"] / reference["total_var_count"]
        assert abs(val - expected) < 0.001, \
            f"fraction_regulatory: got {val}, expected {expected:.4f}"
