#!/usr/bin/env python3

"""Solution: Differentially methylated region analysis with batch correction.

Pipeline:
1. Parse bisulfite counts, compute beta = meth/total
2. Filter CpGs with any sample below 10x coverage
3. Batch correction via per-CpG OLS regression (beta ~ condition + batch)
4. Extract condition coefficient as batch-corrected delta_beta
5. Compute p-values from t-test on condition coefficient, apply BH FDR
6. Merge adjacent significant CpGs into DMRs (within 1000bp, same direction, >=3 CpGs)
7. Annotate DMRs with nearest gene by TSS distance
8. Output results
"""

import csv
import math
import numpy as np
from scipy import stats


def read_tsv(path):
    with open(path) as f:
        reader = csv.DictReader(f, delimiter='\t')
        return list(reader)


def bh_fdr(pvalues):
    """Benjamini-Hochberg FDR correction."""
    n = len(pvalues)
    if n == 0:
        return []
    indexed = sorted(enumerate(pvalues), key=lambda t: t[1])
    padj = [0.0] * n
    cummin = float('inf')
    for rank_idx in range(n - 1, -1, -1):
        orig_idx, pval = indexed[rank_idx]
        adjusted = pval * n / (rank_idx + 1)
        cummin = min(cummin, adjusted)
        padj[orig_idx] = min(cummin, 1.0)
    return padj


def main():
    # Read input data from /opt/data/ (persists from Docker build)
    counts_rows = read_tsv('/opt/data/bisulfite_counts.tsv')
    metadata_rows = read_tsv('/opt/data/sample_metadata.tsv')
    gene_rows = read_tsv('/opt/data/gene_annotations.tsv')

    # Parse metadata
    sample_info = {}
    for row in metadata_rows:
        sample_info[row['sample_id']] = row

    case_samples = [r['sample_id'] for r in metadata_rows if r['condition'] == 'case']
    ctrl_samples = [r['sample_id'] for r in metadata_rows if r['condition'] == 'control']
    all_samples = case_samples + ctrl_samples
    n_samples = len(all_samples)

    # Build design matrix for OLS regression: beta ~ intercept + condition + batch
    condition_vec = np.array([1.0 if sample_info[s]['condition'] == 'case' else 0.0
                              for s in all_samples])
    batch_vec = np.array([1.0 if sample_info[s]['batch'] == 'B' else 0.0
                          for s in all_samples])
    X = np.column_stack([np.ones(n_samples), condition_vec, batch_vec])
    XtX = X.T @ X
    XtX_inv = np.linalg.inv(XtX)
    n_params = 3
    df_resid = n_samples - n_params

    # Compute beta values, filter by coverage, run regression
    total_cpgs = len(counts_rows)
    cpg_results = []
    pvalues = []

    for row in counts_rows:
        cpg_id = row['cpg_id']
        chrom = row['chr']
        position = int(row['position'])

        # Check coverage and compute betas
        betas = []
        passes_filter = True
        for s in all_samples:
            total = int(row[f'{s}_total'])
            if total < 10:
                passes_filter = False
                break
            meth = int(row[f'{s}_meth'])
            betas.append(meth / total)

        if not passes_filter:
            continue

        y = np.array(betas)

        # OLS: beta_hat = (X'X)^-1 X'y
        beta_hat = XtX_inv @ (X.T @ y)
        residuals = y - X @ beta_hat
        sigma2 = np.sum(residuals ** 2) / df_resid

        # Standard errors
        se = np.sqrt(sigma2 * np.diag(XtX_inv))

        # Condition coefficient (index 1)
        delta_beta = beta_hat[1]
        se_cond = se[1]
        if se_cond > 0:
            t_stat = delta_beta / se_cond
            p_value = 2 * stats.t.sf(abs(t_stat), df_resid)
        else:
            p_value = 1.0

        # Compute batch-corrected means
        batch_effect = beta_hat[2]
        corrected = y - batch_vec * batch_effect
        case_mask = condition_vec == 1.0
        ctrl_mask = condition_vec == 0.0
        mean_case = float(np.mean(corrected[case_mask]))
        mean_ctrl = float(np.mean(corrected[ctrl_mask]))

        # Clamp betas to [0, 1]
        mean_case = max(0.0, min(1.0, mean_case))
        mean_ctrl = max(0.0, min(1.0, mean_ctrl))

        cpg_results.append({
            'cpg_id': cpg_id,
            'chr': chrom,
            'position': position,
            'mean_case_beta': mean_case,
            'mean_ctrl_beta': mean_ctrl,
            'delta_beta': delta_beta,
            'pvalue': p_value,
        })
        pvalues.append(p_value)

    filtered_cpgs = total_cpgs - len(cpg_results)

    # BH FDR correction
    padj = bh_fdr(pvalues)
    for i, r in enumerate(cpg_results):
        r['padj'] = padj[i]
        r['significant'] = 'TRUE' if padj[i] < 0.05 else 'FALSE'

    # Write cpg_results.tsv
    with open('/app/cpg_results.tsv', 'w') as f:
        f.write('cpg_id\tchr\tposition\tmean_case_beta\tmean_ctrl_beta\t'
                'delta_beta\tpvalue\tpadj\tsignificant\n')
        for r in cpg_results:
            f.write(f"{r['cpg_id']}\t{r['chr']}\t{r['position']}\t"
                    f"{r['mean_case_beta']:.6f}\t{r['mean_ctrl_beta']:.6f}\t"
                    f"{r['delta_beta']:.6f}\t{r['pvalue']:.8e}\t"
                    f"{r['padj']:.8e}\t{r['significant']}\n")

    # === DMR detection ===
    # Sort significant CpGs by chromosome then position
    sig_results = sorted(
        [r for r in cpg_results if r['significant'] == 'TRUE'],
        key=lambda r: (r['chr'], r['position'])
    )

    dmrs = []
    if sig_results:
        current_group = [sig_results[0]]
        for i in range(1, len(sig_results)):
            prev = current_group[-1]
            curr = sig_results[i]
            same_chr = prev['chr'] == curr['chr']
            same_dir = (prev['delta_beta'] > 0) == (curr['delta_beta'] > 0)
            close = (curr['position'] - prev['position']) <= 1000
            if same_chr and same_dir and close:
                current_group.append(curr)
            else:
                if len(current_group) >= 3:
                    dmrs.append(current_group)
                current_group = [curr]
        if len(current_group) >= 3:
            dmrs.append(current_group)

    # Gene annotations for nearest-gene lookup
    gene_list = [(g['gene_id'], int(g['tss'])) for g in gene_rows]
    gene_list.sort(key=lambda g: g[1])

    def nearest_gene(position):
        best_gene = gene_list[0][0]
        best_dist = abs(position - gene_list[0][1])
        for gid, tss in gene_list:
            d = abs(position - tss)
            if d < best_dist:
                best_dist = d
                best_gene = gid
        return best_gene, best_dist

    # Write dmr_results.tsv
    with open('/app/dmr_results.tsv', 'w') as f:
        f.write('dmr_id\tchr\tstart\tend\tn_cpgs\tmean_delta_beta\t'
                'direction\tnearest_gene\tdistance_to_tss\n')
        for d, group in enumerate(dmrs):
            chrom = group[0]['chr']
            start = group[0]['position']
            end = group[-1]['position']
            n_cpgs = len(group)
            mean_delta = sum(r['delta_beta'] for r in group) / n_cpgs
            direction = 'hyper' if mean_delta > 0 else 'hypo'
            center = (start + end) // 2
            gene, dist = nearest_gene(center)
            f.write(f"DMR_{d + 1}\t{chrom}\t{start}\t{end}\t{n_cpgs}\t"
                    f"{mean_delta:.6f}\t{direction}\t{gene}\t{dist}\n")

    # Write qc_report.tsv
    n_sig = sum(1 for r in cpg_results if r['significant'] == 'TRUE')
    n_dmrs = len(dmrs)

    with open('/app/qc_report.tsv', 'w') as f:
        f.write('metric\tvalue\n')
        f.write(f'total_cpgs\t{total_cpgs}\n')
        f.write(f'filtered_cpgs\t{filtered_cpgs}\n')
        f.write(f'tested_cpgs\t{len(cpg_results)}\n')
        f.write(f'significant_cpgs\t{n_sig}\n')
        f.write(f'n_dmrs\t{n_dmrs}\n')
        f.write('batch_correction_method\tOLS_regression_condition_plus_batch\n')

    print(f"Analysis complete:")
    print(f"  {total_cpgs} total CpGs, {filtered_cpgs} filtered, {len(cpg_results)} tested")
    print(f"  {n_sig} significant CpGs, {n_dmrs} DMRs")


if __name__ == '__main__':
    main()
