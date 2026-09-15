#!/usr/bin/env python3

"""
Tests for the GEO SOFT differential expression pipeline.
Independently parses the SOFT file and verifies all outputs.
"""

import csv
import json
import math
import os
from collections import defaultdict

import pytest
from scipy.stats import ttest_rel


# ---------------------------------------------------------------------------
# Helpers: independent SOFT parser for verification
# ---------------------------------------------------------------------------

def _parse_soft_for_test(path="/app/study.soft"):
    """Minimal independent SOFT parser."""
    platform_probes = []
    samples = {}
    current_entity = None
    current_id = None
    in_table = False
    table_headers = None

    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("^"):
                parts = line[1:].split("=", 1)
                etype = parts[0].strip().upper()
                eid = parts[1].strip() if len(parts) > 1 else ""
                in_table = False
                table_headers = None
                if etype == "PLATFORM":
                    current_entity = "platform"
                elif etype == "SAMPLE":
                    current_entity = "sample"
                    current_id = eid
                    samples[eid] = {"chars": [], "data": [], "meta": {}}
                elif etype == "SERIES":
                    current_entity = "series"
                continue
            if line.startswith("!"):
                lower = line.lower()
                if "table_begin" in lower:
                    in_table = True
                    table_headers = None
                    continue
                if "table_end" in lower:
                    in_table = False
                    continue
                parts = line[1:].split("=", 1)
                if len(parts) < 2:
                    continue
                key, val = parts[0].strip(), parts[1].strip()
                if current_entity == "sample":
                    if "characteristics" in key.lower():
                        samples[current_id]["chars"].append(val)
                    else:
                        samples[current_id]["meta"][key] = val
                continue
            if line.startswith("#"):
                continue
            if in_table:
                fields = line.split("\t")
                if current_entity == "platform":
                    if table_headers is None:
                        table_headers = fields
                    else:
                        platform_probes.append(dict(zip(table_headers, fields)))
                elif current_entity == "sample":
                    if table_headers is None:
                        table_headers = fields
                    else:
                        if len(fields) >= 2:
                            samples[current_id]["data"].append(
                                (fields[0], float(fields[1]))
                            )

    return platform_probes, samples


def _build_probe_gene_map(probes):
    mapping = {}
    for p in probes:
        gs = p.get("Gene Symbol", "").strip()
        if gs:
            mapping[p["ID"]] = gs.split("///")[0].strip()
    return mapping


def _build_gene_expr(samples, probe_gene):
    gene_vals = defaultdict(lambda: defaultdict(list))
    for acc, s in samples.items():
        for probe_id, val in s["data"]:
            if probe_id in probe_gene:
                gene = probe_gene[probe_id]
                gene_vals[gene][acc].append(math.log2(val) if val > 0 else 0.0)
    result = {}
    for gene in gene_vals:
        result[gene] = {}
        for acc in gene_vals[gene]:
            vs = gene_vals[gene][acc]
            result[gene][acc] = sum(vs) / len(vs)
    return result


def _extract_design(samples):
    design = []
    for acc, s in samples.items():
        chars = {}
        for c in s["chars"]:
            if ":" in c:
                k, v = c.split(":", 1)
                chars[k.strip().lower()] = v.strip()
        cond = "Normal" if chars.get("disease state", "") == "normal" else "Tumor"
        pid = chars.get("patient id", "")
        stage_str = chars.get("tumor stage", "")
        stage = int("".join(c for c in stage_str if c.isdigit())) if stage_str else None
        design.append({"acc": acc, "condition": cond, "stage": stage, "patient": pid})

    patient_stage = {}
    for d in design:
        if d["condition"] == "Tumor" and d["stage"] is not None:
            patient_stage[d["patient"]] = d["stage"]
    for d in design:
        if d["condition"] == "Normal":
            d["stage"] = patient_stage.get(d["patient"])

    return sorted(design, key=lambda x: x["acc"])


def _bh_correct(pvals):
    n = len(pvals)
    indexed = sorted(range(n), key=lambda i: pvals[i])
    padj = [0.0] * n
    prev = 1.0
    for rp in range(n - 1, -1, -1):
        i = indexed[rp]
        rank = rp + 1
        adj = min(prev, pvals[i] * n / rank)
        adj = min(adj, 1.0)
        padj[i] = adj
        prev = adj
    return padj


def _compute_de(gene_expr, design, stage):
    patients = set()
    for d in design:
        if d["stage"] == stage:
            patients.add(d["patient"])
    patient_samples = defaultdict(dict)
    for d in design:
        if d["patient"] in patients:
            patient_samples[d["patient"]][d["condition"]] = d["acc"]

    results = []
    for gene in sorted(gene_expr.keys()):
        tvals, nvals = [], []
        for pid in sorted(patients):
            if "Normal" in patient_samples[pid] and "Tumor" in patient_samples[pid]:
                nacc = patient_samples[pid]["Normal"]
                tacc = patient_samples[pid]["Tumor"]
                if nacc in gene_expr[gene] and tacc in gene_expr[gene]:
                    nvals.append(gene_expr[gene][nacc])
                    tvals.append(gene_expr[gene][tacc])
        if len(tvals) >= 2:
            fc = sum(tvals) / len(tvals) - sum(nvals) / len(nvals)
            _, pval = ttest_rel(tvals, nvals)
            if math.isnan(pval):
                pval = 1.0
            results.append({"gene": gene, "log2fc": fc, "pvalue": pval})

    pvals = [r["pvalue"] for r in results]
    padj = _bh_correct(pvals)
    for i, r in enumerate(results):
        r["padj"] = padj[i]
    results.sort(key=lambda x: (x["padj"], -abs(x["log2fc"])))
    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def soft_data():
    probes, samples = _parse_soft_for_test()
    probe_gene = _build_probe_gene_map(probes)
    gene_expr = _build_gene_expr(samples, probe_gene)
    design = _extract_design(samples)
    return {
        "probes": probes,
        "samples": samples,
        "probe_gene": probe_gene,
        "gene_expr": gene_expr,
        "design": design,
    }


# ---------------------------------------------------------------------------
# Tests: output file existence
# ---------------------------------------------------------------------------

class TestFileExistence:
    def test_design_matrix_exists(self):
        assert os.path.isfile("/app/design_matrix.tsv")

    def test_gene_expression_exists(self):
        assert os.path.isfile("/app/gene_expression.tsv")

    def test_de_files_exist(self):
        for stage in [1, 2, 3, 4]:
            assert os.path.isfile(f"/app/de_stage{stage}.tsv"), f"Missing de_stage{stage}.tsv"

    def test_summary_exists(self):
        assert os.path.isfile("/app/summary.json")


# ---------------------------------------------------------------------------
# Tests: design matrix
# ---------------------------------------------------------------------------

class TestDesignMatrix:
    def _read_design(self):
        rows = []
        with open("/app/design_matrix.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(row)
        return rows

    def test_design_matrix_row_count(self, soft_data):
        rows = self._read_design()
        assert len(rows) == 24, f"Expected 24 rows, got {len(rows)}"

    def test_design_matrix_columns(self):
        with open("/app/design_matrix.tsv") as f:
            header = f.readline().strip().split("\t")
        required = {"sample_accession", "condition", "stage", "patient_id"}
        assert required.issubset(set(header)), f"Missing columns: {required - set(header)}"

    def test_design_matrix_conditions(self):
        rows = self._read_design()
        conditions = set(r["condition"] for r in rows)
        assert conditions == {"Normal", "Tumor"}
        normal_count = sum(1 for r in rows if r["condition"] == "Normal")
        tumor_count = sum(1 for r in rows if r["condition"] == "Tumor")
        assert normal_count == 12
        assert tumor_count == 12

    def test_design_matrix_stages(self):
        rows = self._read_design()
        stages = set(int(r["stage"]) for r in rows)
        assert stages == {1, 2, 3, 4}

    def test_design_matrix_patients(self):
        rows = self._read_design()
        patients = set(r["patient_id"] for r in rows)
        assert len(patients) == 12
        # Each patient should appear exactly twice (Normal + Tumor)
        from collections import Counter
        counts = Counter(r["patient_id"] for r in rows)
        for pid, count in counts.items():
            assert count == 2, f"Patient {pid} appears {count} times, expected 2"

    def test_design_matrix_sorted(self):
        rows = self._read_design()
        accessions = [r["sample_accession"] for r in rows]
        assert accessions == sorted(accessions)

    def test_design_matrix_content_matches(self, soft_data):
        rows = self._read_design()
        expected = soft_data["design"]
        for row, exp in zip(rows, expected):
            assert row["sample_accession"] == exp["acc"]
            assert row["condition"] == exp["condition"]
            assert int(row["stage"]) == exp["stage"]
            assert row["patient_id"] == exp["patient"]


# ---------------------------------------------------------------------------
# Tests: gene expression matrix
# ---------------------------------------------------------------------------

class TestGeneExpression:
    def _read_expr(self):
        with open("/app/gene_expression.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            rows = list(reader)
        return rows

    def test_gene_count(self, soft_data):
        rows = self._read_expr()
        expected_genes = set(soft_data["probe_gene"].values())
        actual_genes = set(r["gene"] for r in rows)
        assert actual_genes == expected_genes, (
            f"Gene mismatch. Missing: {expected_genes - actual_genes}, "
            f"Extra: {actual_genes - expected_genes}"
        )

    def test_sample_columns(self, soft_data):
        with open("/app/gene_expression.tsv") as f:
            header = f.readline().strip().split("\t")
        sample_cols = header[1:]  # first is "gene"
        expected_samples = sorted(soft_data["samples"].keys())
        assert sample_cols == expected_samples

    def test_no_control_probes(self):
        rows = self._read_expr()
        genes = [r["gene"] for r in rows]
        for g in genes:
            assert not g.startswith("AFFX"), f"Control probe gene found: {g}"

    def test_expression_values_spot_check(self, soft_data):
        """Spot-check a few expression values against independently computed values."""
        rows = self._read_expr()
        gene_dict = {r["gene"]: r for r in rows}

        expected = soft_data["gene_expr"]
        # Check a few genes
        for gene in ["SLC2A1", "ACTB", "CDH1", "DDR1"]:
            if gene in expected and gene in gene_dict:
                for acc in list(expected[gene].keys())[:3]:
                    if acc in gene_dict[gene]:
                        actual = float(gene_dict[gene][acc])
                        exp = expected[gene][acc]
                        assert abs(actual - exp) < 0.01, (
                            f"Expression mismatch for {gene}/{acc}: "
                            f"got {actual}, expected {exp}"
                        )

    def test_multi_probe_averaging(self, soft_data):
        """Verify that multi-probe genes (GDI2, ACTB) are properly averaged."""
        rows = self._read_expr()
        gene_dict = {r["gene"]: r for r in rows}

        # GDI2 has 2 probes: 200008_s_at and 200009_at
        # ACTB has 2 probes: 200050_at and 200069_at
        for gene in ["GDI2", "ACTB"]:
            assert gene in gene_dict, f"Gene {gene} not found in expression matrix"
            # The averaged value should differ from either individual probe
            expected = soft_data["gene_expr"]
            if gene in expected:
                for acc in list(expected[gene].keys())[:2]:
                    if acc in gene_dict[gene]:
                        actual = float(gene_dict[gene][acc])
                        exp = expected[gene][acc]
                        assert abs(actual - exp) < 0.01

    def test_multi_gene_probe_first_symbol(self):
        """Verify multi-gene probes use first symbol (DDR1 not MIR4640, HOXA10 not HOXA9)."""
        rows = self._read_expr()
        genes = set(r["gene"] for r in rows)
        assert "DDR1" in genes, "DDR1 should be present (first of DDR1 /// MIR4640)"
        assert "MIR4640" not in genes, "MIR4640 should not be present"
        assert "HOXA10" in genes, "HOXA10 should be present (first of HOXA10 /// HOXA9)"
        assert "HOXA9" not in genes, "HOXA9 should not be present"


# ---------------------------------------------------------------------------
# Tests: differential expression
# ---------------------------------------------------------------------------

class TestDifferentialExpression:
    def _read_de(self, stage):
        rows = []
        with open(f"/app/de_stage{stage}.tsv") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append({
                    "gene": row["gene"],
                    "log2fc": float(row["log2fc"]),
                    "pvalue": float(row["pvalue"]),
                    "padj": float(row["padj"]),
                })
        return rows

    def test_de_columns(self):
        for stage in [1, 2, 3, 4]:
            with open(f"/app/de_stage{stage}.tsv") as f:
                header = f.readline().strip().split("\t")
            required = {"gene", "log2fc", "pvalue", "padj"}
            assert required.issubset(set(header)), f"Stage {stage}: missing columns"

    def test_de_gene_count(self, soft_data):
        """Each DE file should have results for all genes."""
        expected_ngenes = len(set(soft_data["probe_gene"].values()))
        for stage in [1, 2, 3, 4]:
            rows = self._read_de(stage)
            assert len(rows) == expected_ngenes, (
                f"Stage {stage}: expected {expected_ngenes} genes, got {len(rows)}"
            )

    def test_de_sorted_by_padj(self):
        for stage in [1, 2, 3, 4]:
            rows = self._read_de(stage)
            padj_vals = [r["padj"] for r in rows]
            assert padj_vals == sorted(padj_vals), f"Stage {stage}: not sorted by padj"

    def test_de_known_upregulated_genes(self, soft_data):
        """SLC2A1 and HIF1A should be upregulated with correct direction in all stages,
        and significantly so in later stages (3, 4) where effect sizes are larger."""
        for stage in [1, 2, 3, 4]:
            rows = self._read_de(stage)
            gene_dict = {r["gene"]: r for r in rows}
            for gene in ["SLC2A1", "HIF1A"]:
                assert gene in gene_dict, f"Stage {stage}: {gene} missing"
                r = gene_dict[gene]
                assert r["log2fc"] > 0.5, (
                    f"Stage {stage}: {gene} log2fc={r['log2fc']}, expected > 0.5"
                )
                # Small sample sizes (n=3) limit power in early stages;
                # require significance (padj < 0.05) in stages 3-4
                if stage >= 3:
                    assert r["padj"] < 0.05, (
                        f"Stage {stage}: {gene} padj={r['padj']}, expected < 0.05"
                    )
                else:
                    # Early stages: raw pvalue should still be < 0.05
                    assert r["pvalue"] < 0.05, (
                        f"Stage {stage}: {gene} pvalue={r['pvalue']}, expected < 0.05"
                    )

    def test_de_known_downregulated_genes(self, soft_data):
        """CDH1 and ESR1 should be downregulated with correct direction in all stages,
        and significantly so in later stages (3, 4)."""
        for stage in [1, 2, 3, 4]:
            rows = self._read_de(stage)
            gene_dict = {r["gene"]: r for r in rows}
            for gene in ["CDH1", "ESR1"]:
                assert gene in gene_dict, f"Stage {stage}: {gene} missing"
                r = gene_dict[gene]
                assert r["log2fc"] < -0.5, (
                    f"Stage {stage}: {gene} log2fc={r['log2fc']}, expected < -0.5"
                )
                if stage >= 3:
                    assert r["padj"] < 0.05, (
                        f"Stage {stage}: {gene} padj={r['padj']}, expected < 0.05"
                    )
                else:
                    assert r["pvalue"] < 0.05, (
                        f"Stage {stage}: {gene} pvalue={r['pvalue']}, expected < 0.05"
                    )

    def test_de_housekeeping_not_significant(self, soft_data):
        """Housekeeping genes (PRPF31, CAPNS1, SRP14) should not be significant."""
        for stage in [1, 2, 3, 4]:
            rows = self._read_de(stage)
            gene_dict = {r["gene"]: r for r in rows}
            for gene in ["PRPF31", "CAPNS1", "SRP14"]:
                if gene in gene_dict:
                    r = gene_dict[gene]
                    assert r["padj"] > 0.05 or abs(r["log2fc"]) < 0.5, (
                        f"Stage {stage}: housekeeping {gene} appears DE: "
                        f"log2fc={r['log2fc']}, padj={r['padj']}"
                    )

    def test_de_stage_progression(self, soft_data):
        """TOP2A and VEGFA should have increasing |log2fc| from stage 1 to 4."""
        fcs = {}
        for stage in [1, 2, 3, 4]:
            rows = self._read_de(stage)
            gene_dict = {r["gene"]: r for r in rows}
            fcs[stage] = gene_dict

        for gene in ["TOP2A", "VEGFA"]:
            fc_values = [fcs[s][gene]["log2fc"] for s in [1, 2, 3, 4]]
            # Check monotonic increase
            assert fc_values[-1] > fc_values[0], (
                f"{gene} log2fc should increase from stage 1 to 4: {fc_values}"
            )
            # Check stage 4 >> stage 1
            assert fc_values[3] > fc_values[0] + 0.5, (
                f"{gene} stage 4 log2fc should be >0.5 higher than stage 1: {fc_values}"
            )

    def test_de_log2fc_values(self, soft_data):
        """Verify log2fc values match independently computed values (within tolerance)."""
        for stage in [1, 2, 3, 4]:
            expected = _compute_de(soft_data["gene_expr"], soft_data["design"], stage)
            expected_dict = {r["gene"]: r for r in expected}
            actual = self._read_de(stage)
            actual_dict = {r["gene"]: r for r in actual}

            for gene in expected_dict:
                if gene in actual_dict:
                    exp_fc = expected_dict[gene]["log2fc"]
                    act_fc = actual_dict[gene]["log2fc"]
                    assert abs(exp_fc - act_fc) < 0.05, (
                        f"Stage {stage}, {gene}: log2fc mismatch "
                        f"(expected {exp_fc:.4f}, got {act_fc:.4f})"
                    )

    def test_de_padj_values(self, soft_data):
        """Verify padj values are reasonable (within tolerance of independently computed)."""
        for stage in [1, 2, 3, 4]:
            expected = _compute_de(soft_data["gene_expr"], soft_data["design"], stage)
            expected_dict = {r["gene"]: r for r in expected}
            actual = self._read_de(stage)
            actual_dict = {r["gene"]: r for r in actual}

            for gene in expected_dict:
                if gene in actual_dict:
                    exp_padj = expected_dict[gene]["padj"]
                    act_padj = actual_dict[gene]["padj"]
                    # Both significant or both not (with margin)
                    if exp_padj < 0.01:
                        assert act_padj < 0.10, (
                            f"Stage {stage}, {gene}: expected sig (padj={exp_padj:.4e}), "
                            f"got padj={act_padj:.4e}"
                        )
                    elif exp_padj > 0.20:
                        assert act_padj > 0.01, (
                            f"Stage {stage}, {gene}: expected not sig (padj={exp_padj:.4e}), "
                            f"got padj={act_padj:.4e}"
                        )


# ---------------------------------------------------------------------------
# Tests: summary.json
# ---------------------------------------------------------------------------

class TestSummary:
    def _read_summary(self):
        with open("/app/summary.json") as f:
            return json.load(f)

    def test_summary_total_samples(self):
        s = self._read_summary()
        assert s["total_samples"] == 24

    def test_summary_total_genes(self, soft_data):
        s = self._read_summary()
        expected = len(set(soft_data["probe_gene"].values()))
        assert s["total_genes"] == expected, f"Expected {expected} genes, got {s['total_genes']}"

    def test_summary_stages_present(self):
        s = self._read_summary()
        assert "stages" in s
        for stage in ["1", "2", "3", "4"]:
            assert stage in s["stages"], f"Stage {stage} missing from summary"

    def test_summary_stage_keys(self):
        s = self._read_summary()
        for stage_key in ["1", "2", "3", "4"]:
            stage = s["stages"][stage_key]
            required = {"sig_up_count", "sig_down_count", "top5_up", "top5_down"}
            assert required.issubset(set(stage.keys())), (
                f"Stage {stage_key}: missing keys {required - set(stage.keys())}"
            )

    def test_summary_sig_counts_consistent(self):
        """sig_up_count + sig_down_count should not exceed total genes."""
        s = self._read_summary()
        total_genes = s["total_genes"]
        for stage_key in ["1", "2", "3", "4"]:
            stage = s["stages"][stage_key]
            total_sig = stage["sig_up_count"] + stage["sig_down_count"]
            assert total_sig <= total_genes, (
                f"Stage {stage_key}: sig count ({total_sig}) exceeds gene count ({total_genes})"
            )

    def test_summary_top5_up_are_upregulated(self):
        """Top5 up genes should have positive log2fc in corresponding DE file."""
        s = self._read_summary()
        for stage_int in [1, 2, 3, 4]:
            top5 = s["stages"][str(stage_int)]["top5_up"]
            with open(f"/app/de_stage{stage_int}.tsv") as f:
                reader = csv.DictReader(f, delimiter="\t")
                gene_fc = {r["gene"]: float(r["log2fc"]) for r in reader}
            for gene in top5:
                assert gene in gene_fc, f"Stage {stage_int}: top5_up gene {gene} not in DE results"
                assert gene_fc[gene] > 0, (
                    f"Stage {stage_int}: top5_up gene {gene} has negative log2fc={gene_fc[gene]}"
                )

    def test_summary_top5_down_are_downregulated(self):
        """Top5 down genes should have negative log2fc."""
        s = self._read_summary()
        for stage_int in [1, 2, 3, 4]:
            top5 = s["stages"][str(stage_int)]["top5_down"]
            with open(f"/app/de_stage{stage_int}.tsv") as f:
                reader = csv.DictReader(f, delimiter="\t")
                gene_fc = {r["gene"]: float(r["log2fc"]) for r in reader}
            for gene in top5:
                assert gene in gene_fc, f"Stage {stage_int}: top5_down gene {gene} not in DE"
                assert gene_fc[gene] < 0, (
                    f"Stage {stage_int}: top5_down gene {gene} has positive log2fc={gene_fc[gene]}"
                )

    def test_summary_known_markers(self):
        """Known ccRCC markers should appear in appropriate top lists."""
        s = self._read_summary()
        # SLC2A1 should be in top5_up for at least 2 stages
        slc2a1_in_top = sum(
            1 for sk in ["1", "2", "3", "4"]
            if "SLC2A1" in s["stages"][sk]["top5_up"]
        )
        assert slc2a1_in_top >= 2, f"SLC2A1 in top5_up for only {slc2a1_in_top} stages"

        # ESR1 or CDH1 should be in top5_down for at least 2 stages
        esr1_cdh1_count = sum(
            1 for sk in ["1", "2", "3", "4"]
            if "ESR1" in s["stages"][sk]["top5_down"]
            or "CDH1" in s["stages"][sk]["top5_down"]
        )
        assert esr1_cdh1_count >= 2, (
            f"ESR1/CDH1 in top5_down for only {esr1_cdh1_count} stages"
        )

    def test_summary_sig_counts_match_de(self, soft_data):
        """Verify sig counts match independently computed DE results."""
        s = self._read_summary()
        for stage in [1, 2, 3, 4]:
            expected = _compute_de(soft_data["gene_expr"], soft_data["design"], stage)
            exp_up = sum(1 for r in expected if r["padj"] < 0.05 and r["log2fc"] > 0)
            exp_down = sum(1 for r in expected if r["padj"] < 0.05 and r["log2fc"] < 0)
            act_up = s["stages"][str(stage)]["sig_up_count"]
            act_down = s["stages"][str(stage)]["sig_down_count"]
            # Allow small tolerance (±2) due to potential BH implementation differences
            assert abs(act_up - exp_up) <= 2, (
                f"Stage {stage}: sig_up expected ~{exp_up}, got {act_up}"
            )
            assert abs(act_down - exp_down) <= 2, (
                f"Stage {stage}: sig_down expected ~{exp_down}, got {act_down}"
            )
