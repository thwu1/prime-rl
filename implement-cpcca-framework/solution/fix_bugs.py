"""Fix all defects in the cross-decomposition pipeline.

"""

# ============================================================
# Fix cross_decomp.py (6 bugs)
# ============================================================

with open('/app/cross_decomp.py', 'r') as f:
    code = f.read()

# Bug 1: load_fields() reads from /observations (raw, uncentered data)
# instead of /preprocessed (centered anomalies ready for decomposition).
# Discovery requires inspecting the HDF5 structure with h5ls or h5dump.
code = code.replace(
    "X = np.array(f['observations']['X'])",
    "X = np.array(f['preprocessed']['left_field'])"
)
code = code.replace(
    "Y = np.array(f['observations']['Y'])",
    "Y = np.array(f['preprocessed']['right_field'])"
)

# Bug 2: whiten() exponent formula is alpha/2 but should be (alpha-1)/2
# When alpha=1 (no whitening), exponent should be 0 giving W=I.
# When alpha=0 (full whitening), exponent should be -1/2.
# The buggy formula alpha/2 gives 1/2 for alpha=1 (wrong) and 0 for alpha=0 (wrong).
code = code.replace(
    'exponent = alpha / 2.0',
    'exponent = (alpha - 1.0) / 2.0'
)

# Bug 3: cpcca() cross-covariance normalization uses n instead of n-1
# The unbiased covariance estimator divides by n-1 (Bessel's correction).
code = code.replace(
    'C_xy = X_w.T @ Y_w / n',
    'C_xy = X_w.T @ Y_w / (n - 1)'
)

# Bug 4: cpcca() scores computed from raw data instead of whitened data
# Scores should be projections of whitened data onto singular vectors.
code = code.replace(
    'Rx = X @ Qx',
    'Rx = X_w @ Qx'
)
code = code.replace(
    'Ry = Y @ Qy',
    'Ry = Y_w @ Qy'
)

# Bug 5: heterogeneous_patterns() passes arguments in wrong order
# Should be homogeneous_patterns(X, other_scores) not (other_scores, X)
code = code.replace(
    'return homogeneous_patterns(other_scores, X)',
    'return homogeneous_patterns(X, other_scores)'
)

# Bug 6: bootstrap_significance() shuffles feature columns instead of sample rows
# To destroy temporal coupling, must permute the sample (row) axis of Y.
# Shuffling columns (features) preserves temporal coupling, invalidating the null.
code = code.replace(
    'perm = rng.permutation(Y.shape[1])',
    'perm = rng.permutation(n)'
)
code = code.replace(
    'Y_perm = Y[:, perm]',
    'Y_perm = Y[perm]'
)

with open('/app/cross_decomp.py', 'w') as f:
    f.write(code)

# ============================================================
# Fix Makefile (1 bug)
# ============================================================

# Bug 7: The decomposition recipe outputs to $(OUTDIR)/output.npz
# but the Make target is $(OUTDIR)/decomposition.npz. The file is
# created at the wrong path so the downstream validation target
# cannot find it. Fix by using the automatic variable $@.

with open('/app/Makefile', 'r') as f:
    makefile = f.read()

makefile = makefile.replace(
    '$(PYTHON) pipeline.py --n-modes 5 --output $(OUTDIR)/output.npz',
    '$(PYTHON) pipeline.py --n-modes 5 --output $@'
)

with open('/app/Makefile', 'w') as f:
    f.write(makefile)

print("All 7 defects fixed (6 in cross_decomp.py, 1 in Makefile)")
