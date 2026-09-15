"""
Phase Noise Estimation and Compensation — reference implementation.

Implements CPE estimation via pilot correlation, CPE compensation via
de-rotation, and phase-noise bandwidth estimation by exploiting the
Wiener-process incremental variance with FFT-window averaging correction.
"""


import numpy as np


def estimate_cpe(rx_equalized, pilot_indices, pilot_value):
    """Estimate Common Phase Error per OFDM symbol from pilot subcarriers.

    For each symbol *m*, compute the mean correlation between received and
    expected pilot values and take its angle::

        cpe[m] = angle( mean( rx_eq[m, pilots] · conj(pilot_value) ) )

    Using ``angle(mean(...))`` rather than ``mean(angle(...))`` avoids
    phase-wrapping artefacts and naturally gives an SNR-weighted result
    when pilot amplitudes vary.
    """
    pilot_indices = np.asarray(pilot_indices)
    pv_conj = np.conj(pilot_value)
    n_sym = rx_equalized.shape[0]
    cpe = np.empty(n_sym)

    for m in range(n_sym):
        pilot_rx = rx_equalized[m, pilot_indices]
        cpe[m] = np.angle(np.mean(pilot_rx * pv_conj))

    return cpe


def compensate_cpe(rx_equalized, cpe):
    """Remove the per-symbol CPE from all subcarriers."""
    return rx_equalized * np.exp(-1j * cpe[:, np.newaxis])


def estimate_pn_bandwidth(cpe, config):
    """Estimate the 3-dB bandwidth of the Wiener phase-noise process.

    Derivation
    ----------
    Let phi[n] be the discrete-time Wiener process at sample rate f_s:

        phi[n] = phi[n-1] + w[n],   w ~ N(0, sigma_w^2),
        sigma_w^2 = 2*pi*f_3dB / f_s

    The CPE for OFDM symbol m is the *average* of the phase noise over the
    N-sample FFT window (not a single sample).  Two consecutive CPE averages
    are separated by S = N + N_cp samples.  Because the averages overlap
    through the Wiener process, their difference has variance:

        Var(delta_CPE) = sigma_w^2 * S_eff

    where the effective symbol spacing accounts for intra-window correlation:

        S_eff = S - (N^2 - 1) / (3*N)   (approx.  S - N/3)

    Solving for f_3dB:

        f_3dB = Var(delta_CPE) * f_s / (2*pi * S_eff)
    """
    fs = config["sample_rate"]
    N = config["n_fft"]
    Ncp = config["n_cp"]
    S = N + Ncp

    # Effective symbol spacing with FFT-window averaging correction
    S_eff = S - (N * N - 1) / (3.0 * N)

    # Unwrap to handle any +/-pi discontinuities, then difference
    cpe_unwrapped = np.unwrap(cpe)
    delta = np.diff(cpe_unwrapped)

    var_delta = np.var(delta, ddof=0)

    f_3dB = var_delta * fs / (2.0 * np.pi * S_eff)
    return float(f_3dB)
