"""Pilot-based channel estimation with linear interpolation."""

import numpy as np


def estimate_channel(rx_active, pilot_indices, pilot_value):
    """Least-Squares channel estimation at pilot positions, interpolated to all
    active subcarriers.

    Uses the first OFDM symbol as a reference for the initial channel estimate.
    Note: the estimate inherits any phase rotation present on symbol 0 (e.g. from
    oscillator phase noise).  Downstream CPE compensation handles this.

    Args:
        rx_active: Complex array of shape (n_symbols, n_active).
        pilot_indices: 1-D array/list of pilot positions within active range.
        pilot_value: Known complex pilot symbol value.

    Returns:
        H_est: Complex array of shape (n_active,) — estimated channel
               frequency response across all active subcarriers.
    """
    pilot_indices = np.asarray(pilot_indices)
    n_active = rx_active.shape[1]

    # LS estimate at pilot positions from symbol 0
    rx_pilots = rx_active[0, pilot_indices]
    H_pilots = rx_pilots / pilot_value

    # Linear interpolation (real and imaginary parts separately)
    all_idx = np.arange(n_active)
    H_real = np.interp(all_idx, pilot_indices, H_pilots.real)
    H_imag = np.interp(all_idx, pilot_indices, H_pilots.imag)
    H_est = H_real + 1j * H_imag

    return H_est
