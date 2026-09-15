"""
Fix pipeline bugs and implement the rotation module.

"""


def fix_file(path, replacements):
    """Apply text replacements to a file."""
    with open(path) as f:
        content = f.read()
    for old, new in replacements:
        if old not in content:
            raise ValueError(f"Pattern not found in {path}: {old!r}")
        content = content.replace(old, new)
    with open(path, 'w') as f:
        f.write(content)


# Bug 1: preprocess.py — area weighting uses cos(lat) instead of sqrt(cos(lat))
fix_file('/app/pipeline/preprocess.py', [
    (
        'coslat = np.maximum(np.cos(lat_rad), 0.0)',
        'coslat = np.sqrt(np.maximum(np.cos(lat_rad), 0.0))',
    ),
])

# Bug 2: decompose.py — explained variance uses N instead of N-1 (Bessel correction)
fix_file('/app/pipeline/decompose.py', [
    (
        'exp_var = s ** 2 / n_time',
        'exp_var = s ** 2 / (n_time - 1)',
    ),
])

# Bug 3: postprocess.py — oblique score rotation uses R^T instead of inv(R)^T
fix_file('/app/pipeline/postprocess.py', [
    (
        'import numpy as np',
        'import numpy as np\nfrom scipy.linalg import inv',
    ),
    (
        'rot_scores_normalized = U_truncated @ R_combined.T',
        'rot_scores_normalized = U_truncated @ inv(R_combined).T',
    ),
])

# Implement rotation module from scratch
ROTATE_IMPLEMENTATION = '''"""Rotation module: Varimax and Promax factor rotation.

Implements orthogonal Varimax and oblique Promax rotation algorithms
for factor analysis loadings.
"""
import numpy as np
from scipy.linalg import svd, inv


def varimax_criterion(loadings):
    """Varimax criterion: sum of column variances of squared loadings."""
    L2 = loadings ** 2
    return np.sum(np.mean(L2 ** 2, axis=0) - np.mean(L2, axis=0) ** 2)


def varimax_rotation(loadings, max_iter=1000, rtol=1e-8):
    """Kaiser-normalized Varimax rotation via SVD-based analytic iteration."""
    n, k = loadings.shape

    # Kaiser normalization: normalize rows to unit communality
    communalities = np.sqrt(np.sum(loadings ** 2, axis=1, keepdims=True))
    communalities = np.maximum(communalities, 1e-12)
    A = loadings / communalities

    R = np.eye(k)
    d = 0.0

    for _ in range(max_iter):
        old_d = d
        B = A @ R
        B2 = B ** 2
        # Gradient of Varimax criterion
        G = A.T @ (B ** 3 - B @ np.diag(np.mean(B2, axis=0)))
        # SVD-based rotation update
        P, S_vals, Qt = svd(G, full_matrices=False)
        R = P @ Qt
        d = np.sum(S_vals)
        if abs(d - old_d) / max(abs(d), 1e-12) < rtol:
            break

    # Undo Kaiser normalization
    rotated = (A @ R) * communalities
    return rotated, R


def promax_rotation(loadings, power=2, max_iter=1000, rtol=1e-8):
    """Oblique Promax rotation."""
    # Step 1: Varimax rotation
    varimax_load, R_varimax = varimax_rotation(loadings, max_iter, rtol)

    if power == 1:
        phi = np.eye(loadings.shape[1])
        return varimax_load, R_varimax, phi, varimax_load

    # Step 2: Sign-preserving power target
    target = np.sign(varimax_load) * np.abs(varimax_load) ** power

    # Step 3: Least-squares oblique rotation
    H = varimax_load
    HtH_inv = inv(H.T @ H)
    R_pro = HtH_inv @ (H.T @ target)

    # Step 4: Column-normalize
    col_norms = np.sqrt(np.sum(R_pro ** 2, axis=0))
    R_pro_normalized = R_pro / col_norms[None, :]

    # Step 5: Apply oblique rotation
    promax_load = H @ R_pro_normalized

    # Combined rotation matrix
    R_combined = R_varimax @ R_pro_normalized

    # Step 6: Factor correlation matrix (phi)
    R_inv = inv(R_combined)
    C = R_inv @ R_inv.T
    d_diag = np.sqrt(np.diag(C))
    phi = C / np.outer(d_diag, d_diag)

    return promax_load, R_combined, phi, varimax_load
'''

with open('/app/pipeline/rotate.py', 'w') as f:
    f.write(ROTATE_IMPLEMENTATION)
