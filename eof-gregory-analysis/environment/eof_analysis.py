"""
EOF analysis of surface temperature anomaly field.
Reads CDO-preprocessed temperature data and NCO-computed area weights.
"""
import numpy as np
from netCDF4 import Dataset
import json
import sys


def main():
    tas_file = sys.argv[1]
    weights_file = sys.argv[2]

    # Read temperature field (missing values already replaced by CDO)
    with Dataset(tas_file) as nc:
        tas = np.array(nc.variables['tas'][:])  # (time, lat, lon)

    # Read area weights computed by NCO
    with Dataset(weights_file) as nc:
        area_wgt = np.array(nc.variables['area_weight'][:])  # (lat,)

    nt, ny, nx = tas.shape

    # Apply sqrt(|area_weight|) for covariance weighting
    sqrt_w = np.sqrt(np.abs(area_wgt))
    tas_weighted = tas * sqrt_w[None, :, None]

    # Reshape to (n_space, nt) for covariance computation
    X = tas_weighted.reshape(nt, ny * nx).T  # (ny*nx, nt)

    # Ensure zero temporal mean
    X -= X.mean(axis=1, keepdims=True)

    # Spatial covariance matrix
    C = (X @ X.T) / (nt - 1)

    # Eigendecomposition
    eigvals, eigvecs = np.linalg.eigh(C)
    idx = np.argsort(eigvals)[::-1]
    eigvals = eigvals[idx]
    eigvecs = eigvecs[:, idx]

    # Variance fractions
    pos = eigvals > 0
    total_var = eigvals[pos].sum()
    var_pct = eigvals / total_var * 100.0

    # Significant modes: eigenvalue exceeds mean eigenvalue
    mean_eig = eigvals[pos].mean()
    n_sig = int(np.sum(eigvals > mean_eig))

    # Principal component time series
    pcs = X.T @ eigvecs[:, :n_sig]  # (nt, n_sig)

    # Dominant periods via FFT
    periods = []
    for k in range(n_sig):
        spectrum = np.abs(np.fft.rfft(pcs[:, k]))
        freqs = np.fft.rfftfreq(nt)
        spectrum[0] = 0
        peak = np.argmax(spectrum)
        if freqs[peak] > 0:
            periods.append(round(1.0 / freqs[peak], 1))
        else:
            periods.append(float('inf'))

    result = {
        "n_significant_modes": n_sig,
        "mode_periods": sorted(periods),
        "explained_variance_pct": [round(float(var_pct[i]), 2) for i in range(n_sig)],
        "total_variance_explained_pct": round(float(sum(var_pct[:n_sig])), 2)
    }

    with open('/tmp/pipeline_work/eof_results.json', 'w') as f:
        json.dump(result, f, indent=2)

    print(f"  Found {n_sig} significant modes")


if __name__ == '__main__':
    main()
