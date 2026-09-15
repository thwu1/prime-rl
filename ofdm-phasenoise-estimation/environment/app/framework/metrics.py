"""Signal quality metrics: EVM computation."""

import numpy as np

# Normalized 16-QAM constellation (average power = 1)
_QAM16 = np.array([
    -3 - 3j, -3 - 1j, -3 + 3j, -3 + 1j,
    -1 - 3j, -1 - 1j, -1 + 3j, -1 + 1j,
    +3 - 3j, +3 - 1j, +3 + 3j, +3 + 1j,
    +1 - 3j, +1 - 1j, +1 + 3j, +1 + 1j,
]) / np.sqrt(10.0)


def _nearest_constellation(symbols, constellation):
    """Map each symbol to the nearest constellation point (hard decision)."""
    flat = symbols.flatten()
    dist = np.abs(flat[:, np.newaxis] - constellation[np.newaxis, :])
    nearest = constellation[np.argmin(dist, axis=1)]
    return nearest.reshape(symbols.shape)


def compute_evm_db(rx_symbols, modulation, pilot_indices=None):
    """Compute RMS Error Vector Magnitude in dB (decision-directed).

    Pilot subcarriers are excluded from the EVM computation because their
    transmitted values differ from the data constellation.

    Args:
        rx_symbols: Complex array of shape (n_symbols, n_active).
        modulation: Modulation string, currently only '16QAM'.
        pilot_indices: Optional list of pilot positions to exclude.

    Returns:
        evm_db: RMS EVM in dB  (20 * log10 of fractional EVM).
    """
    if modulation != "16QAM":
        raise ValueError(f"Unsupported modulation: {modulation}")

    # Exclude pilots
    if pilot_indices is not None:
        mask = np.ones(rx_symbols.shape[1], dtype=bool)
        mask[np.asarray(pilot_indices)] = False
        data = rx_symbols[:, mask]
    else:
        data = rx_symbols

    ref = _nearest_constellation(data, _QAM16)
    err = data - ref
    evm_rms = np.sqrt(np.mean(np.abs(err) ** 2) / np.mean(np.abs(ref) ** 2))
    return 20.0 * np.log10(evm_rms + 1e-30)
