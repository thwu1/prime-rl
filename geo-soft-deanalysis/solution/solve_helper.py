#!/usr/bin/env python3
"""Solution: parse GEO SOFT file and perform differential expression analysis."""

import math
import os
import statistics
from collections import defaultdict
from scipy.stats import ttest_rel

SOFT_PATH = "/data/GSE_SYNTH.soft"
RESULTS_DIR = "/app/results"


def parse_soft(path):
    """Parse a GEO SOFT family file.

    SOFT format uses four line types:
      ^ caret  - entity indicator (PLATFORM, SAMPLE, SERIES)
      ! bang   - entity attribute (key = value)
      # hash   - data table column descriptions
      (none)   - data table rows

    Data tables are delimited by !Entity_table_begin / !Entity_table_end.
    The first data row after table_begin is the header.
    """
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
    """Benjamini-Hochberg p-value adjustment (step-up procedure)."""
    n = len(pvalues)
    order = sorted(range(n), key=lambda i: pvalues[i])
    adj = [0.0] * n
    for rank, idx in enumerate(order):
        adj[idx] = min(pvalues[idx] * n / (rank + 1), 1.0)
    for i in range(n - 2, -1, -1):
        adj[order[i]] = min(adj[order[i]], adj[order[i + 1]])
    return adj


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    platform_probes, samples = parse_soft(SOFT_PATH)

    # ---------- 1. Design matrix ----------
    design = []
    for sid in sorted(samples.keys()):
        chars = samples[sid]["chars"]
        design.append({
            "sample_id": sid,
            "patient_id": int(chars["patient id"]),
            "tissue": chars["tissue"],
            "stage": chars["disease stage"].replace("stage ", ""),
        })

    with open(os.path.join(RESULTS_DIR, "design_matrix.tsv"), "w") as f:
        f.write("sample_id\tpatient_id\ttissue\tstage\n")
        for row in design:
            f.write("{}\t{}\t{}\t{}\n".format(
                row["sample_id"], row["patient_id"],
                row["tissue"], row["stage"]))

    # ---------- 2. Probe-gene map ----------
    pgmap = {pid: gene for pid, gene in sorted(platform_probes.items()) if gene}

    with open(os.path.join(RESULTS_DIR, "probe_gene_map.tsv"), "w") as f:
        f.write("probe_id\tgene_symbol\n")
        for pid in sorted(pgmap.keys()):
            f.write("{}\t{}\n".format(pid, pgmap[pid]))

    # ---------- 3. Outlier detection ----------
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

    with open(os.path.join(RESULTS_DIR, "outlier_samples.txt"), "w") as f:
        for sid in sorted(outliers):
            f.write("{}\n".format(sid))

    # ---------- 4. Differential expression ----------
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

    pvals = [r["pvalue"] for r in de_results]
    padj = bh_adjust(pvals)
    for i, r in enumerate(de_results):
        r["padj"] = padj[i]

    de_results.sort(key=lambda r: (r["padj"], r["probe_id"]))

    with open(os.path.join(RESULTS_DIR, "differential_expression.tsv"), "w") as f:
        f.write("probe_id\tgene_symbol\tlog2fc\tpvalue\tpadj\n")
        for r in de_results:
            f.write("{}\t{}\t{:.6f}\t{:.6e}\t{:.6e}\n".format(
                r["probe_id"], r["gene_symbol"],
                r["log2fc"], r["pvalue"], r["padj"]))

    # ---------- 5. Top 20 genes ----------
    gene_best = {}
    for r in de_results:
        g = r["gene_symbol"]
        if g not in gene_best or r["padj"] < gene_best[g]["padj"]:
            gene_best[g] = r

    top20 = sorted(gene_best.values(),
                   key=lambda r: (r["padj"], r["probe_id"]))[:20]

    with open(os.path.join(RESULTS_DIR, "top_20_genes.txt"), "w") as f:
        for r in top20:
            f.write("{}\n".format(r["gene_symbol"]))

    print("Analysis complete. Results in", RESULTS_DIR)


if __name__ == "__main__":
    main()
