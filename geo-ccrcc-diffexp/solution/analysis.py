#!/usr/bin/env python3
"""GEO ccRCC differential expression analysis pipeline."""

import csv
import math
import os
from collections import defaultdict
from scipy import stats

SOFT_PATH = "/opt/geo_data/GSE53757_family.soft"
ANNOT_PATH = "/opt/geo_data/GPL570_annotation.tsv"
RESULTS_DIR = "/app/results"

os.makedirs(RESULTS_DIR, exist_ok=True)


def parse_soft(path):
    """Parse GEO SOFT file into sample metadata and expression data."""
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
    """Extract structured phenotype from sample characteristics."""
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
    """Load probe-to-gene mapping, excluding unmapped probes."""
    mapping = {}
    with open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            gene = row["Gene Symbol"].strip()
            if gene and gene != "---":
                mapping[row["ID"].strip()] = gene
    return mapping


def aggregate_to_genes(samples, probe2gene):
    """Compute gene-level expression as mean of constituent probes per sample."""
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
                gene_expr[gene][sid] = sum(vals) / len(vals)
    return gene_expr


def benjamini_hochberg(pvalues):
    """Benjamini-Hochberg FDR correction."""
    n = len(pvalues)
    sorted_idx = sorted(range(n), key=lambda i: pvalues[i])

    padj = [0.0] * n
    for rank, idx in enumerate(sorted_idx):
        padj[idx] = pvalues[idx] * n / (rank + 1)

    # Enforce monotonicity from largest to smallest p-value
    prev = min(padj[sorted_idx[-1]], 1.0)
    padj[sorted_idx[-1]] = prev
    for i in range(len(sorted_idx) - 2, -1, -1):
        idx = sorted_idx[i]
        padj[idx] = min(padj[idx], prev, 1.0)
        prev = padj[idx]

    return padj


def main():
    # Parse data
    samples = parse_soft(SOFT_PATH)
    pheno = extract_phenotype(samples)
    probe2gene = load_annotation(ANNOT_PATH)

    # Write phenotype matrix
    pheno_path = os.path.join(RESULTS_DIR, "phenotype_matrix.tsv")
    with open(pheno_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["sample_id", "title", "tissue", "tumor_stage",
                         "sample_type", "patient_id"],
            delimiter="\t",
        )
        writer.writeheader()
        for sid in sorted(pheno.keys()):
            writer.writerow(pheno[sid])

    # Aggregate to gene level
    gene_expr = aggregate_to_genes(samples, probe2gene)

    # Identify groups
    tumor_ids = sorted([s for s, p in pheno.items() if p["sample_type"] == "tumor"])
    normal_ids = sorted([s for s, p in pheno.items() if p["sample_type"] == "normal"])

    # Differential expression
    de_results = []
    for gene, expr in gene_expr.items():
        tv = [expr[s] for s in tumor_ids if s in expr]
        nv = [expr[s] for s in normal_ids if s in expr]

        if len(tv) < 2 or len(nv) < 2:
            continue

        mt = sum(tv) / len(tv)
        mn = sum(nv) / len(nv)

        if mn <= 0:
            continue

        lfc = math.log2(mt / mn)
        _, pv = stats.ttest_ind(tv, nv, equal_var=False)

        de_results.append({
            "gene_symbol": gene,
            "mean_tumor": mt,
            "mean_normal": mn,
            "log2fc": lfc,
            "pvalue": float(pv),
        })

    # BH correction
    pvals = [r["pvalue"] for r in de_results]
    padj = benjamini_hochberg(pvals)
    for i, r in enumerate(de_results):
        r["padj"] = padj[i]

    # Sort by abs(log2fc) descending
    de_results.sort(key=lambda x: abs(x["log2fc"]), reverse=True)

    # Round values
    for r in de_results:
        r["mean_tumor"] = round(r["mean_tumor"], 4)
        r["mean_normal"] = round(r["mean_normal"], 4)
        r["log2fc"] = round(r["log2fc"], 4)
        r["pvalue"] = round(r["pvalue"], 4)
        r["padj"] = round(r["padj"], 4)

    # Write gene expression summary
    summary_path = os.path.join(RESULTS_DIR, "gene_expression_summary.tsv")
    with open(summary_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["gene_symbol", "mean_tumor", "mean_normal",
                         "log2fc", "pvalue", "padj"],
            delimiter="\t",
        )
        writer.writeheader()
        for r in de_results:
            writer.writerow(r)

    # Write top 20 DE genes
    top_path = os.path.join(RESULTS_DIR, "top_de_genes.tsv")
    with open(top_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["rank", "gene_symbol", "log2fc", "direction"],
            delimiter="\t",
        )
        writer.writeheader()
        for i, r in enumerate(de_results[:20]):
            writer.writerow({
                "rank": i + 1,
                "gene_symbol": r["gene_symbol"],
                "log2fc": r["log2fc"],
                "direction": "up" if r["log2fc"] > 0 else "down",
            })

    # Stage progression for CA9, VHL, VEGFA
    stage_path = os.path.join(RESULTS_DIR, "stage_progression.tsv")
    with open(stage_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["gene_symbol", "stage_1", "stage_2", "stage_3", "stage_4"],
            delimiter="\t",
        )
        writer.writeheader()
        for gene in ["CA9", "VHL", "VEGFA"]:
            if gene not in gene_expr:
                continue
            row = {"gene_symbol": gene}
            for sn in [1, 2, 3, 4]:
                stage_label = "stage {}".format(sn)
                sids = [s for s in tumor_ids
                        if pheno[s]["tumor_stage"] == stage_label]
                vals = [gene_expr[gene][s] for s in sids if s in gene_expr[gene]]
                row["stage_{}".format(sn)] = round(
                    sum(vals) / len(vals), 4) if vals else 0.0
            writer.writerow(row)

    print("Analysis complete. Results in {}".format(RESULTS_DIR))


if __name__ == "__main__":
    main()
