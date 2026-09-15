
import pytest
import numpy as np
import json
import sys
import os

sys.path.insert(0, "/app/src")


class TestResultsStructure:
    """Verify results.json exists with all required keys and correct types."""

    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json not found"

    def test_results_has_required_keys(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        required_keys = [
            "evm_percent_no_correction",
            "evm_percent_cpe_corrected",
            "evm_db_no_correction",
            "evm_db_cpe_corrected",
            "cpe_variance_contribution",
            "ici_variance_contribution",
            "integrated_phase_noise_dBc",
            "mean_cpe_degrees",
            "phase_noise_psd_check",
        ]
        for key in required_keys:
            assert key in results, f"Missing key: {key}"

    def test_results_types(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        assert isinstance(results["evm_percent_no_correction"], (int, float))
        assert isinstance(results["evm_percent_cpe_corrected"], (int, float))
        assert isinstance(results["evm_db_no_correction"], (int, float))
        assert isinstance(results["evm_db_cpe_corrected"], (int, float))
        assert isinstance(results["cpe_variance_contribution"], (int, float))
        assert isinstance(results["ici_variance_contribution"], (int, float))
        assert isinstance(results["integrated_phase_noise_dBc"], (int, float))
        assert isinstance(results["mean_cpe_degrees"], (int, float))
        assert isinstance(results["phase_noise_psd_check"], dict)


class TestResultsPhysics:
    """Verify results satisfy physical constraints."""

    @pytest.fixture(autouse=True)
    def load_results(self):
        with open("/app/results.json") as f:
            self.results = json.load(f)

    def test_evm_positive_and_bounded(self):
        assert 0.1 < self.results["evm_percent_no_correction"] < 30.0, (
            f"EVM {self.results['evm_percent_no_correction']}% outside reasonable range"
        )
        assert 0.01 < self.results["evm_percent_cpe_corrected"] < 30.0

    def test_evm_db_consistent_with_percent(self):
        evm_pct = self.results["evm_percent_no_correction"]
        evm_db = self.results["evm_db_no_correction"]
        expected_db = 20 * np.log10(evm_pct / 100.0)
        assert abs(evm_db - expected_db) < 0.5, (
            f"EVM dB {evm_db} inconsistent with {evm_pct}% (expected {expected_db:.1f})"
        )

    def test_cpe_correction_reduces_evm(self):
        assert self.results["evm_percent_cpe_corrected"] < self.results["evm_percent_no_correction"], (
            "CPE correction must reduce EVM"
        )

    def test_decomposition_sums_to_one(self):
        cpe_frac = self.results["cpe_variance_contribution"]
        ici_frac = self.results["ici_variance_contribution"]
        assert 0.0 <= cpe_frac <= 1.0
        assert 0.0 <= ici_frac <= 1.0
        assert abs(cpe_frac + ici_frac - 1.0) < 0.02, (
            f"CPE ({cpe_frac}) + ICI ({ici_frac}) should sum to ~1.0"
        )

    def test_mean_cpe_positive(self):
        assert self.results["mean_cpe_degrees"] > 0

    def test_integrated_phase_noise_reasonable(self):
        # For the given PSD (-60 to -130 dBc/Hz), integrated phase noise
        # should be roughly -20 to -35 dBc
        ipn = self.results["integrated_phase_noise_dBc"]
        assert -50 < ipn < -10, f"Integrated phase noise {ipn} dBc out of range"


class TestPhaseNoiseGenerator:
    """Test the phase noise synthesis module."""

    def test_output_shape_and_type(self):
        from phase_noise import generate_phase_noise

        psd_bp = [[1000, -60], [10000, -80], [100000, -100]]
        N = 2**16
        fs = 30.72e6
        pn = generate_phase_noise(psd_bp, N, fs, seed=123)
        assert pn.shape == (N,), f"Expected shape ({N},), got {pn.shape}"
        assert pn.dtype in [np.float64, np.float32], f"Expected float, got {pn.dtype}"

    def test_zero_mean(self):
        from phase_noise import generate_phase_noise

        psd_bp = [[1000, -60], [10000, -80], [100000, -100]]
        N = 2**17
        fs = 30.72e6
        pn = generate_phase_noise(psd_bp, N, fs, seed=456)
        assert abs(np.mean(pn)) < 0.05, f"Phase noise mean {np.mean(pn):.4f} too far from 0"

    def test_variance_matches_integrated_psd(self):
        from phase_noise import generate_phase_noise

        psd_bp = [[1000, -60], [10000, -80], [100000, -100], [1000000, -120], [10000000, -130]]
        N = 2**18
        fs = 30.72e6
        pn = generate_phase_noise(psd_bp, N, fs, seed=789)
        var = np.var(pn)
        # Analytical integrated PSD ~ 2e-3 rad^2 (within factor 5)
        assert 1e-4 < var < 5e-2, f"Phase noise variance {var:.2e} outside expected range"

    def test_psd_decreasing_with_frequency(self):
        from phase_noise import generate_phase_noise
        from scipy.signal import welch

        psd_bp = [[1000, -60], [10000, -80], [100000, -100], [1000000, -120], [10000000, -130]]
        N = 2**18
        fs = 30.72e6
        pn = generate_phase_noise(psd_bp, N, fs, seed=321)
        # Use nperseg=2**14 for ~1875 Hz frequency resolution
        freqs, psd = welch(pn, fs=fs, nperseg=2**14, return_onesided=True, scaling="density")
        psd_dB = 10 * np.log10(psd + 1e-30)

        idx_5k = np.argmin(np.abs(freqs - 5000))
        idx_500k = np.argmin(np.abs(freqs - 500000))
        # PSD at 500 kHz should be well below PSD at 5 kHz (~40 dB expected)
        assert psd_dB[idx_500k] < psd_dB[idx_5k] - 15, (
            f"PSD at 500kHz ({psd_dB[idx_500k]:.1f}) should be >15dB below 5kHz ({psd_dB[idx_5k]:.1f})"
        )

    def test_reproducibility(self):
        from phase_noise import generate_phase_noise

        psd_bp = [[1000, -80], [10000, -100]]
        pn1 = generate_phase_noise(psd_bp, 10000, 30.72e6, seed=42)
        pn2 = generate_phase_noise(psd_bp, 10000, 30.72e6, seed=42)
        assert np.allclose(pn1, pn2), "Same seed must produce identical output"
        pn3 = generate_phase_noise(psd_bp, 10000, 30.72e6, seed=43)
        assert not np.allclose(pn1, pn3), "Different seeds must produce different output"


class TestOFDM:
    """Test the OFDM modulation/demodulation chain."""

    def test_constellation_size_and_power(self):
        from ofdm import get_constellation

        const = get_constellation("64QAM")
        assert len(const) == 64, f"64QAM should have 64 points, got {len(const)}"
        avg_power = np.mean(np.abs(const) ** 2)
        assert abs(avg_power - 1.0) < 0.01, f"Average power {avg_power} should be ~1.0"

    def test_subcarrier_allocation(self):
        from ofdm import get_subcarrier_allocation

        data_idx, pilot_idx, active_sc = get_subcarrier_allocation(1024, 600, 4)
        # Total active = data + pilots = 600
        assert len(data_idx) + len(pilot_idx) == 600
        # Pilots should be every 4th active subcarrier
        assert len(pilot_idx) == 150
        assert len(data_idx) == 450
        # DC (FFT bin 0) should not be in any index
        assert 0 not in data_idx
        assert 0 not in pilot_idx

    def test_lossless_roundtrip(self):
        from ofdm import get_constellation, get_subcarrier_allocation, ofdm_modulate, ofdm_demodulate
        from evm_analyzer import compute_evm

        n_fft = 256
        n_active = 128
        cp_length = 16
        pilot_spacing = 4

        constellation = get_constellation("64QAM")
        data_idx, pilot_idx, _ = get_subcarrier_allocation(n_fft, n_active, pilot_spacing)

        rng = np.random.default_rng(42)
        data_syms = constellation[rng.integers(0, len(constellation), len(data_idx))]

        tx_signal, tx_freq = ofdm_modulate(data_syms, 1.0 + 0j, n_fft, data_idx, pilot_idx, cp_length)
        rx_data, rx_pilots, _ = ofdm_demodulate(tx_signal, n_fft, cp_length, data_idx, pilot_idx)

        evm_lin, evm_pct, _ = compute_evm(data_syms, rx_data)
        assert evm_pct < 0.01, f"Roundtrip EVM should be ~0, got {evm_pct:.4f}%"

    def test_pilots_recovered(self):
        from ofdm import get_constellation, get_subcarrier_allocation, ofdm_modulate, ofdm_demodulate

        n_fft = 256
        n_active = 128
        cp_length = 16
        pilot_spacing = 4

        constellation = get_constellation("64QAM")
        data_idx, pilot_idx, _ = get_subcarrier_allocation(n_fft, n_active, pilot_spacing)

        rng = np.random.default_rng(55)
        data_syms = constellation[rng.integers(0, len(constellation), len(data_idx))]
        pilot_val = 1.0 + 0j

        tx_signal, _ = ofdm_modulate(data_syms, pilot_val, n_fft, data_idx, pilot_idx, cp_length)
        _, rx_pilots, _ = ofdm_demodulate(tx_signal, n_fft, cp_length, data_idx, pilot_idx)

        for rp in rx_pilots:
            assert abs(rp - pilot_val) < 1e-10, f"Pilot not recovered: {rp}"


class TestEVMAnalyzer:
    """Test EVM computation and CPE estimation."""

    def test_evm_zero_for_identical(self):
        from evm_analyzer import compute_evm

        tx = np.array([1 + 0j, 0 + 1j, -1 + 0j, 0 - 1j])
        _, evm_pct, _ = compute_evm(tx, tx.copy())
        assert evm_pct < 0.001

    def test_evm_known_error(self):
        from evm_analyzer import compute_evm

        tx = np.array([1 + 0j, 0 + 1j, -1 + 0j, 0 - 1j])
        noise = 0.1 * np.array([1 + 1j, -1 + 1j, 1 - 1j, -1 - 1j])
        rx = tx + noise
        _, evm_pct, _ = compute_evm(tx, rx)
        # RMS error = 0.1*sqrt(2), RMS ref = 1 => EVM = 0.1414 = 14.14%
        assert abs(evm_pct - 14.14) < 1.0, f"Expected ~14.14%, got {evm_pct:.2f}%"

    def test_cpe_estimation_known_rotation(self):
        from ofdm import get_constellation, get_subcarrier_allocation, ofdm_modulate, ofdm_demodulate
        from evm_analyzer import estimate_cpe, correct_cpe, compute_evm

        n_fft = 256
        n_active = 128
        cp_length = 16
        pilot_spacing = 4

        constellation = get_constellation("64QAM")
        data_idx, pilot_idx, _ = get_subcarrier_allocation(n_fft, n_active, pilot_spacing)

        rng = np.random.default_rng(99)
        data_syms = constellation[rng.integers(0, len(constellation), len(data_idx))]
        pilot_val = 1.0 + 0j

        tx_signal, _ = ofdm_modulate(data_syms, pilot_val, n_fft, data_idx, pilot_idx, cp_length)

        # Apply known constant phase rotation (pure CPE, no ICI)
        known_phase = 0.15  # radians
        rx_signal = tx_signal * np.exp(1j * known_phase)

        rx_data, rx_pilots, _ = ofdm_demodulate(rx_signal, n_fft, cp_length, data_idx, pilot_idx)
        tx_pilots = np.full(len(pilot_idx), pilot_val)

        estimated_cpe = estimate_cpe(rx_pilots, tx_pilots)
        assert abs(estimated_cpe - known_phase) < 0.01, (
            f"CPE estimate {estimated_cpe:.4f} should match {known_phase:.4f}"
        )

        # After correction, EVM should be near zero
        corrected = correct_cpe(rx_data, estimated_cpe)
        _, evm_pct, _ = compute_evm(data_syms, corrected)
        assert evm_pct < 0.1, f"EVM after CPE correction should be ~0, got {evm_pct:.4f}%"

    def test_cpe_estimation_negative_rotation(self):
        from evm_analyzer import estimate_cpe

        pilot_val = 1.0 + 0j
        phase = -0.25
        rx_pilots = np.full(20, pilot_val) * np.exp(1j * phase)
        tx_pilots = np.full(20, pilot_val)
        est = estimate_cpe(rx_pilots, tx_pilots)
        assert abs(est - phase) < 0.01


class TestMeasurePSD:
    """Test that the PSD measurement utility works."""

    def test_measure_psd_exists_and_returns_tuple(self):
        from phase_noise import measure_psd

        signal = np.random.default_rng(10).standard_normal(8192)
        freqs, psd_dB = measure_psd(signal, 1000.0)
        assert len(freqs) == len(psd_dB)
        assert len(freqs) > 0
