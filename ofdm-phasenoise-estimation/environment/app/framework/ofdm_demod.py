"""OFDM Demodulation: CP removal, FFT, active subcarrier extraction."""

import numpy as np


def remove_cp(rx_stream, n_fft, n_cp, n_symbols):
    """Remove cyclic prefix and reshape IQ stream into OFDM symbol matrix.

    Args:
        rx_stream: 1-D complex array of raw IQ samples.
        n_fft: FFT size (number of subcarriers).
        n_cp: Cyclic prefix length in samples.
        n_symbols: Number of OFDM symbols to extract.

    Returns:
        rx_time: Complex array of shape (n_symbols, n_fft) — time-domain
                 OFDM symbols after CP removal.
    """
    symbol_len = n_fft + n_cp
    rx_time = np.empty((n_symbols, n_fft), dtype=np.complex128)
    for m in range(n_symbols):
        start = m * symbol_len + n_cp
        rx_time[m] = rx_stream[start:start + n_fft]
    return rx_time


def fft_demod(rx_time):
    """Apply FFT to each OFDM symbol (time -> frequency domain).

    Args:
        rx_time: Complex array of shape (n_symbols, n_fft).

    Returns:
        rx_freq: Complex array of shape (n_symbols, n_fft) — frequency-domain
                 OFDM symbols.
    """
    return np.fft.fft(rx_time, axis=1)


def extract_active(rx_freq, active_start, active_end):
    """Extract the active (used) subcarriers from the full FFT output.

    Args:
        rx_freq: Complex array of shape (n_symbols, n_fft).
        active_start: First active subcarrier index.
        active_end: One past the last active subcarrier index.

    Returns:
        rx_active: Complex array of shape (n_symbols, n_active).
    """
    return rx_freq[:, active_start:active_end].copy()
