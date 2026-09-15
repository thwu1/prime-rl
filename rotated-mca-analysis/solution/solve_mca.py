"""Solution: MCA with Varimax rotation from scratch.

"""
import json
import numpy as np


def load_and_preprocess(path):
    """Load .npz, center, coslat-weight, flatten, remove NaN features."""
    f = np.load(path)
    data = f['data']   # (time, lat, lon)
    lat = f['lat']

    n_time, n_lat, n_lon = data.shape

    # sqrt(cos(lat)) area weights broadcast to (lat, lon)
    coslat = np.sqrt(np.cos(np.radians(lat)))
    weights = coslat[:, np.newaxis] * np.ones((1, n_lon))

    # centre over time
    mean = np.nanmean(data, axis=0)
    data_c = data - mean

    # area-weight
    data_w = data_c * weights[np.newaxis, :, :]

    # flatten spatial dims
    data_2d = data_w.reshape(n_time, -1)

    # drop features with any NaN
    valid = ~np.any(np.isnan(data_2d), axis=0)
    data_clean = data_2d[:, valid]

    return data_clean, int(valid.sum())


def varimax_rotation(loadings, max_iter=1000, tol=1e-8):
    """Varimax via pairwise Jacobi rotations (Kaiser 1958)."""
    p, k = loadings.shape
    R = np.eye(k)
    L = loadings.copy()

    for _ in range(max_iter):
        L_old = L.copy()
        for i in range(k - 1):
            for j in range(i + 1, k):
                u = L[:, i] ** 2 - L[:, j] ** 2
                v = 2.0 * L[:, i] * L[:, j]
                A = u.sum()
                B = v.sum()
                C = (u ** 2 - v ** 2).sum()
                D = (2.0 * u * v).sum()

                num = D - 2.0 * A * B / p
                den = C - (A ** 2 - B ** 2) / p
                theta = 0.25 * np.arctan2(num, den)

                ct = np.cos(theta)
                st = np.sin(theta)

                Li = L[:, i].copy()
                Lj = L[:, j].copy()
                L[:, i] = ct * Li + st * Lj
                L[:, j] = -st * Li + ct * Lj

                Ri = R[:, i].copy()
                Rj = R[:, j].copy()
                R[:, i] = ct * Ri + st * Rj
                R[:, j] = -st * Ri + ct * Rj

        if np.max(np.abs(L - L_old)) < tol:
            break

    return L, R


def main():
    # ---- load and preprocess ----
    X, n_feat_x = load_and_preprocess('/app/data/field_x.npz')
    Y, n_feat_y = load_and_preprocess('/app/data/field_y.npz')
    n_time = X.shape[0]
    n_modes = 6

    # ---- cross-covariance matrix ----
    C = X.T @ Y / (n_time - 1)

    # ---- truncated SVD ----
    U_full, S_full, Vt_full = np.linalg.svd(C, full_matrices=False)
    U = U_full[:, :n_modes]
    S = S_full[:n_modes]
    V = Vt_full[:n_modes, :].T          # (n_feat_y, n_modes)

    # ---- squared covariance fraction ----
    frob_sq = np.sum(C ** 2)
    scf = S ** 2 / frob_sq

    # ---- concatenated loadings (CD95) ----
    sqrt_S = np.sqrt(S)
    A = U * sqrt_S                       # (n_feat_x, n_modes)
    B = V * sqrt_S                       # (n_feat_y, n_modes)
    L = np.vstack([A, B])                # (n_feat_x + n_feat_y, n_modes)

    # ---- Varimax rotation ----
    L_rot, R = varimax_rotation(L)

    # ---- split rotated loadings ----
    A_rot = L_rot[:n_feat_x, :]
    B_rot = L_rot[n_feat_x:, :]

    # ---- rotated variance per mode ----
    rot_var = np.sum(L_rot ** 2, axis=0)
    rot_var_frac = rot_var / rot_var.sum()

    # ---- sort by descending variance ----
    sort_idx = np.argsort(-rot_var)
    rot_var_frac = rot_var_frac[sort_idx]
    R = R[:, sort_idx]
    A_rot = A_rot[:, sort_idx]
    B_rot = B_rot[:, sort_idx]

    # ---- expansion-coefficient correlations ----
    A_norms = np.linalg.norm(A_rot, axis=0)
    B_norms = np.linalg.norm(B_rot, axis=0)
    A_hat = A_rot / A_norms
    B_hat = B_rot / B_norms

    scores_x = X @ A_hat
    scores_y = Y @ B_hat

    cross_corr = []
    for i in range(n_modes):
        r = np.corrcoef(scores_x[:, i], scores_y[:, i])[0, 1]
        cross_corr.append(float(r))

    # ---- write results ----
    results = {
        'n_samples': int(n_time),
        'n_features_x': int(n_feat_x),
        'n_features_y': int(n_feat_y),
        'singular_values': [float(v) for v in S],
        'scf': [float(v) for v in scf],
        'rotation_matrix': [[float(v) for v in row] for row in R.tolist()],
        'rotated_variance_fraction': [float(v) for v in rot_var_frac],
        'cross_correlations': cross_corr,
    }

    with open('/app/results.json', 'w') as fh:
        json.dump(results, fh, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
