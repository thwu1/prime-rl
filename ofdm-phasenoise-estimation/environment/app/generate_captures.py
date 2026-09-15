#!/usr/bin/env python3
"""Generate OFDM IQ captures with varying oscillator phase noise.

This script is executed once at Docker build time and then deleted.
"""

import json
import os

import numpy as np


def _qam16_symbols(n, rng):
    """Return *n* random normalised 16-QAM symbols."""
    constellation = np.array([
        -3 - 3j, -3 - 1j, -3 + 3j, -3 + 1j,
        -1 - 3j, -1 - 1j, -1 + 3j, -1 + 1j,
        +3 - 3j, +3 - 1j, +3 + 3j, +3 + 1j,
        +1 - 3j, +1 - 1j, +1 + 3j, +1 + 1j,
    ]) / np.sqrt(10.0)
    return constellation[rng.integers(0, 16, n)]


def generate_capture(config, f_3dB, seed):
    """Generate one OFDM capture corrupted by phase noise + multipath + AWGN."""
    rng = np.random.default_rng(seed)

    N = config["n_fft"]
    Ncp = config["n_cp"]
    Nsym = config["n_symbols"]
    fs = config["sample_rate"]
    a0 = config["active_subcarrier_start"]
    a1 = config["active_subcarrier_end"]
    na = config["n_active"]
    psp = config["pilot_spacing"]
    pv = config["pilot_value_real"] + 1j * config["pilot_value_imag"]
    snr_db = config["snr_db"]

    pilots = list(range(0, na, psp))

    # ---- Transmit symbols ----
    tx_freq = np.zeros((Nsym, N), dtype=np.complex128)
    for m in range(Nsym):
        data = _qam16_symbols(na, rng)
        for pi in pilots:
            data[pi] = pv
        tx_freq[m, a0:a1] = data

    # ---- IFFT + CP ----
    tx_time = np.fft.ifft(tx_freq, axis=1)
    tx_cp = np.concatenate([tx_time[:, -Ncp:], tx_time], axis=1)
    tx_stream = tx_cp.flatten()

    # ---- Multipath channel (5-tap Rayleigh) ----
    n_taps = 5
    h = (rng.normal(0, 1, n_taps) + 1j * rng.normal(0, 1, n_taps)) / np.sqrt(2 * n_taps)
    rx_stream = np.convolve(tx_stream, h)[:len(tx_stream)]

    # ---- Wiener phase noise ----
    sigma_w = np.sqrt(2.0 * np.pi * f_3dB / fs)
    phase = np.cumsum(rng.normal(0, sigma_w, len(rx_stream)))
    rx_stream = rx_stream * np.exp(1j * phase)

    # ---- AWGN ----
    sig_power = np.mean(np.abs(rx_stream) ** 2)
    noise_power = sig_power / 10.0 ** (snr_db / 10.0)
    noise = np.sqrt(noise_power / 2.0) * (
        rng.normal(0, 1, len(rx_stream))
        + 1j * rng.normal(0, 1, len(rx_stream))
    )
    rx_stream = rx_stream + noise

    return rx_stream.astype(np.complex64)


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    os.makedirs("/app/captures", exist_ok=True)

    # Phase-noise 3-dB bandwidths (Hz) — increasing severity
    bandwidths = [100.0, 300.0, 800.0, 1500.0, 3000.0]
    seeds = [10001, 20002, 30003, 40004, 50005]

    for idx, (bw, sd) in enumerate(zip(bandwidths, seeds)):
        cap = generate_capture(config, bw, sd)
        out = f"/app/captures/capture_{idx}.npy"
        np.save(out, cap)
        print(f"  capture_{idx}: f_3dB = {bw:>7.1f} Hz  seed = {sd}")

    print("Capture generation complete.")


if __name__ == "__main__":
    main()
