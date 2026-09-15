import numpy as np


def compute_evm(tx_symbols, rx_symbols):
    """
    Compute Error Vector Magnitude.

    EVM = RMS(error) / RMS(reference)

    Args:
        tx_symbols: reference constellation points (1D complex array)
        rx_symbols: received constellation points (1D complex array)

    Returns:
        evm_linear: RMS EVM (dimensionless)
        evm_percent: EVM in percent
        evm_dB: EVM in dB (20*log10(evm_linear))
    """
    error = rx_symbols - tx_symbols
    rms_error = np.sqrt(np.mean(np.abs(error) ** 2))
    rms_ref = np.sqrt(np.mean(np.abs(tx_symbols) ** 2))

    evm_linear = rms_error / rms_ref
    evm_percent = evm_linear * 100.0
    evm_dB = 20.0 * np.log10(evm_linear + 1e-30)

    return evm_linear, evm_percent, evm_dB


def estimate_cpe(rx_pilots, tx_pilots):
    """
    Estimate Common Phase Error from pilot subcarriers.

    CPE is the average phase rotation common to all subcarriers
    in an OFDM symbol, caused by low-frequency phase noise.

    Args:
        rx_pilots: received pilot symbols (1D complex array)
        tx_pilots: transmitted pilot symbols (1D complex array)

    Returns:
        cpe_rad: estimated CPE in radians
    """
    products = rx_pilots * np.conj(tx_pilots)
    cpe_rad = np.angle(np.mean(products))
    return cpe_rad


def correct_cpe(rx_symbols, cpe_rad):
    """
    Apply CPE correction to received symbols.

    Args:
        rx_symbols: received symbols (1D complex array)
        cpe_rad: CPE estimate in radians

    Returns:
        corrected symbols
    """
    return rx_symbols * np.exp(-1j * cpe_rad)
