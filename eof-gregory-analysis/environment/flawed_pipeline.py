"""
Climate variability analysis pipeline.
Performs EOF decomposition and equilibrium climate sensitivity estimation
on coupled model output.
"""
import numpy as np
import json


def compute_eofs(field):
    """Compute empirical orthogonal functions from a spatiotemporal field.

    Parameters
    ----------
    field : ndarray, shape (nx, ny, nt)
        Anomaly field. May contain NaN for masked cells.

    Returns
    -------
    eigvals, eigvecs, pcs, var_pct, n_sig
    """
    nx, ny, nt = field.shape

    # Handle missing values
    data = field.copy()
    data[np.isnan(data)] = 0.0

    # Flatten spatial dimensions: (n_space, nt)
    X = data.reshape(nx * ny, nt)

    # Ensure zero temporal mean
    X -= X.mean(axis=1, keepdims=True)

    # Spatial covariance matrix
    C = (X @ X.T) / (nt - 1)

    # Eigendecomposition
    eigvals, eigvecs = np.linalg.eigh(C)
    idx = np.argsort(eigvals)[::-1]
    eigvals = eigvals[idx]
    eigvecs = eigvecs[:, idx]

    # Fraction of variance explained
    pos = eigvals > 0
    total_var = eigvals[pos].sum()
    var_pct = eigvals / total_var * 100.0

    # Significant modes: eigenvalue exceeds average
    mean_eig = eigvals[pos].mean()
    n_sig = int(np.sum(eigvals > mean_eig))

    # Principal component time series
    pcs = X.T @ eigvecs[:, :n_sig]

    return eigvals, eigvecs, pcs, var_pct, n_sig


def dominant_period(ts):
    """Find dominant oscillation period of a time series via FFT."""
    spectrum = np.abs(np.fft.rfft(ts))
    freqs = np.fft.rfftfreq(len(ts))
    spectrum[0] = 0
    peak = np.argmax(spectrum)
    return 1.0 / freqs[peak] if freqs[peak] > 0 else np.inf


def gregory_ecs(toa_imbalance, gmst_anomaly):
    """Estimate equilibrium climate sensitivity via Gregory regression.

    Fits N = slope * T + intercept and computes ECS.
    """
    # Use initial adjustment period for regression
    T = gmst_anomaly[:150]
    N = toa_imbalance[:150]

    slope, intercept = np.polyfit(T, N, 1)
    ecs = slope / intercept

    return ecs, slope, intercept


def main():
    ds = np.load('/app/data/climate_simulation.npz')
    field = ds['field']
    lat = ds['lat']
    toa = ds['toa_imbalance']
    gmst = ds['gmst_anomaly']

    # EOF analysis
    eigvals, eigvecs, pcs, var_pct, n_sig = compute_eofs(field)

    # Dominant periods
    periods = [round(dominant_period(pcs[:, k]), 1) for k in range(n_sig)]

    # ECS estimation
    ecs, feedback, forcing = gregory_ecs(toa, gmst)

    results = {
        "n_significant_modes": n_sig,
        "mode_periods": sorted(periods),
        "explained_variance_pct": [round(float(var_pct[i]), 2)
                                   for i in range(n_sig)],
        "ecs_estimate": round(float(ecs), 4),
        "feedback_parameter": round(float(feedback), 4),
        "total_variance_explained_pct": round(float(sum(var_pct[:n_sig])), 2),
    }

    with open('/app/pipeline/results_original.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Analysis complete.")


if __name__ == '__main__':
    main()
