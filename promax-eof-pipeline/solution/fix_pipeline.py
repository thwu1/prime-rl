"""
Fix all numerical bugs in the EOF analysis pipeline.

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

# Bug 3: rotate.py — Promax target loses negative signs (H^p vs sign(H)*|H|^p)
fix_file('/app/pipeline/rotate.py', [
    (
        'target = varimax_load ** power',
        'target = np.sign(varimax_load) * np.abs(varimax_load) ** power',
    ),
])

# Bug 4: postprocess.py — oblique score rotation uses R^T instead of inv(R)^T
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
