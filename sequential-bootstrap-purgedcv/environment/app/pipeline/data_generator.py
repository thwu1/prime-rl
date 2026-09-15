"""Synthetic financial data generator with autocorrelated features."""

import numpy as np
import pandas as pd


def generate_dataset(seed, n_samples, ar_coef, label_horizon,
                     n_informative, n_redundant, n_noise):
    """Generate synthetic financial time-series data.

    Creates features from an AR(1) process with high persistence and
    forward-looking labels that span multiple bars.

    Returns:
        X: DataFrame of features (informative I_*, redundant R_*, noise N_*)
        y: Series of binary labels
        t1: Series mapping each observation index to its label end time
        feature_names: list of feature column names
    """
    rng = np.random.RandomState(seed)

    # AR(1) signal with high persistence
    signal = np.zeros(n_samples)
    for i in range(1, n_samples):
        signal[i] = ar_coef * signal[i - 1] + rng.randn() * 0.25

    # Informative features: signal + lagged values
    X_inf = np.zeros((n_samples, n_informative))
    X_inf[:, 0] = signal
    for j in range(1, n_informative):
        X_inf[j:, j] = signal[:-j]

    # Redundant features: linear combinations of informative
    X_red = np.zeros((n_samples, n_redundant))
    for j in range(n_redundant):
        w = rng.randn(n_informative)
        X_red[:, j] = X_inf @ w + rng.randn(n_samples) * 0.01

    # Noise features: IID Gaussian
    X_noise = rng.randn(n_samples, n_noise)

    X_data = np.hstack([X_inf, X_red, X_noise])

    # Forward-looking labels: sign of return over label_horizon bars
    forward_ret = np.zeros(n_samples)
    for i in range(n_samples - label_horizon):
        forward_ret[i] = signal[i + label_horizon] - signal[i]
    y_data = (forward_ret > 0).astype(int)

    # Build DataFrames with business day index
    dates = pd.bdate_range(end='2024-01-01', periods=n_samples)
    feature_names = (
        [f'I_{i}' for i in range(n_informative)]
        + [f'R_{i}' for i in range(n_redundant)]
        + [f'N_{i}' for i in range(n_noise)]
    )
    X = pd.DataFrame(X_data, index=dates, columns=feature_names)
    y = pd.Series(y_data, index=dates)

    # Label end times: each label depends on data up to label_horizon bars ahead
    t1 = pd.Series(
        [dates[min(i + label_horizon, n_samples - 1)] for i in range(n_samples)],
        index=dates
    )

    return X, y, t1, feature_names
