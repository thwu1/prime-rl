#!/usr/bin/env python3
"""Generate synthetic bulk RNA-seq dataset for deconvolution and composition-aware DE task."""
import numpy as np
import pandas as pd
import os

np.random.seed(42)

n_genes = 500
n_samples = 40
cell_types = ['T_cells', 'B_cells', 'Monocytes', 'NK_cells', 'Fibroblasts']
n_ct = len(cell_types)
gene_names = [f'GENE_{i:04d}' for i in range(n_genes)]
sample_names = [f'Sample_{i:02d}' for i in range(n_samples)]

# 1. Signature matrix: clear cell-type-specific markers
sig = np.random.exponential(3.0, (n_genes, n_ct))
for ct_idx in range(n_ct):
    for g in range(ct_idx * 20, ct_idx * 20 + 20):
        sig[g, ct_idx] *= 10.0
        for other in range(n_ct):
            if other != ct_idx:
                sig[g, other] *= 0.2

# 2. True cell type proportions (Dirichlet with tight concentration)
control_mean = np.array([0.20, 0.15, 0.25, 0.10, 0.30])
treatment_mean = np.array([0.35, 0.08, 0.25, 0.15, 0.17])
true_props = np.zeros((n_samples, n_ct))
conditions = []
batches = []
batch_list = ['batch_A', 'batch_B', 'batch_C']

for i in range(n_samples):
    if i < 20:
        conditions.append('control')
        alpha = control_mean * 80
    else:
        conditions.append('treatment')
        alpha = treatment_mean * 80
    true_props[i] = np.random.dirichlet(alpha)
    batches.append(batch_list[i % 3])

# 3. Bulk expression = Signature @ Proportions^T
bulk = sig @ true_props.T

# 4. Batch effects (gene-level, additive)
for b_name in batch_list:
    effect = np.random.normal(0, 2.0, n_genes)
    for i in range(n_samples):
        if batches[i] == b_name:
            bulk[:, i] += effect

# 5. True DE: genes 400-429, first 15 upregulated, last 15 downregulated
for j in range(30):
    gidx = 400 + j
    if j < 15:
        effect = 4.0 + np.random.uniform(0, 2.0)
    else:
        effect = -(4.0 + np.random.uniform(0, 2.0))
    for i in range(20, 40):
        bulk[gidx, i] += effect

# 6. Gaussian noise
bulk += np.random.normal(0, 0.8, bulk.shape)
bulk = np.maximum(bulk, 0.01)

# 7. Save
os.makedirs('/app', exist_ok=True)
os.makedirs('/app/results', exist_ok=True)

pd.DataFrame(bulk, index=gene_names, columns=sample_names).to_csv('/app/counts.csv')
pd.DataFrame(sig, index=gene_names, columns=cell_types).to_csv('/app/signature.csv')
pd.DataFrame({
    'sample_id': sample_names,
    'condition': conditions,
    'batch': batches
}).to_csv('/app/metadata.csv', index=False)
