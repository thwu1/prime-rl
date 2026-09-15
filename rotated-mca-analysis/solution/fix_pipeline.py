"""Fixed coupled spatial pattern analysis pipeline.

Corrects four bugs in the original pipeline.py:
1. preprocess(): area weighting must use sqrt(cos(lat_radians)), not cos(lat_radians)
2. compute_cross_decomposition(): cross-covariance must divide by (n-1), not n
3. orthogonal_rotation(): angle numerator must subtract 2ab/p, not add
4. main(): mode sorting must be descending (argsort(-rot_var))

"""
import json
import numpy as np
import xarray as xr


def load_field(path):
    ds = xr.open_dataset(path, engine='scipy')
    data = ds['data'].values
    lat = ds['lat'].values
    ds.close()
    return data, lat


def preprocess(data, lat):
    nt, nlat, nlon = data.shape
    # FIX 1: sqrt(cos(radians(lat))) for correct area weighting
    w = np.sqrt(np.cos(np.deg2rad(lat)))[:, None] * np.ones((1, nlon))
    centered = data - np.nanmean(data, axis=0)
    weighted = centered * w[None, :, :]
    flat = weighted.reshape(nt, -1)
    valid_mask = ~np.any(np.isnan(flat), axis=0)
    return flat[:, valid_mask], int(valid_mask.sum())


def compute_cross_decomposition(X, Y, n_modes=6):
    nt = X.shape[0]
    # FIX 2: divide by (nt - 1) for Bessel correction
    C = X.T @ Y / (nt - 1)
    U_full, s_full, Vt_full = np.linalg.svd(C, full_matrices=False)
    U = U_full[:, :n_modes]
    s = s_full[:n_modes]
    V = Vt_full[:n_modes, :].T
    total_sq_cov = np.sum(s_full ** 2)
    scf = s ** 2 / total_sq_cov
    return U, s, V, scf


def orthogonal_rotation(loadings, max_iter=1000, tol=1e-8):
    p, k = loadings.shape
    R = np.eye(k)
    L = loadings.copy()
    for iteration in range(max_iter):
        L_prev = L.copy()
        for i in range(k - 1):
            for j in range(i + 1, k):
                u = L[:, i] ** 2 - L[:, j] ** 2
                v = 2.0 * L[:, i] * L[:, j]
                a = u.sum()
                b = v.sum()
                c = (u ** 2 - v ** 2).sum()
                d = (2.0 * u * v).sum()
                # FIX 3: subtract 2ab/p, not add
                numerator = d - 2.0 * a * b / p
                denominator = c - (a ** 2 - b ** 2) / p
                angle = 0.25 * np.arctan2(numerator, denominator)
                cos_a = np.cos(angle)
                sin_a = np.sin(angle)
                L_i, L_j = L[:, i].copy(), L[:, j].copy()
                L[:, i] = cos_a * L_i + sin_a * L_j
                L[:, j] = -sin_a * L_i + cos_a * L_j
                R_i, R_j = R[:, i].copy(), R[:, j].copy()
                R[:, i] = cos_a * R_i + sin_a * R_j
                R[:, j] = -sin_a * R_i + cos_a * R_j
        if np.max(np.abs(L - L_prev)) < tol:
            break
    return L, R


def main():
    X, n_feat_x = preprocess(*load_field('/app/data/field_x.nc'))
    Y, n_feat_y = preprocess(*load_field('/app/data/field_y.nc'))
    nt = X.shape[0]

    U, s, V, scf = compute_cross_decomposition(X, Y, n_modes=6)

    sqrt_s = np.sqrt(s)
    A = U * sqrt_s
    B = V * sqrt_s
    L = np.vstack([A, B])

    L_rot, R = orthogonal_rotation(L)

    A_rot = L_rot[:n_feat_x, :]
    B_rot = L_rot[n_feat_x:, :]

    rot_var = np.sum(L_rot ** 2, axis=0)
    rvf = rot_var / rot_var.sum()

    # FIX 4: descending sort (argsort with negation)
    sort_idx = np.argsort(-rot_var)
    rvf = rvf[sort_idx]
    R = R[:, sort_idx]
    A_rot = A_rot[:, sort_idx]
    B_rot = B_rot[:, sort_idx]

    a_norms = np.linalg.norm(A_rot, axis=0)
    b_norms = np.linalg.norm(B_rot, axis=0)
    scores_x = X @ (A_rot / a_norms)
    scores_y = Y @ (B_rot / b_norms)

    cross_corr = []
    for i in range(6):
        r = float(np.corrcoef(scores_x[:, i], scores_y[:, i])[0, 1])
        cross_corr.append(r)

    results = {
        'n_samples': int(nt),
        'n_features_x': n_feat_x,
        'n_features_y': n_feat_y,
        'singular_values': [float(x) for x in s],
        'scf': [float(x) for x in scf],
        'rotation_matrix': [[float(x) for x in row] for row in R.tolist()],
        'rotated_variance_fraction': [float(x) for x in rvf],
        'cross_correlations': cross_corr,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
