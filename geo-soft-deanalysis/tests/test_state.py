#!/usr/bin/env python3
"""Tests for GEO SOFT differential expression pipeline task."""

import pytest
import os
import math
import csv
import statistics
from collections import defaultdict
from scipy.stats import ttest_rel

SOFT_PATH = "/data/GSE_SYNTH.soft"
RESULTS_DIR = "/app/results"


def parse_soft_file(path):
    """Parse SOFT family file, return platform probe map and samples dict."""
    platform_probes = {}
    samples = {}

    current_type = None
    current_id = None
    in_table = False
    is_header = False

    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n\r")

            if line.startswith("^"):
                parts = line[1:].split(" = ", 1)
                current_type = parts[0].strip().upper()
                current_id = parts[1].strip() if len(parts) > 1 else ""
                in_table = False
                if current_type == "SAMPLE":
                    samples[current_id] = {"chars": {}, "data": {}}
            elif line.startswith("!"):
                low = line.lower()
                if "table_begin" in low:
                    in_table = True
                    is_header = True
                    continue
                if "table_end" in low:
                    in_table = False
                    continue
                if not in_table:
                    parts = line[1:].split(" = ", 1)
                    if len(parts) == 2:
                        attr = parts[0].strip()
                        val = parts[1].strip()
                        if current_type == "SAMPLE" and current_id in samples:
                            if "characteristics" in attr.lower():
                                if ":" in val:
                                    k, v = val.split(":", 1)
                                    samples[current_id]["chars"][k.strip()] = v.strip()
            elif line.startswith("#"):
                pass
            elif in_table:
                if is_header:
                    is_header = False
                    continue
                cols = line.split("\t")
                if current_type == "PLATFORM":
                    pid = cols[0]
                    gene = cols[1] if len(cols) > 1 else ""
                    platform_probes[pid] = gene
                elif current_type == "SAMPLE" and current_id in samples:
                    pid = cols[0]
                    val = float(cols[1])
                    samples[current_id]["data"][pid] = val

    return platform_probes, samples


def bh_adjust(pvalues):
    """Benjamini-Hochberg p-value adjustment."""
    n = len(pvalues)
    order = sorted(range(n), key=lambda i: pvalues[i])
    adj = [0.0] * n
    for rank, idx in enumerate(order):
        adj[idx] = min(pvalues[idx] * n / (rank + 1), 1.0)
    for i in range(n - 2, -1, -1):
        adj[order[i]] = min(adj[order[i]], adj[order[i + 1]])
    return adj


def compute_expected():
    """Compute all expected results from the raw SOFT file."""
    platform_probes, samples = parse_soft_file(SOFT_PATH)

    # Design matrix
    design = []
    for sid in sorted(samples.keys()):
        chars = samples[sid]["chars"]
        design.append({
            "sample_id": sid,
            "patient_id": int(chars["patient id"]),
            "tissue": chars["tissue"],
            "stage": chars["disease stage"].replace("stage ", ""),
        })

    # Probe-gene map (only non-empty genes)
    pgmap = {pid: gene for pid, gene in sorted(platform_probes.items()) if gene}

    # Outlier detection
    sample_medians = {}
    for sid in samples:
        log2_vals = [math.log2(v) for v in samples[sid]["data"].values()]
        sample_medians[sid] = statistics.median(log2_vals)

    tissue_groups = defaultdict(list)
    for sid in samples:
        tissue = samples[sid]["chars"]["tissue"]
        tissue_groups[tissue].append(sid)

    outliers = set()
    for tissue, sids in tissue_groups.items():
        meds = [sample_medians[s] for s in sids]
        mean_m = statistics.mean(meds)
        std_m = statistics.stdev(meds)
        for s in sids:
            if abs(sample_medians[s] - mean_m) > 3 * std_m:
                outliers.add(s)

    # Identify outlier patients and build valid pairs
    outlier_patients = set()
    for sid in outliers:
        outlier_patients.add(int(samples[sid]["chars"]["patient id"]))

    patient_samples = defaultdict(dict)
    for sid in samples:
        pid = int(samples[sid]["chars"]["patient id"])
        tissue = samples[sid]["chars"]["tissue"]
        patient_samples[pid][tissue] = sid

    valid_patients = sorted([
        pid for pid in patient_samples
        if pid not in outlier_patients
        and "tumor" in patient_samples[pid]
        and "normal" in patient_samples[pid]
    ])

    # Differential expression (paired t-test)
    de_results = []
    for probe_id in sorted(pgmap.keys()):
        gene = pgmap[probe_id]
        tumor_log2 = []
        normal_log2 = []
        for pid in valid_patients:
            t_sid = patient_samples[pid]["tumor"]
            n_sid = patient_samples[pid]["normal"]
            tv = samples[t_sid]["data"].get(probe_id)
            nv = samples[n_sid]["data"].get(probe_id)
            if tv and tv > 0 and nv and nv > 0:
                tumor_log2.append(math.log2(tv))
                normal_log2.append(math.log2(nv))

        if len(tumor_log2) >= 2:
            diffs = [t - n for t, n in zip(tumor_log2, normal_log2)]
            log2fc = sum(diffs) / len(diffs)
            _, pval = ttest_rel(tumor_log2, normal_log2)
            de_results.append({
                "probe_id": probe_id,
                "gene_symbol": gene,
                "log2fc": log2fc,
                "pvalue": float(pval),
            })

    # BH correction
    pvals = [r["pvalue"] for r in de_results]
    padj = bh_adjust(pvals)
    for i, r in enumerate(de_results):
        r["padj"] = padj[i]

    de_results.sort(key=lambda r: (r["padj"], r["probe_id"]))

    # Top 20 genes (best probe per gene)
    gene_best = {}
    for r in de_results:
        g = r["gene_symbol"]
        if g not in gene_best or r["padj"] < gene_best[g]["padj"]:
            gene_best[g] = r
    top20 = sorted(gene_best.values(),
                   key=lambda r: (r["padj"], r["probe_id"]))[:20]
    top20_names = [r["gene_symbol"] for r in top20]

    return {
        "design": design,
        "pgmap": pgmap,
        "outliers": sorted(outliers),
        "de_results": de_results,
        "top20": top20_names,
        "num_samples": len(samples),
        "num_probes": len(platform_probes),
    }


@pytest.fixture(scope="session")
def expected():
    return compute_expected()


# ===== Sanity checks on the test's own parsing =====

class TestSanity:
    def test_num_samples(self, expected):
        assert expected["num_samples"] == 40

    def test_num_probes(self, expected):
        assert expected["num_probes"] == 200

    def test_outlier_count(self, expected):
        assert len(expected["outliers"]) == 2

    def test_pgmap_count(self, expected):
        assert len(expected["pgmap"]) == 190


# ===== Output file existence =====

class TestFilesExist:
    def test_design_matrix(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "design_matrix.tsv"))

    def test_probe_gene_map(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "probe_gene_map.tsv"))

    def test_outlier_samples(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "outlier_samples.txt"))

    def test_differential_expression(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "differential_expression.tsv"))

    def test_top_20_genes(self):
        assert os.path.isfile(os.path.join(RESULTS_DIR, "top_20_genes.txt"))


# ===== Design matrix =====

class TestDesignMatrix:
    def test_row_count(self, expected):
        path = os.path.join(RESULTS_DIR, "design_matrix.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
        assert len(rows) == 40

    def test_columns(self):
        path = os.path.join(RESULTS_DIR, "design_matrix.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            _ = list(reader)
        assert set(reader.fieldnames) == {"sample_id", "patient_id", "tissue", "stage"}

    def test_content_matches(self, expected):
        path = os.path.join(RESULTS_DIR, "design_matrix.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        exp = expected["design"]
        for i, (got, want) in enumerate(zip(rows, exp)):
            assert got["sample_id"] == want["sample_id"], \
                "Row {}: sample_id {} != {}".format(i, got["sample_id"], want["sample_id"])
            assert int(got["patient_id"]) == want["patient_id"], \
                "Row {}: patient_id mismatch".format(i)
            assert got["tissue"] == want["tissue"], \
                "Row {}: tissue mismatch".format(i)
            assert got["stage"] == want["stage"], \
                "Row {}: stage mismatch".format(i)


# ===== Probe-gene map =====

class TestProbeGeneMap:
    def test_row_count(self, expected):
        path = os.path.join(RESULTS_DIR, "probe_gene_map.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
        assert len(rows) == len(expected["pgmap"])

    def test_mappings_correct(self, expected):
        path = os.path.join(RESULTS_DIR, "probe_gene_map.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        pgmap = expected["pgmap"]
        for row in rows:
            pid = row["probe_id"]
            assert pid in pgmap, "Unexpected probe {}".format(pid)
            assert row["gene_symbol"] == pgmap[pid], \
                "Gene mismatch for {}: {} != {}".format(pid, row["gene_symbol"], pgmap[pid])


# ===== Outlier samples =====

class TestOutlierSamples:
    def test_content(self, expected):
        path = os.path.join(RESULTS_DIR, "outlier_samples.txt")
        with open(path) as f:
            lines = sorted([l.strip() for l in f if l.strip()])

        exp = sorted(expected["outliers"])
        assert lines == exp, "Outliers mismatch: got {} expected {}".format(lines, exp)


# ===== Differential expression =====

class TestDifferentialExpression:
    def test_row_count(self, expected):
        path = os.path.join(RESULTS_DIR, "differential_expression.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
        assert len(rows) == len(expected["de_results"]), \
            "Expected {} DE rows, got {}".format(len(expected["de_results"]), len(rows))

    def test_has_required_columns(self):
        path = os.path.join(RESULTS_DIR, "differential_expression.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            _ = list(reader)
        required = {"probe_id", "gene_symbol", "log2fc", "pvalue", "padj"}
        assert required.issubset(set(reader.fieldnames)), \
            "Missing columns: {}".format(required - set(reader.fieldnames))

    def test_top5_probes_match(self, expected):
        path = os.path.join(RESULTS_DIR, "differential_expression.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        exp = expected["de_results"]
        for i in range(min(5, len(rows))):
            assert rows[i]["probe_id"] == exp[i]["probe_id"], \
                "Rank {}: probe {} != {}".format(i + 1, rows[i]["probe_id"], exp[i]["probe_id"])

    def test_fold_change_direction(self, expected):
        path = os.path.join(RESULTS_DIR, "differential_expression.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        exp_by_probe = {r["probe_id"]: r for r in expected["de_results"]}
        for row in rows[:20]:
            pid = row["probe_id"]
            got_fc = float(row["log2fc"])
            exp_fc = exp_by_probe[pid]["log2fc"]
            assert (got_fc > 0) == (exp_fc > 0), \
                "FC direction mismatch for {}: got {}, expected {}".format(pid, got_fc, exp_fc)

    def test_fold_change_magnitude(self, expected):
        path = os.path.join(RESULTS_DIR, "differential_expression.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        exp_by_probe = {r["probe_id"]: r for r in expected["de_results"]}
        for row in rows[:10]:
            pid = row["probe_id"]
            got_fc = float(row["log2fc"])
            exp_fc = exp_by_probe[pid]["log2fc"]
            assert abs(got_fc - exp_fc) < 0.15, \
                "FC magnitude off for {}: got {:.4f}, expected {:.4f}".format(
                    pid, got_fc, exp_fc)

    def test_padj_sorted(self):
        path = os.path.join(RESULTS_DIR, "differential_expression.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        padj_vals = [float(r["padj"]) for r in rows]
        for i in range(1, len(padj_vals)):
            assert padj_vals[i] >= padj_vals[i - 1] - 1e-10, \
                "padj not sorted at position {}".format(i)

    def test_padj_bounded(self):
        path = os.path.join(RESULTS_DIR, "differential_expression.tsv")
        with open(path) as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)

        for row in rows:
            padj = float(row["padj"])
            assert 0 <= padj <= 1.0 + 1e-10, \
                "padj out of range for {}: {}".format(row["probe_id"], padj)


# ===== Top 20 genes =====

class TestTopGenes:
    def test_count(self):
        path = os.path.join(RESULTS_DIR, "top_20_genes.txt")
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 20

    def test_set_matches(self, expected):
        path = os.path.join(RESULTS_DIR, "top_20_genes.txt")
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip()]

        exp_set = set(expected["top20"])
        got_set = set(lines)
        assert got_set == exp_set, \
            "Gene set mismatch. Extra: {}, Missing: {}".format(
                got_set - exp_set, exp_set - got_set)

    def test_top5_order(self, expected):
        path = os.path.join(RESULTS_DIR, "top_20_genes.txt")
        with open(path) as f:
            lines = [l.strip() for l in f if l.strip()]

        exp = expected["top20"]
        for i in range(min(5, len(lines))):
            assert lines[i] == exp[i], \
                "Rank {}: expected {}, got {}".format(i + 1, exp[i], lines[i])
