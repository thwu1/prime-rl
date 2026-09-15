import numpy as np


def get_constellation(modulation):
    """Get normalized QAM constellation with unit average power."""
    if modulation == "64QAM":
        levels = np.array([-7, -5, -3, -1, 1, 3, 5, 7])
        const = np.array([i + 1j * q for i in levels for q in levels])
    elif modulation == "16QAM":
        levels = np.array([-3, -1, 1, 3])
        const = np.array([i + 1j * q for i in levels for q in levels])
    elif modulation == "QPSK":
        const = np.array([1 + 1j, 1 - 1j, -1 + 1j, -1 - 1j]) / np.sqrt(2)
        return const
    else:
        raise ValueError(f"Unknown modulation: {modulation}")

    const = const / np.sqrt(np.mean(np.abs(const) ** 2))
    return const


def get_subcarrier_allocation(n_fft, n_active, pilot_spacing):
    """
    Determine data and pilot subcarrier FFT bin indices.

    Active subcarriers are centered around DC (DC is null).
    Subcarrier indices: -n_active//2 .. -1, 1 .. n_active//2.
    Pilot placement: every pilot_spacing-th active subcarrier.

    Returns:
        data_indices: list of FFT bin indices for data subcarriers
        pilot_indices: list of FFT bin indices for pilot subcarriers
        active_sc: list of subcarrier indices (negative to positive)
    """
    active_sc = list(range(-n_active // 2, 0)) + list(range(1, n_active // 2 + 1))

    data_indices = []
    pilot_indices = []

    for i, sc in enumerate(active_sc):
        fft_idx = sc % n_fft
        if i % pilot_spacing == 0:
            pilot_indices.append(fft_idx)
        else:
            data_indices.append(fft_idx)

    return data_indices, pilot_indices, active_sc


def ofdm_modulate(data_symbols, pilot_value, n_fft, data_indices, pilot_indices, cp_length):
    """
    OFDM modulate: map symbols to subcarriers, IFFT, add cyclic prefix.

    Args:
        data_symbols: 1D array of QAM symbols for data subcarriers
        pilot_value: complex value for all pilot subcarriers
        n_fft: FFT size
        data_indices: FFT bin indices for data subcarriers
        pilot_indices: FFT bin indices for pilot subcarriers
        cp_length: cyclic prefix length in samples

    Returns:
        tx_signal: time-domain OFDM symbol with CP, shape (n_fft + cp_length,)
        freq_domain: frequency-domain symbol, shape (n_fft,)
    """
    X = np.zeros(n_fft, dtype=complex)

    for sym, idx in zip(data_symbols, data_indices):
        X[idx] = sym

    for idx in pilot_indices:
        X[idx] = pilot_value

    # IFFT with sqrt(N) scaling for unit-power normalization
    x = np.fft.ifft(X) * np.sqrt(n_fft)

    # Add cyclic prefix
    cp = x[-cp_length:]
    tx = np.concatenate([cp, x])

    return tx, X


def ofdm_demodulate(rx_signal, n_fft, cp_length, data_indices, pilot_indices):
    """
    OFDM demodulate: remove CP, FFT, extract symbols.

    Args:
        rx_signal: time-domain signal with CP
        n_fft: FFT size
        cp_length: cyclic prefix length
        data_indices: FFT bin indices for data subcarriers
        pilot_indices: FFT bin indices for pilot subcarriers

    Returns:
        data_symbols: received data symbols
        pilot_symbols: received pilot symbols
        freq_domain: full frequency-domain symbol
    """
    x = rx_signal[cp_length : cp_length + n_fft]

    # FFT with matching 1/sqrt(N) scaling
    X = np.fft.fft(x) / np.sqrt(n_fft)

    data_symbols = np.array([X[idx] for idx in data_indices])
    pilot_symbols = np.array([X[idx] for idx in pilot_indices])

    return data_symbols, pilot_symbols, X
