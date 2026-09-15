#!/usr/bin/env python3

"""
GEO SOFT parsing, cross-database reconciliation, and differential expression pipeline.
"""

import csv
import json
import math
import os
from scipy import stats


def parse_soft(path):
    """Parse GEO SOFT file, extracting series and sample metadata + expression data."""
    series = {}
    samples = []
    current_sample = None
    in_table = False

    with open(path) as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")

            # Entity indicator
            if line.startswith("^SERIES"):
                series["accession"] = line.split("=", 1)[1].strip()
                continue
            if line.startswith("^SAMPLE"):
                current_sample = {
                    "id": line.split("=", 1)[1].strip(),
                    "characteristics": {},
                    "expression": {},
                }
                samples.append(current_sample)
                in_table = False
                continue

            # Series attributes
            if current_sample is None and line.startswith("!Series_"):
                key = line.split("=", 1)[0].strip()[1:]  # remove !
                val = line.split("=", 1)[1].strip()
                series[key] = val
                continue

            # Sample attributes
            if current_sample is not None:
                if line == "!Sample_table_begin":
                    in_table = True
                    continue
                if line == "!Sample_table_end":
                    in_table = False
                    continue

                if in_table:
                    if line.startswith("ID_REF"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        current_sample["expression"][parts[0]] = float(parts[1])
                elif line.startswith("!Sample_"):
                    key_full = line.split("=", 1)[0].strip()[1:]  # remove !
                    val = line.split("=", 1)[1].strip()

                    if key_full == "Sample_title":
                        current_sample["title"] = val
                    elif key_full == "Sample_organism_ch1":
                        current_sample["organism"] = val
                    elif key_full == "Sample_platform_id":
                        current_sample["platform_id"] = val
                    elif key_full == "Sample_characteristics_ch1":
                        if ":" in val:
                            tag, v = val.split(":", 1)
                            current_sample["characteristics"][tag.strip()] = v.strip()

    return series, samples


def parse_platform_annotation(path):
    """Parse platform annotation TSV. Returns probe_id -> list of gene symbols."""
    mapping = {}
    with open(path) as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        for row in reader:
            probe_id = row["ID"]
            gene_sym = row["Gene Symbol"]
            if gene_sym == "---" or probe_id.startswith("AFFX-"):
                mapping[probe_id] = []
            elif " /// " in gene_sym:
                mapping[probe_id] = [g.strip() for g in gene_sym.split(" /// ")]
            else:
                mapping[probe_id] = [gene_sym.strip()]
    return mapping


def parse_sra_runinfo(path):
    """Parse SRA RunInfo CSV."""
    with open(path) as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def build_experimental_design(samples, output_path):
    """Extract experimental design matrix from parsed SOFT samples."""
    rows = []
    for s in samples:
        rows.append({
            "sample_id": s["id"],
            "title": s["title"],
            "tissue": s["characteristics"].get("tissue", ""),
            "tumor_stage": s["characteristics"].get("tumor stage", ""),
            "patient_id": s["characteristics"].get("patient id", ""),
            "gender": s["characteristics"].get("gender", ""),
            "age": s["characteristics"].get("age", ""),
            "platform_id": s.get("platform_id", ""),
        })
    rows.sort(key=lambda x: x["sample_id"])

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["sample_id", "title", "tissue", "tumor_stage",
                         "patient_id", "gender", "age", "platform_id"],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(rows)


def build_probe_gene_map(probe_gene_map, output_path):
    """Write probe-gene mapping as JSON."""
    with open(output_path, "w") as f:
        json.dump(probe_gene_map, f, indent=2)


def reconcile_metadata(samples, sra_rows, output_path):
    """Compare GEO sample metadata with SRA RunInfo, report discrepancies."""
    # Build SRA lookup by SampleName
    sra_by_name = {}
    for row in sra_rows:
        sra_by_name[row["SampleName"]] = row

    discrepancies = []
    for idx, s in enumerate(samples):
        title = s["title"]
        sra_row = sra_by_name.get(title)

        if sra_row is None:
            # Sample name mismatch - find the corresponding SRA row by index
            if idx < len(sra_rows):
                sra_row_by_idx = sra_rows[idx]
                discrepancies.append({
                    "geo_sample_id": s["id"],
                    "sra_run_id": sra_row_by_idx["Run"],
                    "field": "sample_name",
                    "geo_value": title,
                    "sra_value": sra_row_by_idx["SampleName"],
                })
            continue

        # Check organism
        geo_org = s.get("organism", "")
        sra_org = sra_row.get("ScientificName", "")
        if geo_org != sra_org:
            discrepancies.append({
                "geo_sample_id": s["id"],
                "sra_run_id": sra_row["Run"],
                "field": "organism",
                "geo_value": geo_org,
                "sra_value": sra_org,
            })

        # Check library source (GEO says "total RNA" → should be TRANSCRIPTOMIC)
        sra_source = sra_row.get("LibrarySource", "")
        if sra_source != "TRANSCRIPTOMIC":
            discrepancies.append({
                "geo_sample_id": s["id"],
                "sra_run_id": sra_row["Run"],
                "field": "library_source",
                "geo_value": "TRANSCRIPTOMIC",
                "sra_value": sra_source,
            })

    result = {"discrepancies": discrepancies}
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)


def compute_differential_expression(samples, probe_gene_map, output_path):
    """Paired t-test differential expression with BH correction."""
    # Group by patient
    patient_map = {}
    for s in samples:
        pid = s["characteristics"].get("patient id", "")
        tissue = s["characteristics"].get("tissue", "")
        stype = "tumor" if "ccRCC" in tissue else "normal"
        patient_map.setdefault(pid, {})[stype] = s

    patients_sorted = sorted(patient_map.keys())
    probe_ids = sorted(samples[0]["expression"].keys())

    results = []
    for probe_id in probe_ids:
        normals = []
        tumors = []
        for pid in patients_sorted:
            if "normal" in patient_map[pid] and "tumor" in patient_map[pid]:
                normals.append(patient_map[pid]["normal"]["expression"][probe_id])
                tumors.append(patient_map[pid]["tumor"]["expression"][probe_id])

        n = len(normals)
        mean_n = sum(normals) / n
        mean_t = sum(tumors) / n
        log2fc = mean_t - mean_n  # already log2 scale

        # Paired t-test
        diffs = [t - nx for t, nx in zip(tumors, normals)]
        mean_d = sum(diffs) / n
        var_d = sum((d - mean_d) ** 2 for d in diffs) / (n - 1)
        se_d = math.sqrt(var_d / n) if var_d > 0 else 1e-10
        t_stat = mean_d / se_d

        p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)

        genes = probe_gene_map.get(probe_id, [])
        gene_str = " /// ".join(genes) if genes else "---"

        results.append({
            "probe_id": probe_id,
            "gene_symbol": gene_str,
            "mean_normal": round(mean_n, 4),
            "mean_tumor": round(mean_t, 4),
            "log2_fold_change": round(log2fc, 4),
            "t_statistic": round(t_stat, 4),
            "p_value": p_val,
        })

    # Benjamini-Hochberg correction
    results.sort(key=lambda x: x["p_value"])
    m = len(results)
    for i, r in enumerate(results):
        r["adj_p_value"] = min(1.0, r["p_value"] * m / (i + 1))

    # Enforce monotonicity (bottom-up)
    for i in range(m - 2, -1, -1):
        results[i]["adj_p_value"] = min(
            results[i]["adj_p_value"], results[i + 1]["adj_p_value"]
        )

    # Sort by adj_p_value
    results.sort(key=lambda x: (x["adj_p_value"], x["probe_id"]))

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["probe_id", "gene_symbol", "mean_normal", "mean_tumor",
                         "log2_fold_change", "t_statistic", "p_value", "adj_p_value"],
            delimiter="\t",
        )
        writer.writeheader()
        for r in results:
            r["p_value"] = f"{r['p_value']:.6e}"
            r["adj_p_value"] = f"{r['adj_p_value']:.6e}"
            writer.writerow(r)


def extract_top_genes(de_path, probe_gene_map, output_path):
    """Extract significantly DE genes (adj_p < 0.05), sorted alphabetically."""
    sig_genes = set()
    with open(de_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            adj_p = float(row["adj_p_value"])
            if adj_p < 0.05:
                probe_id = row["probe_id"]
                genes = probe_gene_map.get(probe_id, [])
                for g in genes:
                    sig_genes.add(g)

    with open(output_path, "w") as f:
        for gene in sorted(sig_genes):
            f.write(gene + "\n")


def main():
    os.makedirs("/app/output", exist_ok=True)

    # Parse source data
    print("Parsing SOFT file...")
    series, samples = parse_soft("/app/data/series.soft")
    print(f"  Found {len(samples)} samples in series {series.get('accession', 'N/A')}")

    print("Parsing platform annotation...")
    probe_gene_map = parse_platform_annotation("/app/data/platform_annotation.tsv")
    multi = sum(1 for v in probe_gene_map.values() if len(v) > 1)
    unmapped = sum(1 for v in probe_gene_map.values() if len(v) == 0)
    print(f"  {len(probe_gene_map)} probes: {multi} multi-mapped, {unmapped} unmapped")

    print("Parsing SRA RunInfo...")
    sra_rows = parse_sra_runinfo("/app/data/sra_runinfo.csv")
    print(f"  {len(sra_rows)} SRA runs")

    # Build outputs
    print("Building experimental design matrix...")
    build_experimental_design(samples, "/app/output/experimental_design.tsv")

    print("Building probe-gene mapping...")
    build_probe_gene_map(probe_gene_map, "/app/output/probe_gene_map.json")

    print("Reconciling metadata...")
    reconcile_metadata(samples, sra_rows, "/app/output/reconciliation_report.json")

    print("Computing differential expression...")
    compute_differential_expression(
        samples, probe_gene_map, "/app/output/de_results.tsv"
    )

    print("Extracting top significant genes...")
    extract_top_genes(
        "/app/output/de_results.tsv", probe_gene_map, "/app/output/top_genes.txt"
    )

    print("Pipeline complete. Output files in /app/output/")


if __name__ == "__main__":
    main()
