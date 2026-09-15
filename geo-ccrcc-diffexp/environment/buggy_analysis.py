#!/usr/bin/env python3
"""Preliminary differential expression analysis of GSE53757 ccRCC data."""

import csv
import math
import os
from collections import defaultdict
from scipy import stats

SOFT_PATH = "/opt/geo_data/GSE53757_family.soft"
ANNOT_PATH = "/opt/geo_data/GPL570_annotation.tsv"
RESULTS_DIR = "/opt/analysis/preliminary_results"

os.makedirs(RESULTS_DIR, exist_ok=True)


def parse_soft(path):
    """Parse GEO SOFT format file."""
    samples = {}
    current = None
    in_table = False

    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("^SAMPLE"):
                current = line.split(" = ", 1)[1].strip()
                samples[current] = {"title": "", "chars": [], "expr": {}}
            elif current and line.startswith("!Sample_title"):
                samples[current]["title"] = line.split(" = ", 1)[1].strip()
            elif current and line.startswith("!Sample_characteristics_ch1"):
                samples[current]["chars"].append(line.split(" = ", 1)[1].strip())
            elif line.strip() == "!sample_table_begin":
                in_table = True
            elif line.strip() == "!sample_table_end":
                in_table = False
            elif in_table and current:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0] != "ID_REF":
                    try:
                        samples[current]["expr"][parts[0]] = float(parts[1])
                    except ValueError:
                        pass
    return samples


def extract_phenotype(samples):
    """Build phenotype table from sample characteristics."""
    pheno = {}
    for sid, sd in samples.items():
        chars = {}
        for c in sd["chars"]:
            if ": " in c:
                k, v = c.split(": ", 1)
                chars[k.strip()] = v.strip()
        pheno[sid] = {
            "sample_id": sid,
            "title": sd["title"],
            "tissue": chars.get("tissue", ""),
            "tumor_stage": chars.get("tumor stage", ""),
            "sample_type": chars.get("sample type", ""),
            "patient_id": chars.get("patient id", ""),
        }
    return pheno


def load_annotation(path):
    """Load platform annotation mapping probes to genes."""
    mapping = {}
    with open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            gene = row["Gene Symbol"].strip()
            if gene and gene != "---":
                mapping[row["ID"].strip()] = gene
    return mapping


def summarize_probes(samples, probe2gene):
    """Summarize probe-level data to gene-level per sample."""
    gene_probes = defaultdict(list)
    for probe, gene in probe2gene.items():
        gene_probes[gene].append(probe)

    gene_expr = {}
    for gene, probes in gene_probes.items():
        gene_expr[gene] = {}
        for sid in samples:
            vals = [samples[sid]["expr"][p] for p in probes
                    if p in samples[sid]["expr"]]
            if vals:
                # Use the maximum responding probe as the representative value
                gene_expr[gene][sid] = max(vals)
    return gene_expr


def correct_pvalues(pvalues):
    """Apply multiple testing correction."""
    n = len(pvalues)
    return [min(p * n, 1.0) for p in pvalues]


def main():
    samples = parse_soft(SOFT_PATH)
    pheno = extract_phenotype(samples)
    probe2gene = load_annotation(ANNOT_PATH)

    # Phenotype output
    with open(os.path.join(RESULTS_DIR, "phenotype_matrix.tsv"), "w",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "sample_id", "title", "tissue", "tumor_stage",
            "sample_type", "patient_id"], delimiter="\t")
        w.writeheader()
        for sid in sorted(pheno):
            w.writerow(pheno[sid])

    gene_expr = summarize_probes(samples, probe2gene)

    tumor_ids = sorted(
        [s for s, p in pheno.items() if p["sample_type"] == "tumor"])
    normal_ids = sorted(
        [s for s, p in pheno.items() if p["sample_type"] == "normal"])

    # Differential expression
    de = []
    for gene in gene_expr:
        tv = [gene_expr[gene][s] for s in tumor_ids if s in gene_expr[gene]]
        nv = [gene_expr[gene][s] for s in normal_ids if s in gene_expr[gene]]
        if len(tv) < 2 or len(nv) < 2:
            continue
        mt = sum(tv) / len(tv)
        mn = sum(nv) / len(nv)
        if mn <= 0:
            continue
        lfc = math.log2(mt / mn)
        _, pv = stats.ttest_ind(tv, nv)
        de.append({
            "gene_symbol": gene, "mean_tumor": mt, "mean_normal": mn,
            "log2fc": lfc, "pvalue": float(pv),
        })

    padj = correct_pvalues([d["pvalue"] for d in de])
    for i, d in enumerate(de):
        d["padj"] = padj[i]

    de.sort(key=lambda x: x["log2fc"], reverse=True)

    for d in de:
        for k in ["mean_tumor", "mean_normal", "log2fc", "pvalue", "padj"]:
            d[k] = round(d[k], 4)

    with open(os.path.join(RESULTS_DIR, "gene_expression_summary.tsv"), "w",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "gene_symbol", "mean_tumor", "mean_normal",
            "log2fc", "pvalue", "padj"], delimiter="\t")
        w.writeheader()
        for d in de:
            w.writerow(d)

    with open(os.path.join(RESULTS_DIR, "top_de_genes.tsv"), "w",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "rank", "gene_symbol", "log2fc", "direction"], delimiter="\t")
        w.writeheader()
        for i, d in enumerate(de[:20]):
            w.writerow({"rank": i + 1, "gene_symbol": d["gene_symbol"],
                         "log2fc": d["log2fc"],
                         "direction": "up" if d["log2fc"] > 0 else "down"})

    # Stage progression for marker genes
    with open(os.path.join(RESULTS_DIR, "stage_progression.tsv"), "w",
              newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "gene_symbol", "stage_1", "stage_2", "stage_3", "stage_4"],
            delimiter="\t")
        w.writeheader()
        for gene in ["CA9", "VHL", "VEGFA"]:
            if gene not in gene_expr:
                continue
            row = {"gene_symbol": gene}
            for sn in [1, 2, 3, 4]:
                sl = "stage {}".format(sn)
                sids = [s for s in tumor_ids
                        if pheno[s]["tumor_stage"] == sl]
                vals = [gene_expr[gene][s] for s in sids
                        if s in gene_expr[gene]]
                row["stage_{}".format(sn)] = round(
                    sum(vals) / len(vals), 4) if vals else 0.0
            w.writerow(row)

    print("Preliminary analysis complete: {}".format(RESULTS_DIR))


if __name__ == "__main__":
    main()
