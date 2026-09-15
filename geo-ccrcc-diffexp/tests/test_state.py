
import os
import csv
import math
import pytest
import numpy as np
from collections import defaultdict
from scipy import stats

SOFT_PATH = "/opt/geo_data/GSE53757_family.soft"
ANNOT_PATH = "/opt/geo_data/GPL570_annotation.tsv"
RESULTS_DIR = "/app/results"


# -- Independent reference implementation -------------------------------------

def _parse_soft():
    """Reference SOFT parser independent of agent's implementation."""
    samples = {}
    cur = None
    in_tbl = False
    with open(SOFT_PATH) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("^SAMPLE"):
                cur = line.split(" = ", 1)[1].strip()
                samples[cur] = {"title": "", "chars": [], "expr": {}}
            elif cur and line.startswith("!Sample_title"):
                samples[cur]["title"] = line.split(" = ", 1)[1].strip()
            elif cur and line.startswith("!Sample_characteristics_ch1"):
                samples[cur]["chars"].append(line.split(" = ", 1)[1].strip())
            elif line.strip() == "!sample_table_begin":
                in_tbl = True
            elif line.strip() == "!sample_table_end":
                in_tbl = False
            elif in_tbl and cur:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0] != "ID_REF":
                    try:
                        samples[cur]["expr"][parts[0]] = float(parts[1])
                    except ValueError:
                        pass
    return samples


def _parse_chars(chars):
    result = {}
    for c in chars:
        if ": " in c:
            k, v = c.split(": ", 1)
            result[k.strip()] = v.strip()
    return result


def _load_annot():
    p2g = {}
    with open(ANNOT_PATH) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            g = row["Gene Symbol"].strip()
            if g and g != "---":
                p2g[row["ID"].strip()] = g
    return p2g


def _benjamini_hochberg(pvalues):
    n = len(pvalues)
    si = sorted(range(n), key=lambda i: pvalues[i])
    padj = [0.0] * n
    for rank, idx in enumerate(si):
        padj[idx] = pvalues[idx] * n / (rank + 1)
    prev = min(padj[si[-1]], 1.0)
    padj[si[-1]] = prev
    for i in range(len(si) - 2, -1, -1):
        idx = si[i]
        padj[idx] = min(padj[idx], prev, 1.0)
        prev = padj[idx]
    return padj


def _compute_reference():
    """Compute all expected values from source data."""
    samples = _parse_soft()
    p2g = _load_annot()

    # Phenotype
    pheno = {}
    for sid, sd in samples.items():
        ch = _parse_chars(sd["chars"])
        pheno[sid] = {
            "title": sd["title"],
            "tissue": ch.get("tissue", ""),
            "tumor_stage": ch.get("tumor stage", ""),
            "sample_type": ch.get("sample type", ""),
            "patient_id": ch.get("patient id", ""),
        }

    tumor_ids = sorted([s for s, p in pheno.items() if p["sample_type"] == "tumor"])
    normal_ids = sorted([s for s, p in pheno.items() if p["sample_type"] == "normal"])

    # Gene-level expression (mean of probes per gene)
    gene_probes = defaultdict(list)
    for probe, gene in p2g.items():
        gene_probes[gene].append(probe)

    gene_expr = {}
    for gene, probes in gene_probes.items():
        gene_expr[gene] = {}
        for sid in samples:
            vals = [samples[sid]["expr"][p] for p in probes if p in samples[sid]["expr"]]
            if vals:
                gene_expr[gene][sid] = sum(vals) / len(vals)

    # Differential expression
    de = []
    for gene in gene_expr:
        tv = [gene_expr[gene][s] for s in tumor_ids if s in gene_expr[gene]]
        nv = [gene_expr[gene][s] for s in normal_ids if s in gene_expr[gene]]
        if len(tv) < 2 or len(nv) < 2:
            continue
        mt = float(np.mean(tv))
        mn = float(np.mean(nv))
        if mn <= 0:
            continue
        lfc = math.log2(mt / mn)
        _, pv = stats.ttest_ind(tv, nv, equal_var=False)
        de.append({"gene": gene, "mt": mt, "mn": mn, "lfc": lfc, "pv": float(pv)})

    # BH correction
    pvals = [d["pv"] for d in de]
    padj = _benjamini_hochberg(pvals)
    for i, d in enumerate(de):
        d["padj"] = padj[i]

    # Sort by abs(log2fc) descending
    de.sort(key=lambda x: abs(x["lfc"]), reverse=True)

    # Stage progression
    stage_prog = {}
    for gene in ["CA9", "VHL", "VEGFA"]:
        if gene in gene_expr:
            sp = {}
            for sn in [1, 2, 3, 4]:
                sl = "stage {}".format(sn)
                sids = [s for s in tumor_ids if pheno[s]["tumor_stage"] == sl]
                vals = [gene_expr[gene][s] for s in sids if s in gene_expr[gene]]
                sp[sn] = float(np.mean(vals)) if vals else 0.0
            stage_prog[gene] = sp

    return {
        "pheno": pheno,
        "de": de,
        "stage_prog": stage_prog,
        "n_genes": len(gene_expr),
        "tumor_ids": tumor_ids,
        "normal_ids": normal_ids,
    }


@pytest.fixture(scope="module")
def ref():
    return _compute_reference()


# -- Helper to load agent output ----------------------------------------------

def _read_tsv(name):
    path = os.path.join(RESULTS_DIR, name)
    with open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        fields = reader.fieldnames
        rows = list(reader)
    return fields, rows


# -- Tests: Phenotype Matrix --------------------------------------------------

class TestPhenotypeMatrix:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "phenotype_matrix.tsv")), \
            "phenotype_matrix.tsv not found"

    def test_structure(self):
        fields, rows = _read_tsv("phenotype_matrix.tsv")
        assert len(rows) == 24, "Expected 24 sample rows, got {}".format(len(rows))
        required = {"sample_id", "title", "tissue", "tumor_stage", "sample_type", "patient_id"}
        assert required.issubset(set(fields)), \
            "Missing columns: {}".format(required - set(fields))

    def test_tumor_normal_split(self):
        _, rows = _read_tsv("phenotype_matrix.tsv")
        tumors = [r for r in rows if r["sample_type"] == "tumor"]
        normals = [r for r in rows if r["sample_type"] == "normal"]
        assert len(tumors) == 12, "Expected 12 tumor samples"
        assert len(normals) == 12, "Expected 12 normal samples"

    def test_specific_tumor_sample(self, ref):
        _, rows = _read_tsv("phenotype_matrix.tsv")
        by_id = {r["sample_id"]: r for r in rows}
        s = by_id["GSM1300062"]
        assert s["tissue"] == "clear cell renal cell carcinoma"
        assert s["tumor_stage"] == "stage 1"
        assert s["sample_type"] == "tumor"
        assert s["patient_id"] == "PT1001"

    def test_specific_normal_sample(self, ref):
        _, rows = _read_tsv("phenotype_matrix.tsv")
        by_id = {r["sample_id"]: r for r in rows}
        s = by_id["GSM1300074"]
        assert s["tissue"] == "matched normal kidney"
        assert s["sample_type"] == "normal"
        assert s["patient_id"] == "PT1001"

    def test_stage_distribution(self):
        _, rows = _read_tsv("phenotype_matrix.tsv")
        tumors = [r for r in rows if r["sample_type"] == "tumor"]
        stages = [r["tumor_stage"] for r in tumors]
        for sn in [1, 2, 3, 4]:
            count = stages.count("stage {}".format(sn))
            assert count == 3, "Expected 3 stage {} tumors, got {}".format(sn, count)


# -- Tests: Gene Expression Summary -------------------------------------------

class TestGeneExpressionSummary:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "gene_expression_summary.tsv"))

    def test_structure(self):
        fields, rows = _read_tsv("gene_expression_summary.tsv")
        required = {"gene_symbol", "mean_tumor", "mean_normal", "log2fc", "pvalue", "padj"}
        assert required.issubset(set(fields)), \
            "Missing columns: {}".format(required - set(fields))

    def test_gene_count(self, ref):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        assert len(rows) == ref["n_genes"], \
            "Expected {} genes, got {}".format(ref["n_genes"], len(rows))

    def test_no_unmapped_genes(self):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        genes = [r["gene_symbol"] for r in rows]
        assert "---" not in genes, "Unmapped probes should be excluded"

    def test_sorted_by_abs_log2fc(self):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        fcs = [abs(float(r["log2fc"])) for r in rows]
        for i in range(len(fcs) - 1):
            assert fcs[i] >= fcs[i + 1] - 0.002, \
                "Not sorted at row {}: {} < {}".format(i, fcs[i], fcs[i + 1])

    def test_fold_changes_match(self, ref):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        result = {r["gene_symbol"]: r for r in rows}
        for d in ref["de"]:
            gene = d["gene"]
            assert gene in result, "Gene {} missing from results".format(gene)
            actual = float(result[gene]["log2fc"])
            expected = round(d["lfc"], 4)
            assert abs(actual - expected) < 0.05, \
                "log2fc for {}: got {}, expected {}".format(gene, actual, expected)

    def test_mean_values_match(self, ref):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        result = {r["gene_symbol"]: r for r in rows}
        for d in ref["de"][:10]:  # check top 10 genes
            gene = d["gene"]
            actual_mt = float(result[gene]["mean_tumor"])
            actual_mn = float(result[gene]["mean_normal"])
            assert abs(actual_mt - d["mt"]) / max(d["mt"], 1) < 0.01, \
                "mean_tumor for {}: got {}, expected {}".format(gene, actual_mt, d["mt"])
            assert abs(actual_mn - d["mn"]) / max(d["mn"], 1) < 0.01, \
                "mean_normal for {}: got {}, expected {}".format(gene, actual_mn, d["mn"])

    def test_pvalues_valid(self):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        for r in rows:
            pv = float(r["pvalue"])
            pa = float(r["padj"])
            assert 0 <= pv <= 1, "Invalid pvalue {} for {}".format(pv, r["gene_symbol"])
            assert 0 <= pa <= 1, "Invalid padj {} for {}".format(pa, r["gene_symbol"])

    def test_padj_geq_pvalue(self):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        for r in rows:
            pv = float(r["pvalue"])
            pa = float(r["padj"])
            assert pa >= pv - 0.001, \
                "padj ({}) < pvalue ({}) for {}".format(pa, pv, r["gene_symbol"])

    def test_significant_gene_count(self, ref):
        """Verify the number of significant genes matches reference (catches wrong MTC)."""
        _, rows = _read_tsv("gene_expression_summary.tsv")
        n_sig = sum(1 for r in rows if float(r["padj"]) < 0.05)
        expected_n_sig = sum(1 for d in ref["de"] if d["padj"] < 0.05)
        assert abs(n_sig - expected_n_sig) <= 3, \
            "Expected ~{} significant genes (padj<0.05), got {}".format(
                expected_n_sig, n_sig)

    def test_padj_values_match(self, ref):
        """Spot-check padj values against reference (catches wrong MTC method)."""
        _, rows = _read_tsv("gene_expression_summary.tsv")
        result = {r["gene_symbol"]: r for r in rows}
        for d in ref["de"][:15]:
            gene = d["gene"]
            actual = float(result[gene]["padj"])
            expected = round(d["padj"], 4)
            tol = max(abs(expected) * 0.15, 0.005)
            assert abs(actual - expected) < tol, \
                "padj for {}: got {}, expected {}".format(gene, actual, expected)

    def test_housekeeping_genes_stable(self):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        result = {r["gene_symbol"]: r for r in rows}
        for gene in ["GAPDH", "ACTB", "TUBB"]:
            if gene in result:
                lfc = abs(float(result[gene]["log2fc"]))
                assert lfc < 0.5, \
                    "Housekeeping {} should be stable, got log2fc={}".format(gene, lfc)

    def test_known_upregulated(self, ref):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        result = {r["gene_symbol"]: r for r in rows}
        for gene in ["CA9", "NDUFA4L2", "VEGFA"]:
            lfc = float(result[gene]["log2fc"])
            assert lfc > 2.0, \
                "{} should be strongly upregulated, got log2fc={}".format(gene, lfc)

    def test_known_downregulated(self, ref):
        _, rows = _read_tsv("gene_expression_summary.tsv")
        result = {r["gene_symbol"]: r for r in rows}
        for gene in ["ALDOB", "CYP2E1", "VHL"]:
            lfc = float(result[gene]["log2fc"])
            assert lfc < -1.5, \
                "{} should be strongly downregulated, got log2fc={}".format(gene, lfc)


# -- Tests: Top DE Genes ------------------------------------------------------

class TestTopDEGenes:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "top_de_genes.tsv"))

    def test_structure(self):
        fields, rows = _read_tsv("top_de_genes.tsv")
        assert len(rows) == 20, "Expected 20 rows, got {}".format(len(rows))
        required = {"rank", "gene_symbol", "log2fc", "direction"}
        assert required.issubset(set(fields))

    def test_ranks_sequential(self):
        _, rows = _read_tsv("top_de_genes.tsv")
        for i, r in enumerate(rows):
            assert int(r["rank"]) == i + 1, \
                "Expected rank {}, got {}".format(i + 1, r["rank"])

    def test_directions_correct(self):
        _, rows = _read_tsv("top_de_genes.tsv")
        for r in rows:
            lfc = float(r["log2fc"])
            expected = "up" if lfc > 0 else "down"
            assert r["direction"] == expected, \
                "Direction for {}: got {}, lfc={}".format(
                    r["gene_symbol"], r["direction"], lfc)

    def test_includes_downregulated(self):
        """Top genes by magnitude must include strongly downregulated genes."""
        _, rows = _read_tsv("top_de_genes.tsv")
        genes = set(r["gene_symbol"] for r in rows)
        assert "ALDOB" in genes, \
            "ALDOB (strongly downregulated) should appear in top 20 by magnitude"

    def test_top5_match_reference(self, ref):
        _, rows = _read_tsv("top_de_genes.tsv")
        expected_top5 = set(d["gene"] for d in ref["de"][:5])
        actual_top5 = set(r["gene_symbol"] for r in rows[:5])
        assert expected_top5 == actual_top5, \
            "Top 5 mismatch: expected {}, got {}".format(expected_top5, actual_top5)

    def test_top10_match_reference(self, ref):
        _, rows = _read_tsv("top_de_genes.tsv")
        expected_top10 = set(d["gene"] for d in ref["de"][:10])
        actual_top10 = set(r["gene_symbol"] for r in rows[:10])
        assert expected_top10 == actual_top10, \
            "Top 10 mismatch: expected {}, got {}".format(expected_top10, actual_top10)

    def test_fold_changes_descending(self):
        _, rows = _read_tsv("top_de_genes.tsv")
        fcs = [abs(float(r["log2fc"])) for r in rows]
        for i in range(len(fcs) - 1):
            assert fcs[i] >= fcs[i + 1] - 0.002


# -- Tests: Stage Progression -------------------------------------------------

class TestStageProgression:
    def test_file_exists(self):
        assert os.path.exists(os.path.join(RESULTS_DIR, "stage_progression.tsv"))

    def test_structure(self):
        fields, rows = _read_tsv("stage_progression.tsv")
        assert len(rows) == 3, "Expected 3 gene rows, got {}".format(len(rows))
        required = {"gene_symbol", "stage_1", "stage_2", "stage_3", "stage_4"}
        assert required.issubset(set(fields))

    def test_correct_genes_present(self):
        _, rows = _read_tsv("stage_progression.tsv")
        genes = set(r["gene_symbol"] for r in rows)
        assert genes == {"CA9", "VHL", "VEGFA"}, \
            "Expected CA9/VHL/VEGFA, got {}".format(genes)

    def test_ca9_increases(self):
        _, rows = _read_tsv("stage_progression.tsv")
        ca9 = next(r for r in rows if r["gene_symbol"] == "CA9")
        s1 = float(ca9["stage_1"])
        s4 = float(ca9["stage_4"])
        assert s4 > s1 * 1.5, \
            "CA9 should increase with stage: s1={}, s4={}".format(s1, s4)

    def test_vhl_decreases(self):
        _, rows = _read_tsv("stage_progression.tsv")
        vhl = next(r for r in rows if r["gene_symbol"] == "VHL")
        s1 = float(vhl["stage_1"])
        s4 = float(vhl["stage_4"])
        assert s1 > s4 * 1.2, \
            "VHL should decrease with stage: s1={}, s4={}".format(s1, s4)

    def test_vegfa_increases(self):
        _, rows = _read_tsv("stage_progression.tsv")
        vegfa = next(r for r in rows if r["gene_symbol"] == "VEGFA")
        s1 = float(vegfa["stage_1"])
        s4 = float(vegfa["stage_4"])
        assert s4 > s1 * 1.2, \
            "VEGFA should increase with stage: s1={}, s4={}".format(s1, s4)

    def test_values_match_reference(self, ref):
        _, rows = _read_tsv("stage_progression.tsv")
        by_gene = {r["gene_symbol"]: r for r in rows}
        for gene in ["CA9", "VHL", "VEGFA"]:
            for sn in [1, 2, 3, 4]:
                expected = ref["stage_prog"][gene][sn]
                actual = float(by_gene[gene]["stage_{}".format(sn)])
                tol = max(abs(expected) * 0.01, 1.0)
                assert abs(actual - expected) < tol, \
                    "{} stage {}: expected {:.2f}, got {:.2f}".format(
                        gene, sn, expected, actual)
