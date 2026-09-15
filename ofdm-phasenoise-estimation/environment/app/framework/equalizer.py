"""Zero-Forcing frequency-domain equalization."""

import numpy as np


def zf_equalize(rx_active, H_est):
    """Apply Zero-Forcing equalization to each OFDM symbol.

    Divides each subcarrier by the estimated channel to remove channel effects.

    Args:
        rx_active: Complex array of shape (n_symbols, n_active).
        H_est: Complex array of shape (n_active,) — channel estimate.

    Returns:
        rx_eq: Complex array of shape (n_symbols, n_active) — equalized symbols.
    """
    return rx_active / H_est[np.newaxis, :]
