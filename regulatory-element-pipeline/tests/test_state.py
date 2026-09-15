#!/usr/bin/env python3
"""Tests for the genomic pipeline multi-defect data audit task.

Tests create corrected copies of input data and independently recompute
each expected output to verify the solver's results.
"""

import os
import random
import shutil
import subprocess
import pytest

DATA_DIR = "/app/data"
RESULTS_DIR = "/app/results"
FIXED_DIR = "/tmp/test_fixed_data"

# Ground-truth chromosome sizes (the genome.txt may be wrong)
CORRECT_GENOME = [
    ("chr1", 250000),
    ("chr2", 200000),
    ("chr3", 150000),
    ("chr4", 100000),
    ("chr5", 50000),
]


def run_cmd(cmd):
    """Run a shell command and return stripped stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def read_lines(path):
    """Read non-empty, stripped lines from a file."""
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def load_genome_correct():
    """Return correct genome sizes as dict."""
    return dict(CORRECT_GENOME)


@pytest.fixture(scope="session", autouse=True)
def setup_fixed_data():
    """Create corrected copies of input data for reference computation."""
    os.makedirs(FIXED_DIR, exist_ok=True)

    # Fix genome.txt — write correct chromosome sizes
    with open(os.path.join(FIXED_DIR, "genome.txt"), "w") as f:
        for name, size in CORRECT_GENOME:
            f.write(f"{name}\t{size}\n")

    # Fix genes.bed — normalize strand encoding ("1"->"+", "-1"->"-")
    with open(os.path.join(DATA_DIR, "genes.bed")) as fin:
        lines = fin.readlines()
    with open(os.path.join(FIXED_DIR, "genes.bed"), "w") as fout:
        for line in lines:
            fields = line.strip().split("\t")
            if len(fields) >= 6:
                if fields[5] == "1":
                    fields[5] = "+"
                elif fields[5] == "-1":
                    fields[5] = "-"
            fout.write("\t".join(fields) + "\n")

    # Regenerate correct CpG islands from scratch using the same RNG seed
    # as generate_data.py. This avoids depending on DATA_DIR state (the
    # solver may have already corrected the 1-based starts in-place).
    def _place_intervals(rng, chrom_size, n, min_sz, max_sz, margin,
                         min_gap=200, max_gap=2000):
        results = []
        pos = margin + rng.randint(0, min(500, margin))
        for _ in range(n):
            pos += rng.randint(min_gap, max_gap)
            if pos + min_sz >= chrom_size - margin:
                break
            sz = rng.randint(min_sz, max_sz)
            end = min(pos + sz, chrom_size - margin)
            if end <= pos:
                break
            results.append((pos, end))
            pos = end
        return results

    rng_cpg = random.Random(142)
    cpg_idx = 1
    with open(os.path.join(FIXED_DIR, "cpg_islands.bed"), "w") as fout:
        for chrom, chrom_size in CORRECT_GENOME:
            n = max(5, chrom_size // 10000)
            intervals = _place_intervals(rng_cpg, chrom_size, n, 200,
                                         1200, 200, 500, 3000)
            for start, end in intervals:
                fout.write(f"{chrom}\t{start}\t{end}\tCpG_{cpg_idx:03d}\n")
                cpg_idx += 1

    # Sort tfbs_C.bed (may be unsorted in the defective data)
    subprocess.run(
        f"sort -k1,1 -k2,2n {DATA_DIR}/tfbs_C.bed > "
        f"{FIXED_DIR}/tfbs_C.bed",
        shell=True, check=True,
    )

    # Fix tfbs_D.bed — normalize chromosome names to lowercase and sort
    with open(os.path.join(DATA_DIR, "tfbs_D.bed")) as fin:
        lines = fin.readlines()
    with open(os.path.join(FIXED_DIR, "tfbs_D.bed"), "w") as fout:
        for line in lines:
            fields = line.strip().split("\t")
            if len(fields) >= 1:
                fields[0] = fields[0].lower()
            fout.write("\t".join(fields) + "\n")
    subprocess.run(
        f"sort -k1,1 -k2,2n {FIXED_DIR}/tfbs_D.bed -o "
        f"{FIXED_DIR}/tfbs_D.bed",
        shell=True, check=True,
    )

    # Copy files that have no defects
    for fname in [
        "repeats.bed",
        "tfbs_A.bed", "tfbs_B.bed", "tfbs_E.bed",
    ]:
        shutil.copy(
            os.path.join(DATA_DIR, fname),
            os.path.join(FIXED_DIR, fname),
        )

    return FIXED_DIR


# ===================================================================
# 1. promoters.bed
# ===================================================================
class TestPromoters:
    def test_file_exists(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "promoters.bed"))

    def test_count_matches_genes(self):
        gene_count = len(read_lines(os.path.join(DATA_DIR, "genes.bed")))
        prom_count = len(
            read_lines(os.path.join(RESULTS_DIR, "promoters.bed")))
        assert prom_count == gene_count, \
            f"Expected {gene_count} promoters, got {prom_count}"

    def test_bed6_format(self):
        for line in read_lines(
                os.path.join(RESULTS_DIR, "promoters.bed")):
            fields = line.split("\t")
            assert len(fields) == 6, \
                f"Expected 6 columns, got {len(fields)}: {line}"
            assert int(fields[1]) >= 0, f"Negative start: {line}"
            assert int(fields[2]) > int(fields[1]), \
                f"End not > start: {line}"
            assert fields[5] in ("+", "-"), \
                f"Invalid strand '{fields[5]}': {line}"

    def test_strand_awareness(self):
        """+ strand: promoter ends at gene start.
        - strand: promoter starts at gene end.
        Uses corrected gene data for reference."""
        genes = {}
        for line in read_lines(os.path.join(FIXED_DIR, "genes.bed")):
            f = line.split("\t")
            genes[f[3]] = (f[0], int(f[1]), int(f[2]), f[5])

        for line in read_lines(
                os.path.join(RESULTS_DIR, "promoters.bed")):
            f = line.split("\t")
            gene_name = f[3]
            prom_start, prom_end = int(f[1]), int(f[2])
            strand = f[5]

            assert gene_name in genes, f"Unknown gene: {gene_name}"
            chrom, g_start, g_end, g_strand = genes[gene_name]
            assert strand == g_strand, \
                f"Strand mismatch for {gene_name}: " \
                f"got '{strand}', expected '{g_strand}'"

            if g_strand == "+":
                assert prom_end == g_start, (
                    f"{gene_name} (+): promoter end {prom_end} "
                    f"should equal gene start {g_start}")
            else:
                assert prom_start == g_end, (
                    f"{gene_name} (-): promoter start {prom_start} "
                    f"should equal gene end {g_end}")

    def test_within_chromosome_bounds(self):
        genome = load_genome_correct()
        for line in read_lines(
                os.path.join(RESULTS_DIR, "promoters.bed")):
            f = line.split("\t")
            assert int(f[1]) >= 0, f"Negative start: {line}"
            assert int(f[2]) <= genome[f[0]], \
                f"End exceeds chrom size: {line}"

    def test_promoter_size(self):
        """Promoter should be min(2000, distance_to_boundary) bp."""
        genome = load_genome_correct()
        genes = {}
        for line in read_lines(os.path.join(FIXED_DIR, "genes.bed")):
            f = line.split("\t")
            genes[f[3]] = (f[0], int(f[1]), int(f[2]), f[5])

        for line in read_lines(
                os.path.join(RESULTS_DIR, "promoters.bed")):
            f = line.split("\t")
            size = int(f[2]) - int(f[1])
            gene_name = f[3]
            chrom, g_start, g_end, g_strand = genes[gene_name]

            if g_strand == "+":
                expected = min(2000, g_start)
            else:
                expected = min(2000, genome[chrom] - g_end)

            assert size == expected, (
                f"{gene_name}: expected promoter size {expected}, "
                f"got {size}")


# ===================================================================
# 2. cpg_promoters_norepeats.bed
# ===================================================================
class TestCpgPromotersNorepeats:
    def test_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "cpg_promoters_norepeats.bed"))

    def test_overlaps_cpg(self):
        """Every output interval must overlap a corrected CpG island."""
        fpath = os.path.join(RESULTS_DIR, "cpg_promoters_norepeats.bed")
        if os.path.getsize(fpath) == 0:
            pytest.skip("Empty output file")
        count = int(run_cmd(
            f"bedtools intersect -a {fpath} "
            f"-b {FIXED_DIR}/cpg_islands.bed -u | wc -l"))
        total = int(run_cmd(f"wc -l < {fpath}"))
        assert count == total, \
            f"{total - count} intervals don't overlap CpG islands"

    def test_no_repeat_overlap(self):
        """No output interval may overlap a repeat."""
        fpath = os.path.join(RESULTS_DIR, "cpg_promoters_norepeats.bed")
        if os.path.getsize(fpath) == 0:
            pytest.skip("Empty output file")
        count = int(run_cmd(
            f"bedtools intersect -a {fpath} "
            f"-b {DATA_DIR}/repeats.bed -u | wc -l"))
        assert count == 0, f"{count} intervals overlap repeats"

    def test_within_promoters(self):
        """Every interval must lie within a corrected promoter region."""
        fpath = os.path.join(RESULTS_DIR, "cpg_promoters_norepeats.bed")
        if os.path.getsize(fpath) == 0:
            pytest.skip("Empty output file")
        run_cmd(
            f"bedtools flank -l 2000 -r 0 -s "
            f"-i {FIXED_DIR}/genes.bed -g {FIXED_DIR}/genome.txt "
            f"| sort -k1,1 -k2,2n "
            f"| bedtools merge -i - > /tmp/test_merged_proms.bed")
        outside = int(run_cmd(
            f"bedtools subtract -a {fpath} "
            f"-b /tmp/test_merged_proms.bed | wc -l"))
        assert outside == 0, \
            f"{outside} intervals are outside promoter regions"

    def test_matches_reference(self):
        """Base-pair-level match with independently computed result.

        Uses DATA_DIR CpG islands (solver-corrected in-place) for the
        pipeline recomputation.  Independent CpG correctness is verified
        by test_overlaps_cpg against RNG-regenerated FIXED_DIR data.
        """
        fpath = os.path.join(RESULTS_DIR, "cpg_promoters_norepeats.bed")
        # Compute reference promoters to a file (matching solver pipeline)
        run_cmd(
            f"bedtools flank -l 2000 -r 0 -s "
            f"-i {FIXED_DIR}/genes.bed -g {FIXED_DIR}/genome.txt "
            f"| sort -k1,1 -k2,2n > /tmp/test_ref_proms.bed")
        # Intersect with CpG, subtract repeats, sort, merge
        run_cmd(
            f"bedtools intersect "
            f"-a /tmp/test_ref_proms.bed "
            f"-b {DATA_DIR}/cpg_islands.bed "
            f"| bedtools subtract -a stdin "
            f"-b {DATA_DIR}/repeats.bed "
            f"| sort -k1,1 -k2,2n "
            f"| bedtools merge -i - > /tmp/test_ref_cpg_prom.bed")
        ref_lines = read_lines("/tmp/test_ref_cpg_prom.bed")
        act_lines = read_lines(fpath)
        if not ref_lines and not act_lines:
            return  # both empty is correct
        assert len(act_lines) > 0, "Output is empty but reference is not"
        assert len(ref_lines) > 0, "Reference is empty but output is not"
        # Normalize both to sorted BED3 and compare with diff
        run_cmd(
            f"cut -f1-3 {fpath} | sort -k1,1 -k2,2n "
            f"> /tmp/test_act_cpg_sorted.bed")
        run_cmd(
            f"cut -f1-3 /tmp/test_ref_cpg_prom.bed | sort -k1,1 -k2,2n "
            f"> /tmp/test_ref_cpg_sorted.bed")
        diff = run_cmd(
            "diff /tmp/test_act_cpg_sorted.bed "
            "/tmp/test_ref_cpg_sorted.bed")
        assert diff == "", (
            f"Output differs from reference "
            f"(solver: {len(act_lines)}, ref: {len(ref_lines)} "
            f"intervals):\n{diff[:500]}")


# ===================================================================
# 3. jaccard_matrix.tsv
# ===================================================================
class TestJaccardMatrix:
    def test_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "jaccard_matrix.tsv"))

    def test_format(self):
        lines = read_lines(
            os.path.join(RESULTS_DIR, "jaccard_matrix.tsv"))
        assert len(lines) == 6, \
            f"Expected 6 lines (header + 5 rows), got {len(lines)}"
        header = lines[0].split("\t")
        assert header == ["sample", "A", "B", "C", "D", "E"], \
            f"Wrong header: {header}"
        seen = set()
        for line in lines[1:]:
            fields = line.split("\t")
            assert len(fields) == 6, \
                f"Expected 6 columns, got {len(fields)}"
            assert fields[0] in ("A", "B", "C", "D", "E"), \
                f"Unknown sample: {fields[0]}"
            seen.add(fields[0])
            for v in fields[1:]:
                fv = float(v)
                assert 0 <= fv <= 1, f"Jaccard {fv} out of range"
        expected_samples = {"A", "B", "C", "D", "E"}
        assert seen == expected_samples, \
            "Missing samples: " + str(expected_samples - seen)

    def test_diagonal(self):
        """Diagonal entries must be 1.0."""
        lines = read_lines(
            os.path.join(RESULTS_DIR, "jaccard_matrix.tsv"))
        samples = ["A", "B", "C", "D", "E"]
        for line in lines[1:]:
            fields = line.split("\t")
            s = fields[0]
            idx = samples.index(s) + 1
            assert abs(float(fields[idx]) - 1.0) < 1e-4, (
                f"Diagonal for {s} should be 1.0, got {fields[idx]}")

    def test_symmetry(self):
        """Matrix must be symmetric."""
        lines = read_lines(
            os.path.join(RESULTS_DIR, "jaccard_matrix.tsv"))
        samples = ["A", "B", "C", "D", "E"]
        matrix = {}
        for line in lines[1:]:
            fields = line.split("\t")
            s1 = fields[0]
            for i, s2 in enumerate(samples):
                matrix[(s1, s2)] = float(fields[i + 1])
        for s1 in samples:
            for s2 in samples:
                assert abs(matrix[(s1, s2)] - matrix[(s2, s1)]) < 1e-4, (
                    f"Asymmetry: ({s1},{s2})={matrix[(s1, s2)]:.6f}, "
                    f"({s2},{s1})={matrix[(s2, s1)]:.6f}")

    def test_specific_values(self):
        """Spot-check Jaccard values against corrected TFBS files."""
        lines = read_lines(
            os.path.join(RESULTS_DIR, "jaccard_matrix.tsv"))
        samples = ["A", "B", "C", "D", "E"]
        matrix = {}
        for line in lines[1:]:
            fields = line.split("\t")
            s1 = fields[0]
            for i, s2 in enumerate(samples):
                matrix[(s1, s2)] = float(fields[i + 1])

        # Test pairs that exercise sort-order fix (C) and naming fix (D)
        pairs = [("A", "B"), ("C", "D"), ("A", "E"), ("B", "D")]
        for s1, s2 in pairs:
            f1 = os.path.join(FIXED_DIR, f"tfbs_{s1}.bed")
            f2 = os.path.join(FIXED_DIR, f"tfbs_{s2}.bed")
            out = run_cmd(
                f"bedtools jaccard -a {f1} -b {f2}")
            expected = float(out.split("\n")[1].split("\t")[2])
            assert abs(matrix[(s1, s2)] - expected) < 1e-4, (
                f"Jaccard({s1},{s2}): expected {expected:.6f}, "
                f"got {matrix[(s1, s2)]:.6f}")


# ===================================================================
# 4. tfbs_promoter_scores.tsv
# ===================================================================
class TestTfbsPromoterScores:
    def test_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "tfbs_promoter_scores.tsv"))

    def test_format(self):
        lines = read_lines(
            os.path.join(RESULTS_DIR, "tfbs_promoter_scores.tsv"))
        header = lines[0].split("\t")
        assert header == ["gene", "A", "B", "C", "D", "E"], \
            f"Wrong header: {header}"
        gene_count = len(read_lines(os.path.join(DATA_DIR, "genes.bed")))
        assert len(lines) == gene_count + 1, (
            f"Expected {gene_count + 1} lines, got {len(lines)}")

    def test_sorted_by_gene(self):
        lines = read_lines(
            os.path.join(RESULTS_DIR, "tfbs_promoter_scores.tsv"))
        gene_names = [l.split("\t")[0] for l in lines[1:]]
        assert gene_names == sorted(gene_names), \
            "Genes not sorted alphabetically"

    def test_values_non_negative(self):
        lines = read_lines(
            os.path.join(RESULTS_DIR, "tfbs_promoter_scores.tsv"))
        for line in lines[1:]:
            fields = line.split("\t")
            for v in fields[1:]:
                assert float(v) >= 0, f"Negative score in: {line}"

    def test_spot_check_tf_a(self):
        """Verify TF_A scores via independent bedtools map
        using corrected promoters."""
        run_cmd(
            f"bedtools flank -l 2000 -r 0 -s "
            f"-i {FIXED_DIR}/genes.bed -g {FIXED_DIR}/genome.txt "
            f"| sort -k1,1 -k2,2n > /tmp/test_proms_map.bed")
        out = run_cmd(
            f"bedtools map "
            f"-a /tmp/test_proms_map.bed "
            f"-b {FIXED_DIR}/tfbs_A.bed "
            f"-c 5 -o sum -null 0")
        expected = {}
        for line in out.split("\n"):
            if not line.strip():
                continue
            f = line.split("\t")
            expected[f[3]] = float(f[6])

        lines = read_lines(
            os.path.join(RESULTS_DIR, "tfbs_promoter_scores.tsv"))
        actual = {}
        for line in lines[1:]:
            f = line.split("\t")
            actual[f[0]] = float(f[1])

        checked = 0
        for gene in sorted(expected.keys()):
            assert gene in actual, f"Missing gene {gene} in output"
            assert abs(actual[gene] - expected[gene]) < 0.01, (
                f"TF_A score for {gene}: expected {expected[gene]}, "
                f"got {actual[gene]}")
            checked += 1
        assert checked > 0, "No genes checked"

    def test_spot_check_tf_c(self):
        """Verify TF_C scores — tests that the solver handled the
        sort-order issue in tfbs_C.bed."""
        run_cmd(
            f"bedtools flank -l 2000 -r 0 -s "
            f"-i {FIXED_DIR}/genes.bed -g {FIXED_DIR}/genome.txt "
            f"| sort -k1,1 -k2,2n > /tmp/test_proms_map_c.bed")
        out = run_cmd(
            f"bedtools map "
            f"-a /tmp/test_proms_map_c.bed "
            f"-b {FIXED_DIR}/tfbs_C.bed "
            f"-c 5 -o sum -null 0")
        expected = {}
        for line in out.split("\n"):
            if not line.strip():
                continue
            f = line.split("\t")
            expected[f[3]] = float(f[6])

        lines = read_lines(
            os.path.join(RESULTS_DIR, "tfbs_promoter_scores.tsv"))
        actual = {}
        for line in lines[1:]:
            f = line.split("\t")
            actual[f[0]] = float(f[3])  # C is 4th column (index 3)

        for gene in sorted(expected.keys()):
            assert gene in actual, f"Missing gene {gene}"
            assert abs(actual[gene] - expected[gene]) < 0.01, (
                f"TF_C score for {gene}: expected {expected[gene]}, "
                f"got {actual[gene]}")

    def test_spot_check_tf_d(self):
        """Verify TF_D scores — tests that the solver handled the
        chromosome naming inconsistency in tfbs_D.bed."""
        run_cmd(
            f"bedtools flank -l 2000 -r 0 -s "
            f"-i {FIXED_DIR}/genes.bed -g {FIXED_DIR}/genome.txt "
            f"| sort -k1,1 -k2,2n > /tmp/test_proms_map_d.bed")
        out = run_cmd(
            f"bedtools map "
            f"-a /tmp/test_proms_map_d.bed "
            f"-b {FIXED_DIR}/tfbs_D.bed "
            f"-c 5 -o sum -null 0")
        expected = {}
        for line in out.split("\n"):
            if not line.strip():
                continue
            f = line.split("\t")
            expected[f[3]] = float(f[6])

        lines = read_lines(
            os.path.join(RESULTS_DIR, "tfbs_promoter_scores.tsv"))
        actual = {}
        for line in lines[1:]:
            f = line.split("\t")
            actual[f[0]] = float(f[4])  # D is 5th column (index 4)

        checked = 0
        for gene in sorted(expected.keys()):
            assert gene in actual, f"Missing gene {gene}"
            assert abs(actual[gene] - expected[gene]) < 0.01, (
                f"TF_D score for {gene}: expected {expected[gene]}, "
                f"got {actual[gene]}")
            checked += 1
        assert checked > 0, "No genes checked"


# ===================================================================
# 5. multi_coverage.tsv
# ===================================================================
class TestMultiCoverage:
    def test_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "multi_coverage.tsv"))

    def test_format(self):
        lines = read_lines(
            os.path.join(RESULTS_DIR, "multi_coverage.tsv"))
        assert len(lines) >= 1, "File is empty"
        header = lines[0].split("\t")
        assert header == ["chrom", "bases_covered_by_3plus"], \
            f"Wrong header: {header}"

    def test_values(self):
        """Verify via independent multiinter using corrected files."""
        tfbs_args = " ".join(
            os.path.join(FIXED_DIR, f"tfbs_{s}.bed")
            for s in "ABCDE"
        )
        out = run_cmd(
            f"bedtools multiinter -i {tfbs_args} "
            f"| awk '$4 >= 3 {{print $1\"\\t\"$3-$2}}' "
            f"| sort -k1,1 "
            f"| bedtools groupby -g 1 -c 2 -o sum")
        expected = {}
        for line in out.split("\n"):
            if not line.strip():
                continue
            f = line.split("\t")
            expected[f[0]] = int(f[1])

        lines = read_lines(
            os.path.join(RESULTS_DIR, "multi_coverage.tsv"))
        actual = {}
        for line in lines[1:]:
            f = line.split("\t")
            actual[f[0]] = int(f[1])

        assert actual == expected, (
            f"Multi-coverage mismatch:\n"
            f"  expected: {expected}\n"
            f"  got:      {actual}")


# ===================================================================
# 6. regulatory_deserts.bed
# ===================================================================
class TestRegulatoryDeserts:
    def test_file_exists(self):
        assert os.path.isfile(
            os.path.join(RESULTS_DIR, "regulatory_deserts.bed"))

    def test_min_size(self):
        """All desert intervals must be >= 10000 bp."""
        for line in read_lines(
                os.path.join(RESULTS_DIR, "regulatory_deserts.bed")):
            f = line.split("\t")
            size = int(f[2]) - int(f[1])
            assert size >= 10000, \
                f"Desert too small ({size} bp): {line}"

    def test_no_tfbs_overlap(self):
        """Deserts must not overlap any TFBS from any experiment."""
        fpath = os.path.join(RESULTS_DIR, "regulatory_deserts.bed")
        if os.path.getsize(fpath) == 0:
            pytest.skip("Empty file")
        for tf in "ABCDE":
            tfbs_file = os.path.join(FIXED_DIR, f"tfbs_{tf}.bed")
            count = int(run_cmd(
                f"bedtools intersect -a {fpath} "
                f"-b {tfbs_file} -u | wc -l"))
            assert count == 0, \
                f"Deserts overlap TFBS_{tf} ({count} intervals)"

    def test_correct_deserts(self):
        """Compare with independently computed deserts using
        corrected genome and TFBS files."""
        tfbs_files = " ".join(
            os.path.join(FIXED_DIR, f"tfbs_{s}.bed")
            for s in "ABCDE"
        )
        genome_file = os.path.join(FIXED_DIR, "genome.txt")
        run_cmd(
            f"cat {tfbs_files} "
            f"| cut -f1-3 | sort -k1,1 -k2,2n "
            f"| bedtools merge -i - "
            f"| bedtools complement -i - -g {genome_file} "
            f"| awk '$3 - $2 >= 10000' > /tmp/test_ref_deserts.bed")
        expected = read_lines("/tmp/test_ref_deserts.bed")
        actual = read_lines(
            os.path.join(RESULTS_DIR, "regulatory_deserts.bed"))

        assert len(actual) == len(expected), (
            f"Expected {len(expected)} deserts, got {len(actual)}")
        for exp_line, act_line in zip(expected, actual):
            ef = exp_line.split("\t")[:3]
            af = act_line.split("\t")[:3]
            assert ef == af, (
                f"Desert mismatch: expected {ef}, got {af}")

    def test_sorted(self):
        """Deserts must be sorted by chrom then start."""
        lines = read_lines(
            os.path.join(RESULTS_DIR, "regulatory_deserts.bed"))
        prev = ("", -1)
        for line in lines:
            f = line.split("\t")
            cur = (f[0], int(f[1]))
            assert cur >= prev, f"Not sorted at {line}"
            prev = cur
