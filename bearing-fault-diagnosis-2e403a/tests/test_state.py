
import sys
import math
import numpy as np
import pytest

sys.path.insert(0, "/app")

from bearing_diagnostics import compute_defect_frequencies, envelope_spectrum, diagnose


# ---------------------------------------------------------------------------
# Synthetic signal generation for testing
# ---------------------------------------------------------------------------

def generate_bearing_fault_signal(
    fault_freq_hz,
    sample_rate,
    duration_sec,
    resonance_hz,
    snr_db=20,
    seed=42,
    am_freq_hz=None,
    amplitude=1.0,
    fixed_noise_std=None,
):
    """Create a synthetic bearing vibration signal with an embedded fault.

    The signal is a train of damped sinusoidal impulses at *fault_freq_hz*
    (exciting a structural resonance at *resonance_hz*) plus Gaussian noise.
    Setting *fault_freq_hz* to ``None`` returns pure noise (healthy bearing).
    """
    rng = np.random.RandomState(seed)
    n = int(duration_sec * sample_rate)
    t = np.arange(n) / sample_rate

    if fault_freq_hz is None:
        return rng.randn(n) * 0.1

    # Impulse response: damped sinusoid at resonance frequency
    decay_rate = 500.0
    ir_dur = min(0.008, 0.7 / fault_freq_hz)
    n_ir = max(int(ir_dur * sample_rate), 10)
    t_ir = np.arange(n_ir) / sample_rate
    h = np.exp(-decay_rate * t_ir) * np.sin(2 * np.pi * resonance_hz * t_ir)
    h_max = np.max(np.abs(h))
    if h_max > 0:
        h /= h_max

    # Impulse train at fault frequency
    period_samples = sample_rate / fault_freq_hz
    impulse_indices = np.round(np.arange(0, n, period_samples)).astype(int)
    impulse_indices = impulse_indices[impulse_indices < n]
    impulses = np.zeros(n)
    impulses[impulse_indices] = amplitude

    # Optional amplitude modulation (inner-race faults)
    if am_freq_hz is not None:
        am = 1.0 + 0.8 * np.cos(2 * np.pi * am_freq_hz * t)
        impulses *= am

    fault_signal = np.convolve(impulses, h, mode="same")

    # Add noise
    if fixed_noise_std is not None:
        noise = rng.randn(n) * fixed_noise_std
    else:
        sig_power = np.mean(fault_signal ** 2)
        noise_std = (
            np.sqrt(sig_power / (10 ** (snr_db / 10))) if sig_power > 0 else 0.01
        )
        noise = rng.randn(n) * noise_std

    return fault_signal + noise


# ===================================================================
# Defect-frequency computation tests
# ===================================================================

class TestDefectFrequencies:
    """Verify defect-frequency formulas against analytically-known values."""

    def test_nice_bearing(self):
        params = {
            "rd": 0.235, "pd": 1.245, "ne": 8,
            "ca_deg": 0.0, "outer_fixed": True,
        }
        r = compute_defect_frequencies(params, 25.0)
        assert abs(r["BPFO"] - 81.1245) < 0.01
        assert abs(r["BPFI"] - 118.8755) < 0.01
        assert abs(r["BSF"] - 127.728) < 0.05
        assert abs(r["FTF"] - 10.1406) < 0.01

    def test_skf6205_bearing(self):
        params = {
            "rd": 7.94, "pd": 39.04, "ne": 9,
            "ca_deg": 0.0, "outer_fixed": True,
        }
        r = compute_defect_frequencies(params, 29.17)
        assert abs(r["BPFO"] - 104.568) < 0.05
        assert abs(r["BPFI"] - 157.962) < 0.05
        assert abs(r["BSF"] - 137.493) < 0.15
        assert abs(r["FTF"] - 11.619) < 0.01

    def test_angled_bearing(self):
        params = {
            "rd": 5.0, "pd": 40.0, "ne": 12,
            "ca_deg": 15.0, "outer_fixed": True,
        }
        r = compute_defect_frequencies(params, 30.0)
        assert abs(r["BPFO"] - 158.267) < 0.05
        assert abs(r["BPFI"] - 201.733) < 0.05
        assert abs(r["BSF"] - 236.501) < 0.15
        assert abs(r["FTF"] - 13.189) < 0.01

    def test_inner_fixed_ftf(self):
        params = {
            "rd": 0.235, "pd": 1.245, "ne": 8,
            "ca_deg": 0.0, "outer_fixed": False,
        }
        r = compute_defect_frequencies(params, 25.0)
        assert abs(r["FTF"] - 14.8594) < 0.01
        # BPFO / BPFI / BSF are independent of which race is fixed
        assert abs(r["BPFO"] - 81.1245) < 0.01
        assert abs(r["BPFI"] - 118.8755) < 0.01

    def test_bpfo_bpfi_symmetry(self):
        """BPFO + BPFI must equal ne * shaft_hz for any geometry."""
        cases = [
            (0.235, 1.245, 8, 0.0),
            (7.94, 39.04, 9, 0.0),
            (5.0, 40.0, 12, 15.0),
        ]
        for rd, pd, ne, ca in cases:
            for shaft in [10.0, 25.0, 50.0]:
                params = {
                    "rd": rd, "pd": pd, "ne": ne,
                    "ca_deg": ca, "outer_fixed": True,
                }
                r = compute_defect_frequencies(params, shaft)
                expected = ne * shaft
                assert abs(r["BPFO"] + r["BPFI"] - expected) < 0.001, (
                    f"BPFO+BPFI={r['BPFO']+r['BPFI']}, expected {expected}"
                )


# ===================================================================
# Envelope-spectrum tests
# ===================================================================

class TestEnvelopeSpectrum:
    """Verify that envelope demodulation recovers modulation frequencies."""

    def test_am_demodulation(self):
        sr = 48828
        duration = 2.0
        t = np.arange(0, duration, 1.0 / sr)
        carrier_freq = 3000.0
        mod_freq = 80.0
        signal = (1 + 0.8 * np.cos(2 * np.pi * mod_freq * t)) * np.sin(
            2 * np.pi * carrier_freq * t
        )
        rng = np.random.RandomState(100)
        signal += rng.randn(len(t)) * 0.05

        freqs, psd = envelope_spectrum(signal, sr, 2500.0, 3500.0)

        # Dominant peak (above 10 Hz to skip DC leakage) must be near mod_freq
        valid = freqs > 10.0
        peak_idx = np.argmax(psd[valid])
        peak_freq = freqs[valid][peak_idx]
        assert abs(peak_freq - mod_freq) < 4.0, (
            f"Expected peak near {mod_freq} Hz, got {peak_freq} Hz"
        )

    def test_dual_modulation(self):
        sr = 48828
        duration = 3.0
        t = np.arange(0, duration, 1.0 / sr)
        carrier = 4000.0
        f1, f2 = 60.0, 130.0
        signal = (
            1
            + 0.5 * np.cos(2 * np.pi * f1 * t)
            + 0.5 * np.cos(2 * np.pi * f2 * t)
        ) * np.sin(2 * np.pi * carrier * t)
        rng = np.random.RandomState(101)
        signal += rng.randn(len(t)) * 0.03

        freqs, psd = envelope_spectrum(signal, sr, 3500.0, 4500.0)

        valid = freqs > 20.0
        psd_v = psd[valid]
        freqs_v = freqs[valid]

        mask1 = np.abs(freqs_v - f1) < 6.0
        mask2 = np.abs(freqs_v - f2) < 6.0
        assert np.any(mask1), "No frequency bins near f1"
        assert np.any(mask2), "No frequency bins near f2"

        peak1 = np.max(psd_v[mask1])
        peak2 = np.max(psd_v[mask2])
        median_psd = np.median(psd_v)
        assert peak1 > 3 * median_psd, "Peak at f1 not prominent"
        assert peak2 > 3 * median_psd, "Peak at f2 not prominent"


# ===================================================================
# Full diagnosis pipeline tests
# ===================================================================

class TestDiagnosis:
    """End-to-end diagnosis: synthetic fault signals → classification."""

    def test_outer_race_fault(self):
        params = {
            "rd": 0.235, "pd": 1.245, "ne": 8,
            "ca_deg": 0.0, "outer_fixed": True,
        }
        shaft_hz = 25.0
        bpfo = 81.1245
        signal = generate_bearing_fault_signal(
            fault_freq_hz=bpfo, sample_rate=48828, duration_sec=3.0,
            resonance_hz=3000, snr_db=20, seed=42,
        )
        result = diagnose(signal, 48828, params, shaft_hz)
        assert result["fault_type"] == "outer_race", (
            f"Expected outer_race, got {result['fault_type']}"
        )
        assert result["confidence"] > 0.2
        assert result["fault_frequency_hz"] is not None
        assert abs(result["fault_frequency_hz"] - bpfo) < 3.0

    def test_inner_race_fault(self):
        params = {
            "rd": 0.235, "pd": 1.245, "ne": 8,
            "ca_deg": 0.0, "outer_fixed": True,
        }
        shaft_hz = 25.0
        bpfi = 118.8755
        signal = generate_bearing_fault_signal(
            fault_freq_hz=bpfi, sample_rate=48828, duration_sec=3.0,
            resonance_hz=5000, snr_db=20, seed=43, am_freq_hz=shaft_hz,
        )
        result = diagnose(signal, 48828, params, shaft_hz)
        assert result["fault_type"] == "inner_race", (
            f"Expected inner_race, got {result['fault_type']}"
        )
        assert result["confidence"] > 0.2
        assert result["fault_frequency_hz"] is not None
        assert abs(result["fault_frequency_hz"] - bpfi) < 3.0

    def test_healthy_bearing(self):
        params = {
            "rd": 0.235, "pd": 1.245, "ne": 8,
            "ca_deg": 0.0, "outer_fixed": True,
        }
        signal = generate_bearing_fault_signal(
            fault_freq_hz=None, sample_rate=48828, duration_sec=3.0,
            resonance_hz=3000, seed=44,
        )
        result = diagnose(signal, 48828, params, 25.0)
        assert result["fault_type"] == "healthy", (
            f"Expected healthy, got {result['fault_type']}"
        )

    def test_rolling_element_fault(self):
        params = {
            "rd": 7.94, "pd": 39.04, "ne": 9,
            "ca_deg": 0.0, "outer_fixed": True,
        }
        shaft_hz = 29.17
        bsf = 137.493
        signal = generate_bearing_fault_signal(
            fault_freq_hz=bsf, sample_rate=48828, duration_sec=3.0,
            resonance_hz=8000, snr_db=20, seed=45,
        )
        result = diagnose(signal, 48828, params, shaft_hz)
        assert result["fault_type"] == "rolling_element", (
            f"Expected rolling_element, got {result['fault_type']}"
        )
        assert result["confidence"] > 0.2

    def test_outer_race_different_bearing(self):
        params = {
            "rd": 5.0, "pd": 40.0, "ne": 12,
            "ca_deg": 15.0, "outer_fixed": True,
        }
        shaft_hz = 30.0
        bpfo = 158.267
        signal = generate_bearing_fault_signal(
            fault_freq_hz=bpfo, sample_rate=48828, duration_sec=3.0,
            resonance_hz=6000, snr_db=18, seed=46,
        )
        result = diagnose(signal, 48828, params, shaft_hz)
        assert result["fault_type"] == "outer_race", (
            f"Expected outer_race, got {result['fault_type']}"
        )

    def test_severity_monotonic(self):
        """Severity must increase with fault amplitude under identical noise."""
        params = {
            "rd": 0.235, "pd": 1.245, "ne": 8,
            "ca_deg": 0.0, "outer_fixed": True,
        }
        shaft_hz = 25.0
        bpfo = 81.1245
        severities = []
        for amp in [0.3, 0.7, 1.5]:
            signal = generate_bearing_fault_signal(
                fault_freq_hz=bpfo, sample_rate=48828, duration_sec=3.0,
                resonance_hz=3000, seed=50, amplitude=amp,
                fixed_noise_std=0.02,
            )
            result = diagnose(signal, 48828, params, shaft_hz)
            severities.append(result["severity"])

        for i in range(len(severities) - 1):
            assert severities[i] < severities[i + 1], (
                f"Severity not monotonically increasing: {severities}"
            )

    def test_diagnosis_output_structure(self):
        """Every required key must be present and well-typed."""
        params = {
            "rd": 0.235, "pd": 1.245, "ne": 8,
            "ca_deg": 0.0, "outer_fixed": True,
        }
        signal = generate_bearing_fault_signal(
            fault_freq_hz=81.12, sample_rate=48828, duration_sec=3.0,
            resonance_hz=3000, seed=60,
        )
        result = diagnose(signal, 48828, params, 25.0)

        assert "fault_type" in result
        assert result["fault_type"] in (
            "healthy", "outer_race", "inner_race", "rolling_element",
        )
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0
        assert "defect_frequencies" in result
        for k in ("BPFO", "BPFI", "BSF", "FTF"):
            assert k in result["defect_frequencies"]
        assert "detected_peaks_hz" in result
        assert isinstance(result["detected_peaks_hz"], list)
        assert "fault_frequency_hz" in result
        assert "severity" in result
        assert result["severity"] >= 0
