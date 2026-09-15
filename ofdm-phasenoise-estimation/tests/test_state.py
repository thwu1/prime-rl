"""Verification tests for OFDM phase noise estimation and compensation.

Tests generate their own OFDM signals with known phase-noise parameters
(different from the task captures) and verify that the agent's algorithms
produce correct results.
"""


import json
import os
import sys

import numpy as np
import pytest

# Make the framework importable
sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Helper: generate an independent OFDM test signal
# ---------------------------------------------------------------------------

_QAM16 = np.array([
    -3 - 3j, -3 - 1j, -3 + 3j, -3 + 1j,
    -1 - 3j, -1 - 1j, -1 + 3j, -1 + 1j,
    +3 - 3j, +3 - 1j, +3 + 3j, +3 + 1j,
    +1 - 3j, +1 - 1j, +1 + 3j, +1 + 1j,
]) / np.sqrt(10.0)


def _generate_test_signal(f_3dB: float, seed: int, n_symbols: int = 100):
    """Return (rx_stream, true_cpe, config) for a test OFDM signal."""
    rng = np.random.default_rng(seed)

    N = 1024
    Ncp = 72
    fs = 30.72e6
    na = 600
    a0, a1 = 212, 812
    psp = 6
    pv = 1.0 + 0j
    snr_db = 30.0

    pilots = list(range(0, na, psp))

    # TX
    tx_freq = np.zeros((n_symbols, N), dtype=np.complex128)
    for m in range(n_symbols):
        data = _QAM16[rng.integers(0, 16, na)]
        for pi in pilots:
            data[pi] = pv
        tx_freq[m, a0:a1] = data

    tx_time = np.fft.ifft(tx_freq, axis=1)
    tx_cp = np.concatenate([tx_time[:, -Ncp:], tx_time], axis=1)
    tx_stream = tx_cp.flatten()

    # Channel (3-tap)
    h = (rng.normal(0, 1, 3) + 1j * rng.normal(0, 1, 3)) / np.sqrt(6)
    rx_stream = np.convolve(tx_stream, h)[:len(tx_stream)]

    # Phase noise
    sigma_w = np.sqrt(2.0 * np.pi * f_3dB / fs)
    phase = np.cumsum(rng.normal(0, sigma_w, len(rx_stream)))
    rx_stream = rx_stream * np.exp(1j * phase)

    # True CPE per symbol (mean phase over FFT window)
    true_cpe = np.zeros(n_symbols)
    for m in range(n_symbols):
        start = m * (N + Ncp) + Ncp
        true_cpe[m] = np.mean(phase[start : start + N])

    # AWGN
    sp = np.mean(np.abs(rx_stream) ** 2)
    np_ = sp / 10.0 ** (snr_db / 10.0)
    noise = np.sqrt(np_ / 2) * (
        rng.normal(0, 1, len(rx_stream)) + 1j * rng.normal(0, 1, len(rx_stream))
    )
    rx_stream = rx_stream + noise

    config = {
        "n_fft": N,
        "n_cp": Ncp,
        "sample_rate": fs,
        "n_active": na,
        "active_subcarrier_start": a0,
        "active_subcarrier_end": a1,
        "pilot_spacing": psp,
        "pilot_value_real": 1.0,
        "pilot_value_imag": 0.0,
        "snr_db": snr_db,
        "modulation": "16QAM",
        "n_symbols": n_symbols,
    }
    return rx_stream.astype(np.complex64), true_cpe, config


def _pipeline_to_eq(rx_stream, config):
    """Run demod -> channel est -> equalization; return (rx_eq, pilots, pv)."""
    from framework.ofdm_demod import remove_cp, fft_demod, extract_active
    from framework.channel_est import estimate_channel
    from framework.equalizer import zf_equalize

    pilots = list(range(0, config["n_active"], config["pilot_spacing"]))
    pv = config["pilot_value_real"] + 1j * config["pilot_value_imag"]

    rx_time = remove_cp(rx_stream, config["n_fft"], config["n_cp"],
                        config["n_symbols"])
    rx_freq = fft_demod(rx_time)
    rx_active = extract_active(rx_freq, config["active_subcarrier_start"],
                               config["active_subcarrier_end"])
    H = estimate_channel(rx_active, pilots, pv)
    rx_eq = zf_equalize(rx_active, H)
    return rx_eq, pilots, pv


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCPEEstimation:
    """CPE estimation must correlate with the true CPE."""

    def test_cpe_correlation(self):
        from framework.phase_noise import estimate_cpe

        rx, true_cpe, cfg = _generate_test_signal(750.0, 99999)
        rx_eq, pilots, pv = _pipeline_to_eq(rx, cfg)

        cpe = estimate_cpe(rx_eq, pilots, pv)

        assert cpe is not None, "estimate_cpe returned None"
        assert len(cpe) == cfg["n_symbols"], (
            f"CPE length {len(cpe)} != {cfg['n_symbols']}"
        )

        # Unwrap both sequences to handle phase wrapping before correlation
        cpe_uw = np.unwrap(cpe)
        true_uw = np.unwrap(true_cpe)

        c1 = cpe_uw - np.mean(cpe_uw)
        c2 = true_uw - np.mean(true_uw)
        corr = np.dot(c1, c2) / (np.linalg.norm(c1) * np.linalg.norm(c2) + 1e-30)
        assert corr > 0.90, f"CPE correlation {corr:.3f} < 0.90"


class TestCPECompensation:
    """CPE compensation must measurably reduce EVM."""

    def test_evm_improves(self):
        from framework.phase_noise import estimate_cpe, compensate_cpe
        from framework.metrics import compute_evm_db

        rx, _, cfg = _generate_test_signal(750.0, 99999)
        rx_eq, pilots, pv = _pipeline_to_eq(rx, cfg)

        evm_before = compute_evm_db(rx_eq, cfg["modulation"], pilots)

        cpe = estimate_cpe(rx_eq, pilots, pv)
        rx_comp = compensate_cpe(rx_eq, cpe)

        evm_after = compute_evm_db(rx_comp, cfg["modulation"], pilots)

        improvement = evm_before - evm_after  # positive = better
        assert improvement > 2.0, (
            f"EVM improvement {improvement:.2f} dB < 2 dB "
            f"(before={evm_before:.2f}, after={evm_after:.2f})"
        )


class TestBandwidthEstimation:
    """Bandwidth estimates must be within 50 % of the true value."""

    @pytest.mark.parametrize(
        "true_bw, seed",
        [(750.0, 99999), (500.0, 12345)],
        ids=["bw_750Hz", "bw_500Hz"],
    )
    def test_bandwidth_accuracy(self, true_bw, seed):
        from framework.phase_noise import estimate_cpe, estimate_pn_bandwidth

        rx, _, cfg = _generate_test_signal(true_bw, seed)
        rx_eq, pilots, pv = _pipeline_to_eq(rx, cfg)

        cpe = estimate_cpe(rx_eq, pilots, pv)
        est = estimate_pn_bandwidth(cpe, cfg)

        assert est is not None, "estimate_pn_bandwidth returned None"
        assert est > 0, f"Estimated bandwidth {est} <= 0"

        rel_err = abs(est - true_bw) / true_bw
        assert rel_err < 0.50, (
            f"Bandwidth estimate {est:.1f} Hz vs true {true_bw:.1f} Hz "
            f"(error {rel_err * 100:.1f} %)"
        )


class TestResultsJSON:
    """Verify /app/results.json format and consistency."""

    @pytest.fixture()
    def results(self):
        path = "/app/results.json"
        assert os.path.exists(path), "results.json not found at /app/results.json"
        with open(path) as f:
            return json.load(f)

    def test_all_captures_present(self, results):
        for i in range(5):
            key = f"capture_{i}"
            assert key in results, f"Missing key: {key}"
            for field in ("evm_before_cpe_db", "evm_after_cpe_db",
                          "estimated_pn_bandwidth_hz"):
                assert field in results[key], f"Missing field {field} in {key}"

    def test_evm_improvement(self, results):
        for i in range(5):
            r = results[f"capture_{i}"]
            assert r["evm_after_cpe_db"] < r["evm_before_cpe_db"], (
                f"capture_{i}: EVM after ({r['evm_after_cpe_db']:.2f} dB) "
                f"not better than before ({r['evm_before_cpe_db']:.2f} dB)"
            )

    def test_bandwidth_range(self, results):
        for i in range(5):
            bw = results[f"capture_{i}"]["estimated_pn_bandwidth_hz"]
            assert 10 < bw < 50000, (
                f"capture_{i}: bandwidth {bw:.1f} Hz outside [10, 50000]"
            )

    def test_bandwidth_ordering(self, results):
        bws = [results[f"capture_{i}"]["estimated_pn_bandwidth_hz"]
               for i in range(5)]
        assert bws[4] > bws[0] * 2, (
            f"capture_4 BW ({bws[4]:.1f}) should be much larger than "
            f"capture_0 BW ({bws[0]:.1f})"
        )
