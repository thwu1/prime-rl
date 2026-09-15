#!/usr/bin/env python3

"""
Solve the GEO SOFT differential expression analysis task.
Parses the SOFT file, maps probes to genes, computes paired DE statistics.
"""

import math
import json
import csv
from collections import defaultdict
from scipy import stats as sp_stats
from scipy.stats import false_discovery_control


def parse_soft(filepath):
    """Parse a GEO SOFT file into platform, samples, and series entities."""
    platform = {"probes": [], "metadata": {}}
    samples = {}
    series = {"metadata": {}, "sample_ids": []}

    current_entity = None
    current_id = None
    in_table = False
    table_headers = None

    with open(filepath, "r") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue

            # Caret line: entity indicator
            if line.startswith("^"):
                parts = line[1:].split("=", 1)
                entity_type = parts[0].strip().upper()
                entity_id = parts[1].strip() if len(parts) > 1 else ""
                in_table = False
                table_headers = None

                if entity_type == "PLATFORM":
                    current_entity = "platform"
                    current_id = entity_id
                elif entity_type == "SAMPLE":
                    current_entity = "sample"
                    current_id = entity_id
                    samples[entity_id] = {"metadata": {}, "characteristics": [], "data": []}
                elif entity_type == "SERIES":
                    current_entity = "series"
                    current_id = entity_id
                continue

            # Bang lines: attributes
            if line.startswith("!"):
                # Check for table begin/end
                lower = line.lower()
                if "table_begin" in lower:
                    in_table = True
                    table_headers = None
                    continue
                if "table_end" in lower:
                    in_table = False
                    table_headers = None
                    continue

                parts = line[1:].split("=", 1)
                if len(parts) < 2:
                    continue
                key = parts[0].strip()
                value = parts[1].strip()

                if current_entity == "platform":
                    platform["metadata"][key] = value
                elif current_entity == "sample":
                    if "characteristics" in key.lower():
                        samples[current_id]["characteristics"].append(value)
                    elif "sample_id" in key.lower() and key.lower().startswith("series"):
                        pass
                    else:
                        samples[current_id]["metadata"][key] = value
                elif current_entity == "series":
                    if key == "Series_sample_id":
                        series["sample_ids"].append(value)
                    else:
                        series["metadata"][key] = value
                continue

            # Hash lines: data table header descriptions
            if line.startswith("#"):
                continue

            # Data lines (in a table)
            if in_table:
                fields = line.split("\t")
                if current_entity == "platform":
                    if table_headers is None:
                        table_headers = fields
                    else:
                        probe = dict(zip(table_headers, fields))
                        platform["probes"].append(probe)
                elif current_entity == "sample":
                    if table_headers is None:
                        table_headers = fields
                    else:
                        if len(fields) >= 2:
                            samples[current_id]["data"].append(
                                {"ID_REF": fields[0], "VALUE": float(fields[1])}
                            )

    return platform, samples, series


def extract_design_matrix(samples):
    """Extract experimental design from sample metadata and characteristics."""
    design = []
    for acc, sample in samples.items():
        chars = {}
        for c in sample["characteristics"]:
            if ":" in c:
                key, val = c.split(":", 1)
                chars[key.strip().lower()] = val.strip()

        condition = "Normal" if chars.get("disease state", "") == "normal" else "Tumor"
        patient_id = chars.get("patient id", "")

        stage_str = chars.get("tumor stage", "")
        if stage_str:
            # Extract integer from "Stage X"
            stage = int("".join(c for c in stage_str if c.isdigit()))
        else:
            stage = None

        design.append({
            "sample_accession": acc,
            "condition": condition,
            "stage": stage,
            "patient_id": patient_id,
        })

    # For normal samples, find their matched tumor's stage via patient_id
    patient_stage = {}
    for d in design:
        if d["condition"] == "Tumor" and d["stage"] is not None:
            patient_stage[d["patient_id"]] = d["stage"]

    for d in design:
        if d["condition"] == "Normal":
            d["stage"] = patient_stage.get(d["patient_id"])

    design.sort(key=lambda x: x["sample_accession"])
    return design


def build_probe_gene_map(platform):
    """Map probe IDs to gene symbols. Use first symbol for multi-gene probes."""
    mapping = {}
    for probe in platform["probes"]:
        gene_sym = probe.get("Gene Symbol", "").strip()
        if gene_sym:
            first_gene = gene_sym.split("///")[0].strip()
            if first_gene:
                mapping[probe["ID"]] = first_gene
    return mapping


def build_expression_matrix(samples, probe_gene_map):
    """Build gene-by-sample expression matrix (log2-transformed, probes averaged per gene)."""
    gene_sample_vals = defaultdict(lambda: defaultdict(list))

    for acc, sample in samples.items():
        for row in sample["data"]:
            probe_id = row["ID_REF"]
            if probe_id in probe_gene_map:
                gene = probe_gene_map[probe_id]
                val = row["VALUE"]
                log2val = math.log2(val) if val > 0 else 0.0
                gene_sample_vals[gene][acc].append(log2val)

    # Average across probes for same gene
    gene_expr = {}
    for gene in sorted(gene_sample_vals.keys()):
        gene_expr[gene] = {}
        for acc in gene_sample_vals[gene]:
            vals = gene_sample_vals[gene][acc]
            gene_expr[gene][acc] = round(sum(vals) / len(vals), 6)

    return gene_expr


def compute_de(gene_expr, design, stage):
    """Compute paired differential expression for a specific stage."""
    # Find patients at this stage
    patients_at_stage = set()
    for d in design:
        if d["stage"] == stage:
            patients_at_stage.add(d["patient_id"])

    # Build patient -> (normal_acc, tumor_acc) mapping
    patient_samples = defaultdict(dict)
    for d in design:
        if d["patient_id"] in patients_at_stage:
            patient_samples[d["patient_id"]][d["condition"]] = d["sample_accession"]

    genes = sorted(gene_expr.keys())
    results = []

    for gene in genes:
        tumor_vals = []
        normal_vals = []

        for pid in sorted(patients_at_stage):
            if "Normal" in patient_samples[pid] and "Tumor" in patient_samples[pid]:
                n_acc = patient_samples[pid]["Normal"]
                t_acc = patient_samples[pid]["Tumor"]
                if n_acc in gene_expr[gene] and t_acc in gene_expr[gene]:
                    normal_vals.append(gene_expr[gene][n_acc])
                    tumor_vals.append(gene_expr[gene][t_acc])

        if len(tumor_vals) >= 2:
            log2fc = sum(tumor_vals) / len(tumor_vals) - sum(normal_vals) / len(normal_vals)
            # Paired t-test
            t_stat, pval = sp_stats.ttest_rel(tumor_vals, normal_vals)
            if math.isnan(pval):
                pval = 1.0
            results.append({
                "gene": gene,
                "log2fc": round(log2fc, 6),
                "pvalue": pval,
            })

    # Benjamini-Hochberg correction
    pvals = [r["pvalue"] for r in results]
    n = len(pvals)
    if n > 0:
        indexed = sorted(range(n), key=lambda i: pvals[i])
        padj = [0.0] * n
        prev = 1.0
        for rank_pos in range(n - 1, -1, -1):
            i = indexed[rank_pos]
            rank = rank_pos + 1
            adj = min(prev, pvals[i] * n / rank)
            adj = min(adj, 1.0)
            padj[i] = adj
            prev = adj
        for i, r in enumerate(results):
            r["padj"] = padj[i]
    else:
        for r in results:
            r["padj"] = r["pvalue"]

    # Sort by padj ascending, then |log2fc| descending
    results.sort(key=lambda x: (x["padj"], -abs(x["log2fc"])))
    return results


def main():
    soft_path = "/app/study.soft"

    # Parse SOFT file
    platform, samples, series = parse_soft(soft_path)

    # Extract design matrix
    design = extract_design_matrix(samples)

    # Write design matrix
    with open("/app/design_matrix.tsv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["sample_accession", "condition", "stage", "patient_id"],
                                delimiter="\t")
        writer.writeheader()
        for d in design:
            writer.writerow(d)

    # Build probe-to-gene mapping
    probe_gene_map = build_probe_gene_map(platform)

    # Build expression matrix
    gene_expr = build_expression_matrix(samples, probe_gene_map)

    # Write expression matrix
    all_accessions = sorted(set(acc for gene in gene_expr for acc in gene_expr[gene]))
    with open("/app/gene_expression.tsv", "w") as f:
        f.write("gene\t" + "\t".join(all_accessions) + "\n")
        for gene in sorted(gene_expr.keys()):
            vals = [str(gene_expr[gene].get(acc, "")) for acc in all_accessions]
            f.write(gene + "\t" + "\t".join(vals) + "\n")

    # Compute DE for each stage
    stages = sorted(set(d["stage"] for d in design if d["stage"] is not None))
    summary = {
        "total_samples": len(samples),
        "total_genes": len(gene_expr),
        "stages": {},
    }

    for stage in stages:
        results = compute_de(gene_expr, design, stage)

        # Write DE results
        with open(f"/app/de_stage{stage}.tsv", "w") as f:
            f.write("gene\tlog2fc\tpvalue\tpadj\n")
            for r in results:
                f.write(f"{r['gene']}\t{r['log2fc']:.6f}\t{r['pvalue']:.6e}\t{r['padj']:.6e}\n")

        # Summary
        sig_up = [r for r in results if r["padj"] < 0.05 and r["log2fc"] > 0]
        sig_down = [r for r in results if r["padj"] < 0.05 and r["log2fc"] < 0]

        # Top 5 up: already sorted by padj then |log2fc|
        top5_up = [r["gene"] for r in sig_up[:5]]
        # Top 5 down: sort by padj ascending then |log2fc| descending
        sig_down_sorted = sorted(sig_down, key=lambda x: (x["padj"], -abs(x["log2fc"])))
        top5_down = [r["gene"] for r in sig_down_sorted[:5]]

        summary["stages"][str(stage)] = {
            "sig_up_count": len(sig_up),
            "sig_down_count": len(sig_down),
            "top5_up": top5_up,
            "top5_down": top5_down,
        }

    # Write summary
    with open("/app/summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("Pipeline complete.")
    print(f"  Samples: {len(samples)}")
    print(f"  Genes: {len(gene_expr)}")
    print(f"  Stages: {stages}")


if __name__ == "__main__":
    main()
