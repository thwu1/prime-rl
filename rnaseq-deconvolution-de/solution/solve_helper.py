#!/usr/bin/env python3
"""Solution: NNLS deconvolution + composition-aware differential expression."""

import numpy as np
import pandas as pd
from scipy.optimize import nnls
from scipy import stats
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
import os
import warnings

warnings.filterwarnings('ignore')

# ------------------------------------------------------------------
# Load data
# ------------------------------------------------------------------
counts = pd.read_csv('/app/counts.csv', index_col=0)
signature = pd.read_csv('/app/signature.csv', index_col=0)
metadata = pd.read_csv('/app/metadata.csv')

gene_names = counts.index.tolist()
sample_names = counts.columns.tolist()
cell_types = signature.columns.tolist()
n_genes = len(gene_names)
n_samples = len(sample_names)
n_ct = len(cell_types)

conditions = metadata['condition'].values
is_treatment = (conditions == 'treatment').astype(int)

os.makedirs('/app/results', exist_ok=True)

# ------------------------------------------------------------------
# Step 1: Deconvolution via non-negative least squares
# ------------------------------------------------------------------
proportions = np.zeros((n_samples, n_ct))

for i in range(n_samples):
    y = counts.iloc[:, i].values
    A = signature.values
    x, _ = nnls(A, y)
    total = x.sum()
    if total > 0:
        x = x / total
    proportions[i] = x

props_df = pd.DataFrame(proportions, index=sample_names, columns=cell_types)
props_df.to_csv('/app/results/proportions.csv')
print(f"Deconvolution complete for {n_samples} samples.")

# ------------------------------------------------------------------
# Step 2: Differential abundance between conditions
# ------------------------------------------------------------------
da_rows = []
for ct_idx, ct_name in enumerate(cell_types):
    ctrl_vals = proportions[is_treatment == 0, ct_idx]
    treat_vals = proportions[is_treatment == 1, ct_idx]
    ctrl_mean = ctrl_vals.mean()
    treat_mean = treat_vals.mean()
    log2fc = np.log2(treat_mean / ctrl_mean) if ctrl_mean > 0 else 0.0
    _, pval = stats.ttest_ind(treat_vals, ctrl_vals, equal_var=False)
    da_rows.append({
        'cell_type': ct_name,
        'log2fc': log2fc,
        'pvalue': pval,
    })

da_df = pd.DataFrame(da_rows)
_, padj, _, _ = multipletests(da_df['pvalue'].values, method='fdr_bh')
da_df['padj'] = padj
da_df.to_csv('/app/results/da_results.csv', index=False)
print(f"DA: {(da_df['padj'] < 0.05).sum()} significant cell types")

# ------------------------------------------------------------------
# Step 3: Composition-aware differential expression
#   expression ~ condition + batch + cell_proportions
# ------------------------------------------------------------------
batch_dummies = pd.get_dummies(metadata['batch'], drop_first=True).values
# Use n_ct-1 proportions to avoid perfect multicollinearity with intercept
prop_covariates = proportions[:, :-1]

de_rows = []
for g in range(n_genes):
    y = counts.iloc[g, :].values
    X = np.column_stack([
        np.ones(n_samples),       # intercept
        is_treatment,             # condition
        batch_dummies,            # batch (k-1 dummies)
        prop_covariates,          # cell proportions (n_ct-1)
    ])
    try:
        model = sm.OLS(y, X).fit()
        coef = model.params[1]
        pval = model.pvalues[1]
        ctrl_mean = y[is_treatment == 0].mean()
        if ctrl_mean > 0:
            ratio = max((ctrl_mean + coef) / ctrl_mean, 1e-10)
            log2fc = np.log2(ratio)
        else:
            log2fc = float(coef)
    except Exception:
        coef = 0.0
        pval = 1.0
        log2fc = 0.0

    de_rows.append({
        'gene': gene_names[g],
        'log2fc': log2fc,
        'pvalue': pval,
    })

de_df = pd.DataFrame(de_rows)
_, padj, _, _ = multipletests(de_df['pvalue'].values, method='fdr_bh')
de_df['padj'] = padj
de_df.to_csv('/app/results/de_results.csv', index=False)

sig_genes = de_df.loc[de_df['padj'] < 0.05, 'gene'].tolist()
with open('/app/results/significant_genes.txt', 'w') as fh:
    for g in sig_genes:
        fh.write(g + '\n')

print(f"Composition-aware DE: {len(sig_genes)} significant genes (padj < 0.05)")
