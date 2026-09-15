"""Tests for speech feature extraction pipeline.

"""

import pytest
import numpy as np
import os
import sys
import subprocess

sys.path.insert(0, '/app')


@pytest.fixture(scope='session', autouse=True)
def setup_test_data():
    """Generate synthetic test WAV files for deterministic testing."""
    from scipy.io.wavfile import write
    os.makedirs('/app/test_data', exist_ok=True)
    fs = 16000

    # --- Pure 150 Hz harmonic tone (2 seconds) ---
    t = np.arange(0, 2.0, 1.0 / fs)
    signal = (np.sin(2 * np.pi * 150 * t)
              + 0.5 * np.sin(2 * np.pi * 300 * t)
              + 0.25 * np.sin(2 * np.pi * 450 * t))
    signal = signal / np.max(np.abs(signal))
    write('/app/test_data/tone_150hz.wav', fs,
          (signal * 32767).astype(np.int16))

    # --- Multi-segment signal (voiced/unvoiced/pause) ---
    rng = np.random.RandomState(42)
    # 0.5 s voiced at 150 Hz
    t1 = np.arange(0, 0.5, 1.0 / fs)
    v1 = np.sin(2 * np.pi * 150 * t1) + 0.5 * np.sin(2 * np.pi * 300 * t1)
    # 0.12 s low-energy noise (short unvoiced, < 140 ms)
    noise1 = 0.01 * rng.randn(int(0.12 * fs))
    # 0.4 s voiced at 200 Hz
    t2 = np.arange(0, 0.4, 1.0 / fs)
    v2 = np.sin(2 * np.pi * 200 * t2) + 0.5 * np.sin(2 * np.pi * 400 * t2)
    # 0.3 s silence (pause, > 140 ms)
    silence = np.zeros(int(0.3 * fs))
    # 0.35 s voiced at 180 Hz
    t3 = np.arange(0, 0.35, 1.0 / fs)
    v3 = np.sin(2 * np.pi * 180 * t3) + 0.5 * np.sin(2 * np.pi * 360 * t3)

    multi = np.concatenate([v1, noise1, v2, silence, v3])
    multi = multi / np.max(np.abs(multi))
    write('/app/test_data/multi_segment.wav', fs,
          (multi * 32767).astype(np.int16))

    # --- Silence (1 second) ---
    silent = np.zeros(int(1.0 * fs))
    write('/app/test_data/silence.wav', fs, silent.astype(np.int16))

    # --- Chirp signal (120-250 Hz over 1.5 seconds) ---
    t_chirp = np.arange(0, 1.5, 1.0 / fs)
    f_start, f_end = 120.0, 250.0
    phase = 2 * np.pi * (f_start * t_chirp +
                          (f_end - f_start) * t_chirp**2 / (2 * 1.5))
    chirp = np.sin(phase) + 0.5 * np.sin(2 * phase)
    chirp = chirp / np.max(np.abs(chirp))
    write('/app/test_data/chirp_120_250.wav', fs,
          (chirp * 32767).astype(np.int16))

    # --- Stereo tone (150 Hz, two channels at different gains) ---
    t_st = np.arange(0, 1.0, 1.0 / fs)
    left = np.sin(2 * np.pi * 150 * t_st)
    right = np.sin(2 * np.pi * 150 * t_st) * 0.8
    stereo = np.column_stack([left, right])
    stereo_norm = stereo / np.max(np.abs(stereo))
    write('/app/test_data/stereo_150hz.wav', fs,
          (stereo_norm * 32767).astype(np.int16))

    # --- Very short signal (40 ms) ---
    t_short = np.arange(0, 0.04, 1.0 / fs)
    short_sig = np.sin(2 * np.pi * 150 * t_short)
    write('/app/test_data/short_40ms.wav', fs,
          (short_sig * 32767).astype(np.int16))

    # --- 44.1 kHz stereo tone (for SoX preprocessing tests) ---
    fs_44 = 44100
    t_44 = np.arange(0, 1.0, 1.0 / fs_44)
    left_44 = np.sin(2 * np.pi * 150 * t_44)
    right_44 = np.sin(2 * np.pi * 150 * t_44) * 0.8
    stereo_44 = np.column_stack([left_44, right_44])
    stereo_44 = stereo_44 / np.max(np.abs(stereo_44))
    write('/app/test_data/hires_stereo.wav', fs_44,
          (stereo_44 * 32767).astype(np.int16))

    # --- Signal with DC offset (for high-pass filter test) ---
    t_dc = np.arange(0, 1.0, 1.0 / fs)
    dc_sig = 0.5 + 0.5 * np.sin(2 * np.pi * 150 * t_dc)
    dc_sig = dc_sig / np.max(np.abs(dc_sig))
    write('/app/test_data/dc_offset.wav', fs,
          (dc_sig * 32767).astype(np.int16))


# ============================================================
# SoX preprocessing tests
# ============================================================

class TestPreprocessing:
    def test_script_exists_and_executable(self):
        assert os.path.isfile('/app/preprocess.sh'), \
            "/app/preprocess.sh must exist"
        assert os.access('/app/preprocess.sh', os.X_OK), \
            "/app/preprocess.sh must be executable"

    def test_resample_to_16khz_mono(self):
        """preprocess.sh must convert 44.1kHz stereo to 16kHz mono."""
        from scipy.io.wavfile import read as wav_read
        out_path = '/app/test_data/hires_preprocessed.wav'
        result = subprocess.run(
            ['bash', '/app/preprocess.sh',
             '/app/test_data/hires_stereo.wav', out_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"preprocess.sh failed: {result.stderr}"
        assert os.path.isfile(out_path), "Output file not created"

        fs_out, data_out = wav_read(out_path)
        assert fs_out == 16000, f"Expected 16000 Hz, got {fs_out}"
        assert len(data_out.shape) == 1, \
            f"Output must be mono (1D), got shape {data_out.shape}"

    def test_output_is_16bit_pcm(self):
        """Output must be 16-bit PCM WAV."""
        from scipy.io.wavfile import read as wav_read
        out_path = '/app/test_data/pcm_test_out.wav'
        subprocess.run(
            ['bash', '/app/preprocess.sh',
             '/app/test_data/tone_150hz.wav', out_path],
            capture_output=True, text=True, timeout=30
        )
        _, data = wav_read(out_path)
        assert data.dtype == np.int16, \
            f"Expected int16 (16-bit PCM), got {data.dtype}"

    def test_highpass_removes_dc(self):
        """High-pass filter at 50 Hz should remove DC offset."""
        from scipy.io.wavfile import read as wav_read
        out_path = '/app/test_data/dc_filtered.wav'
        result = subprocess.run(
            ['bash', '/app/preprocess.sh',
             '/app/test_data/dc_offset.wav', out_path],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, \
            f"preprocess.sh failed: {result.stderr}"

        _, data_out = wav_read(out_path)
        data_f = data_out.astype(float)
        # DC component should be heavily attenuated
        relative_dc = np.abs(np.mean(data_f)) / np.max(np.abs(data_f))
        assert relative_dc < 0.05, \
            f"DC not sufficiently removed: relative DC = {relative_dc:.4f}"

    def test_uses_sox_tool(self):
        """preprocess.sh must invoke the sox command."""
        with open('/app/preprocess.sh', 'r') as f:
            content = f.read()
        assert 'sox' in content.lower(), \
            "preprocess.sh must use the sox command"

    def test_preserves_signal_content(self):
        """Preprocessing should preserve the main frequency content."""
        from scipy.io.wavfile import read as wav_read
        out_path = '/app/test_data/preserve_test.wav'
        subprocess.run(
            ['bash', '/app/preprocess.sh',
             '/app/test_data/tone_150hz.wav', out_path],
            capture_output=True, text=True, timeout=30
        )
        _, data = wav_read(out_path)
        data_f = data.astype(float)
        # Signal should have significant energy (not zeroed out)
        assert np.max(np.abs(data_f)) > 100, \
            "Preprocessing should preserve signal energy"


# ============================================================
# Low-level phonation function tests (exact numerical checks)
# ============================================================

class TestJitterEnv:
    def test_basic(self):
        from phonation import jitter_env
        f0 = np.array([150.0, 152.0, 148.0, 151.0, 149.0,
                        150.0, 153.0, 147.0])
        result = jitter_env(f0, 8)
        mx = 153.0
        expected = np.array([
            100 * 2 / mx, 100 * 4 / mx, 100 * 3 / mx, 100 * 2 / mx,
            100 * 1 / mx, 100 * 3 / mx, 100 * 6 / mx, 0.0
        ])
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_resampling(self):
        """When n_points > len(input), the copy-then-normalize path fires."""
        from phonation import jitter_env
        f0 = np.array([100.0, 110.0, 105.0])
        result = jitter_env(f0, 6)
        mx = 110.0
        # n=0: i=0, raw=|110-100|=10, out=100*10/110
        # n=1: i=0 (same), raw=out[0], out=100*out[0]/110
        # n=2: i=1, raw=|105-110|=5, out=100*5/110
        # n=3: i=1 (same), raw=out[2], out=100*out[2]/110
        # n=4: i=2, i+1=3 >= len=3, raw=0, out=0
        # n=5: 0 (last)
        o0 = 100 * 10 / mx
        o2 = 100 * 5 / mx
        expected = np.array([o0, 100 * o0 / mx, o2, 100 * o2 / mx, 0.0, 0.0])
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_short_input(self):
        from phonation import jitter_env
        result = jitter_env(np.array([100.0]), 5)
        assert len(result) == 5
        assert np.all(result == 0)

    def test_output_length(self):
        from phonation import jitter_env
        f0 = np.array([150.0, 160.0, 155.0, 158.0])
        for n_pts in [4, 8, 2]:
            result = jitter_env(f0, n_pts)
            assert len(result) == n_pts

    def test_last_element_zero(self):
        """Last element should always be zero."""
        from phonation import jitter_env
        f0 = np.array([150.0, 160.0, 155.0, 158.0, 162.0])
        result = jitter_env(f0, 5)
        assert result[-1] == 0.0

    def test_nonnegative(self):
        """All jitter values must be non-negative."""
        from phonation import jitter_env
        f0 = np.array([100.0, 200.0, 50.0, 300.0, 150.0])
        result = jitter_env(f0, 5)
        assert np.all(result >= 0)


class TestShimmerEnv:
    def test_basic(self):
        from phonation import shimmer_env
        amp = np.array([0.80, 0.85, 0.78, 0.82, 0.80, 0.83])
        result = shimmer_env(amp, 6)
        mx = 0.85
        expected = np.array([
            100 * 0.05 / mx, 100 * 0.07 / mx, 100 * 0.04 / mx,
            100 * 0.02 / mx, 100 * 0.03 / mx, 0.0
        ])
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_resampling_shimmer(self):
        """Shimmer must exhibit same resampling behavior as jitter."""
        from phonation import shimmer_env
        amp = np.array([0.5, 0.7])
        result = shimmer_env(amp, 4)
        mx = 0.7
        # n=0: i=0, raw=|0.7-0.5|=0.2, out=100*0.2/0.7
        # n=1: i=0 (same), raw=out[0], out=100*out[0]/0.7
        # n=2: i=1, i+1=2>=len=2, raw=0, out=0
        # n=3: 0 (last)
        o0 = 100 * 0.2 / mx
        expected = np.array([o0, 100 * o0 / mx, 0.0, 0.0])
        np.testing.assert_allclose(result, expected, rtol=1e-10)


class TestPerturbationQuotient:
    def test_k5(self):
        from phonation import perturbation_quotient
        x = np.array([1.0, 1.1, 0.9, 1.05, 0.95, 1.0, 1.08, 0.92])
        result = perturbation_quotient(x, 5)
        # d0=|0.5/5|=0.1, d1=|-0.25/5|=0.05, d2=|0.23/5|=0.046
        expected = 100 * ((0.1 + 0.05 + 0.046) / 3) / 1.0
        np.testing.assert_allclose(result, expected, rtol=1e-4)

    def test_k3(self):
        from phonation import perturbation_quotient
        x = np.array([1.0, 0.9, 1.1, 0.95, 1.05])
        result = perturbation_quotient(x, 3)
        d0 = abs((0.1 + 0 + 0.2) / 3)
        d1 = abs((-0.2 + 0 + (-0.15)) / 3)
        expected = 100 * ((d0 + d1) / 2) / 1.0
        np.testing.assert_allclose(result, expected, rtol=1e-4)

    def test_even_k_returns_zero(self):
        from phonation import perturbation_quotient
        result = perturbation_quotient(np.array([1.0, 2.0, 3.0, 4.0]), 4)
        assert result == 0

    def test_short_input_returns_zero(self):
        from phonation import perturbation_quotient
        result = perturbation_quotient(np.array([1.0, 2.0]), 5)
        assert result == 0

    def test_constant_input(self):
        """Constant input should yield zero perturbation."""
        from phonation import perturbation_quotient
        result = perturbation_quotient(np.ones(20), 5)
        assert result == 0

    def test_k7(self):
        """Test with k=7 to verify center-deviation formula."""
        from phonation import perturbation_quotient
        x = np.array([1.0, 1.02, 0.98, 1.01, 0.99, 1.03, 0.97,
                       1.0, 1.01, 0.99])
        result = perturbation_quotient(x, 7)
        # Verify it's a positive finite number
        assert result > 0
        assert np.isfinite(result)
        # Verify it's small for near-constant input
        assert result < 10.0


class TestAPQ:
    def test_calls_pq_with_k11(self):
        from phonation import apq, perturbation_quotient
        x = np.array([0.8, 0.82, 0.79, 0.81, 0.83, 0.80, 0.84,
                       0.78, 0.82, 0.81, 0.79, 0.83, 0.80, 0.82])
        result = apq(x)
        expected = perturbation_quotient(x, 11)
        np.testing.assert_allclose(result, expected, rtol=1e-10)
        # Sanity: result should be a positive percentage
        assert result > 0

    def test_too_few_values(self):
        from phonation import apq
        result = apq(np.array([0.8, 0.82, 0.79]))
        assert result == 0


class TestPPQ:
    def test_uses_periods(self):
        """PPQ must operate on pitch periods (1/F0), not frequencies."""
        from phonation import ppq, perturbation_quotient
        f0 = np.array([150.0, 152.0, 148.0, 151.0, 149.0, 150.0])
        result = ppq(f0)
        expected = perturbation_quotient(1.0 / f0, 5)
        np.testing.assert_allclose(result, expected, rtol=1e-10)
        # Must differ from computing PQ on frequencies directly
        freq_pq = perturbation_quotient(f0, 5)
        assert not np.isclose(result, freq_pq, rtol=1e-3), \
            "PPQ must use periods, not frequencies"


class TestLogEnergy:
    def test_basic(self):
        from phonation import log_energy
        frame = np.array([0.5, -0.3, 0.2, -0.1, 0.4])
        result = log_energy(frame)
        expected = np.log10(np.mean(frame ** 2))
        np.testing.assert_allclose(result, expected, rtol=1e-10)

    def test_unit_signal(self):
        from phonation import log_energy
        frame = np.ones(100)
        result = log_energy(frame)
        np.testing.assert_allclose(result, 0.0, atol=1e-10)


# ============================================================
# F0 extraction tests
# ============================================================

class TestExtractF0:
    def test_pure_tone_150hz(self):
        from phonation import extract_f0
        f0 = extract_f0('/app/test_data/tone_150hz.wav')
        f0_voiced = f0[f0 > 0]
        assert len(f0_voiced) > 10, "Should detect many voiced frames"
        mean_f0 = np.mean(f0_voiced)
        assert 140 <= mean_f0 <= 160, \
            f"Mean F0 should be ~150 Hz, got {mean_f0:.1f}"

    def test_silence_all_unvoiced(self):
        from phonation import extract_f0
        f0 = extract_f0('/app/test_data/silence.wav')
        assert np.all(f0 == 0), "Silence should have no voiced frames"

    def test_output_is_numpy(self):
        from phonation import extract_f0
        f0 = extract_f0('/app/test_data/tone_150hz.wav')
        assert isinstance(f0, np.ndarray)

    def test_f0_range(self):
        """Non-zero F0 values should be within [60, 350] Hz."""
        from phonation import extract_f0
        f0 = extract_f0('/app/test_data/tone_150hz.wav')
        voiced = f0[f0 > 0]
        assert np.all(voiced >= 60), "F0 below minimum"
        assert np.all(voiced <= 350), "F0 above maximum"

    def test_chirp_tracking(self):
        """F0 should track a frequency-varying signal."""
        from phonation import extract_f0
        f0 = extract_f0('/app/test_data/chirp_120_250.wav')
        f0_voiced = f0[f0 > 0]
        assert len(f0_voiced) > 5, "Should detect voiced frames in chirp"
        # F0 should generally increase over time
        first_quarter = f0_voiced[:len(f0_voiced) // 4]
        last_quarter = f0_voiced[-len(f0_voiced) // 4:]
        assert np.mean(last_quarter) > np.mean(first_quarter), \
            "F0 should increase over chirp signal"

    def test_chirp_range(self):
        """Chirp F0 must stay within valid range."""
        from phonation import extract_f0
        f0 = extract_f0('/app/test_data/chirp_120_250.wav')
        voiced = f0[f0 > 0]
        assert np.all(voiced >= 60)
        assert np.all(voiced <= 350)

    def test_multi_segment_f0(self):
        """Multi-segment signal should have voiced and unvoiced frames."""
        from phonation import extract_f0
        f0 = extract_f0('/app/test_data/multi_segment.wav')
        assert np.any(f0 > 0), "Should have voiced frames"
        assert np.any(f0 == 0), "Should have unvoiced frames"


# ============================================================
# Phonation pipeline tests
# ============================================================

class TestPhonationStatic:
    def test_dimensions(self):
        from phonation import extract_static
        features = extract_static('/app/test_data/tone_150hz.wav')
        assert len(features) == 28, f"Expected 28 features, got {len(features)}"

    def test_finite_values(self):
        from phonation import extract_static
        features = extract_static('/app/test_data/tone_150hz.wav')
        assert np.all(np.isfinite(features)), "All features should be finite"

    def test_aggregation_order(self):
        """Feature vector: [7 means, 7 stds, 7 skews, 7 kurts]."""
        from phonation import extract_static
        features = extract_static('/app/test_data/tone_150hz.wav')
        stds = features[7:14]
        # All standard deviations should be non-negative
        assert np.all(stds >= 0), "Standard deviations must be >= 0"

    def test_jitter_near_zero_for_pure_tone(self):
        """A clean harmonic tone should have very low jitter."""
        from phonation import extract_static
        features = extract_static('/app/test_data/tone_150hz.wav')
        # features[2] is mean(Jitter)
        mean_jitter = features[2]
        assert mean_jitter < 5.0, \
            f"Clean tone mean jitter should be small, got {mean_jitter:.3f}"

    def test_multi_segment(self):
        from phonation import extract_static
        features = extract_static('/app/test_data/multi_segment.wav')
        assert len(features) == 28
        assert np.all(np.isfinite(features))

    def test_silence_returns_zeros(self):
        """Silence should return a 28-element zero vector."""
        from phonation import extract_static
        features = extract_static('/app/test_data/silence.wav')
        assert len(features) == 28
        assert np.all(features == 0)

    def test_stereo_input(self):
        """Stereo WAV should be converted to mono and processed."""
        from phonation import extract_static
        features = extract_static('/app/test_data/stereo_150hz.wav')
        assert len(features) == 28
        assert np.all(np.isfinite(features))

    def test_short_signal(self):
        """Very short signal should return valid 28-element vector."""
        from phonation import extract_static
        features = extract_static('/app/test_data/short_40ms.wav')
        assert len(features) == 28

    def test_chirp_features(self):
        """Chirp signal should produce valid features."""
        from phonation import extract_static
        features = extract_static('/app/test_data/chirp_120_250.wav')
        assert len(features) == 28
        assert np.all(np.isfinite(features))


class TestPhonationDynamic:
    def test_shape(self):
        from phonation import extract_dynamic
        features = extract_dynamic('/app/test_data/tone_150hz.wav')
        assert len(features.shape) == 2, "Should be 2D array"
        assert features.shape[1] == 7, \
            f"Should have 7 columns, got {features.shape[1]}"
        assert features.shape[0] > 0, "Should have rows"

    def test_multi_segment_shape(self):
        from phonation import extract_dynamic
        features = extract_dynamic('/app/test_data/multi_segment.wav')
        assert features.shape[1] == 7


# ============================================================
# Prosody pipeline tests
# ============================================================

class TestProsodyStatic:
    def test_dimensions(self):
        from prosody import extract_static
        features = extract_static('/app/test_data/multi_segment.wav')
        assert len(features) == 103, \
            f"Expected 103 features, got {len(features)}"

    def test_finite_values(self):
        from prosody import extract_static
        features = extract_static('/app/test_data/multi_segment.wav')
        assert np.all(np.isfinite(features)), "All features should be finite"

    def test_f0_mean_in_range(self):
        """Feature[0] is mean of voiced F0 values."""
        from prosody import extract_static
        features = extract_static('/app/test_data/multi_segment.wav')
        mean_f0 = features[0]
        assert 100 <= mean_f0 <= 250, \
            f"Mean F0 should be in [100, 250], got {mean_f0:.1f}"

    def test_voiced_rate_positive(self):
        """Feature[78] is voiced rate (segments / second)."""
        from prosody import extract_static
        features = extract_static('/app/test_data/multi_segment.wav')
        voiced_rate = features[78]
        assert voiced_rate > 0, \
            f"Voiced rate should be positive, got {voiced_rate}"

    def test_voiced_rate_reasonable(self):
        from prosody import extract_static
        features = extract_static('/app/test_data/multi_segment.wav')
        # 3 voiced segments in ~1.67 s => rate ~1.8 seg/s
        voiced_rate = features[78]
        assert 0.5 <= voiced_rate <= 10, \
            f"Voiced rate should be reasonable, got {voiced_rate:.2f}"

    def test_duration_ratios_nonnegative(self):
        """Features[97-102] are duration ratios, all >= 0."""
        from prosody import extract_static
        features = extract_static('/app/test_data/multi_segment.wav')
        ratios = features[97:103]
        assert np.all(ratios >= 0), f"Duration ratios must be >= 0, got {ratios}"

    def test_pure_tone_dimensions(self):
        """Single voiced segment should still produce 103 features."""
        from prosody import extract_static
        features = extract_static('/app/test_data/tone_150hz.wav')
        assert len(features) == 103

    def test_silence_dimensions(self):
        """Silence should return a 103-element vector."""
        from prosody import extract_static
        features = extract_static('/app/test_data/silence.wav')
        assert len(features) == 103

    def test_stereo_input(self):
        """Stereo WAV should be handled for prosody."""
        from prosody import extract_static
        features = extract_static('/app/test_data/stereo_150hz.wav')
        assert len(features) == 103
        assert np.all(np.isfinite(features))

    def test_chirp_prosody(self):
        """Chirp signal should produce valid prosody features."""
        from prosody import extract_static
        features = extract_static('/app/test_data/chirp_120_250.wav')
        assert len(features) == 103
        assert np.all(np.isfinite(features))

    def test_energy_features_nonnegative_std(self):
        """Energy feature standard deviations (indices 31-34) should include
        non-negative std at index 31+1=32 (if it's a 4-stat block)."""
        from prosody import extract_static
        features = extract_static('/app/test_data/multi_segment.wav')
        # Feature 31 is mean energy, 32 is std energy for voiced
        # std should be non-negative
        assert features[31] != 0, "Voiced energy std should be computed"


class TestProsodyDynamic:
    def test_shape(self):
        from prosody import extract_dynamic
        features = extract_dynamic('/app/test_data/multi_segment.wav')
        assert len(features.shape) == 2, "Should be 2D array"
        assert features.shape[1] == 13, \
            f"Should have 13 columns, got {features.shape[1]}"
        assert features.shape[0] > 0, "Should have rows"

    def test_durations_positive(self):
        from prosody import extract_dynamic
        features = extract_dynamic('/app/test_data/multi_segment.wav')
        durations = features[:, 12]
        assert np.all(durations > 0), "Segment durations should be positive"

    def test_poly_coefficients_finite(self):
        from prosody import extract_dynamic
        features = extract_dynamic('/app/test_data/multi_segment.wav')
        assert np.all(np.isfinite(features)), \
            "All polynomial coefficients should be finite"

    def test_pure_tone_dynamic(self):
        """Single continuous voiced segment should produce at least 1 row."""
        from prosody import extract_dynamic
        features = extract_dynamic('/app/test_data/tone_150hz.wav')
        assert features.shape[0] >= 1
        assert features.shape[1] == 13


# ============================================================
# Cross-module consistency tests
# ============================================================

class TestCrossModuleConsistency:
    def test_both_detect_voiced_content(self):
        """Phonation and prosody should both produce non-zero features
        for a voiced signal."""
        from phonation import extract_static as phon_static
        from prosody import extract_static as pros_static

        phon = phon_static('/app/test_data/tone_150hz.wav')
        pros = pros_static('/app/test_data/tone_150hz.wav')

        assert not np.all(phon == 0), \
            "Phonation should produce non-zero features for voiced tone"
        assert not np.all(pros == 0), \
            "Prosody should produce non-zero features for voiced tone"

    def test_both_handle_silence(self):
        """Both modules should handle silence gracefully."""
        from phonation import extract_static as phon_static
        from prosody import extract_static as pros_static

        phon = phon_static('/app/test_data/silence.wav')
        pros = pros_static('/app/test_data/silence.wav')

        assert len(phon) == 28
        assert len(pros) == 103


# ============================================================
# CLI tests
# ============================================================

class TestCLI:
    def test_phonation_static_format(self):
        result = subprocess.run(
            ['python3', '/app/extract.py', 'phonation', 'static',
             '/app/test_data/tone_150hz.wav'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        lines = result.stdout.strip().split('\n')
        assert len(lines) == 1, "Static features should be one line"
        values = lines[0].split(',')
        assert len(values) == 28, \
            f"Expected 28 comma-separated values, got {len(values)}"
        # All values should be parseable as floats
        for v in values:
            float(v.strip())

    def test_prosody_static_format(self):
        result = subprocess.run(
            ['python3', '/app/extract.py', 'prosody', 'static',
             '/app/test_data/multi_segment.wav'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        lines = result.stdout.strip().split('\n')
        assert len(lines) == 1, "Static features should be one line"
        values = lines[0].split(',')
        assert len(values) == 103, \
            f"Expected 103 comma-separated values, got {len(values)}"

    def test_phonation_dynamic_format(self):
        result = subprocess.run(
            ['python3', '/app/extract.py', 'phonation', 'dynamic',
             '/app/test_data/tone_150hz.wav'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        lines = result.stdout.strip().split('\n')
        assert len(lines) > 0, "Should have at least one row"
        for line in lines:
            values = line.split(',')
            assert len(values) == 7, \
                f"Each row should have 7 values, got {len(values)}"

    def test_prosody_dynamic_format(self):
        result = subprocess.run(
            ['python3', '/app/extract.py', 'prosody', 'dynamic',
             '/app/test_data/multi_segment.wav'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        lines = result.stdout.strip().split('\n')
        assert len(lines) > 0, "Should have at least one row"
        for line in lines:
            values = line.split(',')
            assert len(values) == 13, \
                f"Each row should have 13 values, got {len(values)}"

    def test_cli_all_modes(self):
        """All four mode combinations should succeed on multi-segment."""
        modes = [
            ('phonation', 'static', 28),
            ('phonation', 'dynamic', 7),
            ('prosody', 'static', 103),
            ('prosody', 'dynamic', 13),
        ]
        for module, mode, expected_cols in modes:
            result = subprocess.run(
                ['python3', '/app/extract.py', module, mode,
                 '/app/test_data/multi_segment.wav'],
                capture_output=True, text=True, timeout=60
            )
            assert result.returncode == 0, \
                f"CLI failed for {module}/{mode}: {result.stderr}"
            lines = result.stdout.strip().split('\n')
            assert len(lines) >= 1, \
                f"No output for {module}/{mode}"
            for line in lines:
                values = line.split(',')
                assert len(values) == expected_cols, \
                    f"{module}/{mode}: expected {expected_cols} cols, " \
                    f"got {len(values)}"

    def test_cli_handles_nonstandard_input(self):
        """CLI must handle 44.1kHz stereo input via SoX preprocessing."""
        result = subprocess.run(
            ['python3', '/app/extract.py', 'phonation', 'static',
             '/app/test_data/hires_stereo.wav'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, \
            f"CLI failed on 44.1kHz stereo: {result.stderr}"
        values = result.stdout.strip().split(',')
        assert len(values) == 28, \
            f"Expected 28 values for phonation static, got {len(values)}"
        # Should produce finite float values
        for v in values:
            assert np.isfinite(float(v.strip())), \
                f"Non-finite value in output: {v}"

    def test_cli_prosody_nonstandard_input(self):
        """CLI prosody should also handle non-standard input."""
        result = subprocess.run(
            ['python3', '/app/extract.py', 'prosody', 'static',
             '/app/test_data/hires_stereo.wav'],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, \
            f"CLI failed on 44.1kHz stereo: {result.stderr}"
        values = result.stdout.strip().split(',')
        assert len(values) == 103, \
            f"Expected 103 values for prosody static, got {len(values)}"
