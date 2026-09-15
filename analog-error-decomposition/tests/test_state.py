
import sys
import os
import json

import numpy as np
import pytest

sys.path.insert(0, "/app")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_params(prog=False, noise=False, drift=False, drift_time=0,
                 cell_bits=6, adc_bits=8):
    """Build CrossSimParameters with optional HfO2BilayerRRAM errors."""
    import hfo2_rram  # noqa: F401
    from simulator import CrossSimParameters

    params = CrossSimParameters()
    params.core.style = "BALANCED"
    params.xbar.device.Rmin = 5e3
    params.xbar.device.Rmax = 500e3
    params.xbar.device.cell_bits = cell_bits

    if adc_bits > 0:
        params.xbar.adc.mvm.bits = adc_bits
        params.xbar.adc.mvm.model = "SignMagnitudeADC"
        params.xbar.adc.mvm.signed = True
        params.xbar.adc.mvm.adc_range_option = "MAX"

    if prog:
        params.xbar.device.programming_error.enable = True
        params.xbar.device.programming_error.model = "HfO2BilayerRRAM"
    if noise:
        params.xbar.device.read_noise.enable = True
        params.xbar.device.read_noise.model = "HfO2BilayerRRAM"
    if drift:
        params.xbar.device.drift_error.enable = True
        params.xbar.device.drift_error.model = "HfO2BilayerRRAM"
        params.xbar.device.time = drift_time

    return params


# ===================================================================
# 1  Device model structure
# ===================================================================

class TestDeviceModelStructure:

    def test_device_file_exists(self):
        assert os.path.exists("/app/hfo2_rram.py"), \
            "/app/hfo2_rram.py not found"

    def test_class_inherits_empty_device(self):
        from hfo2_rram import HfO2BilayerRRAM
        from simulator.devices.idevice import EmptyDevice
        assert issubclass(HfO2BilayerRRAM, EmptyDevice), \
            "HfO2BilayerRRAM must be a subclass of EmptyDevice"

    def test_has_programming_error_method(self):
        from hfo2_rram import HfO2BilayerRRAM
        assert callable(getattr(HfO2BilayerRRAM, "programming_error", None))

    def test_has_read_noise_method(self):
        from hfo2_rram import HfO2BilayerRRAM
        assert callable(getattr(HfO2BilayerRRAM, "read_noise", None))

    def test_has_drift_error_method(self):
        from hfo2_rram import HfO2BilayerRRAM
        assert callable(getattr(HfO2BilayerRRAM, "drift_error", None))


# ===================================================================
# 2  CrossSim integration
# ===================================================================

class TestCrossSimIntegration:

    def test_basic_mvm_runs(self):
        """AnalogCore with HfO2BilayerRRAM runs an MVM without crashing."""
        from simulator import AnalogCore

        np.random.seed(99)
        W = np.random.RandomState(123).randn(32, 32)
        x = np.random.RandomState(456).randn(32)

        params = _make_params(prog=True, noise=True, drift=True, drift_time=5)
        core = AnalogCore(W, params=params)
        y = np.asarray(core.matvec(x), dtype=np.float64)

        assert y.shape == (32,), f"Expected shape (32,), got {y.shape}"
        assert np.isfinite(y).all(), "MVM output contains NaN/Inf"

    def test_quantization_only_is_deterministic(self):
        """With no device errors, repeated MVMs must be identical."""
        from simulator import AnalogCore

        W = np.random.RandomState(123).randn(16, 16)
        x = np.random.RandomState(456).randn(16)
        params = _make_params()

        core1 = AnalogCore(W, params=params)
        y1 = np.asarray(core1.matvec(x), dtype=np.float64)

        core2 = AnalogCore(W, params=params)
        y2 = np.asarray(core2.matvec(x), dtype=np.float64)

        np.testing.assert_array_equal(y1, y2)

    def test_programming_error_adds_measurable_noise(self):
        """Programming error must produce non-trivial deviation from ideal."""
        from simulator import AnalogCore

        W = np.random.RandomState(123).randn(32, 32)
        x = np.random.RandomState(456).randn(32)
        y_ideal = W @ x

        nrmse_list = []
        for seed in range(20):
            np.random.seed(seed)
            params = _make_params(prog=True)
            core = AnalogCore(W, params=params)
            y = np.asarray(core.matvec(x), dtype=np.float64)
            nrmse = np.sqrt(np.mean((y - y_ideal) ** 2)) / np.sqrt(np.mean(y_ideal ** 2))
            nrmse_list.append(nrmse)

        mean_nrmse = np.mean(nrmse_list)
        assert mean_nrmse > 0.001, \
            f"Programming error NRMSE too small ({mean_nrmse:.6f}); model may not inject noise"
        assert mean_nrmse < 1.5, \
            f"Programming error NRMSE too large ({mean_nrmse:.6f}); model may be broken"

    def test_drift_increases_error_over_time(self):
        """Drift at t=30 days should produce more error than t=0."""
        from simulator import AnalogCore

        W = np.random.RandomState(123).randn(32, 32)
        x = np.random.RandomState(456).randn(32)
        y_ideal = W @ x

        nrmse_by_t = {}
        for t in [0, 30]:
            params = _make_params(drift=True, drift_time=t)
            core = AnalogCore(W, params=params)
            y = np.asarray(core.matvec(x), dtype=np.float64)
            nrmse_by_t[t] = np.sqrt(np.mean((y - y_ideal) ** 2)) / np.sqrt(np.mean(y_ideal ** 2))

        assert nrmse_by_t[30] > nrmse_by_t[0], \
            f"Drift at t=30d ({nrmse_by_t[30]:.6f}) must exceed t=0 ({nrmse_by_t[0]:.6f})"


# ===================================================================
# 3  Results file
# ===================================================================

class TestResults:

    @pytest.fixture(autouse=True)
    def _load_results(self):
        path = "/app/results.json"
        assert os.path.exists(path), f"{path} not found"
        with open(path) as f:
            self.results = json.load(f)

    def test_error_decomposition_keys(self):
        ed = self.results.get("error_decomposition", {})
        required = ["quantization_only", "programming_error", "read_noise",
                     "drift_30d", "all_combined"]
        for key in required:
            assert key in ed, f"Missing scenario '{key}' in error_decomposition"
            val = ed[key]
            assert isinstance(val, (int, float)), f"{key} must be numeric, got {type(val)}"
            assert 0 <= val <= 2.0, f"NRMSE for {key} out of range [0, 2]: {val}"

    def test_dominant_error_source_valid(self):
        dom = self.results.get("dominant_error_source")
        assert dom in ("programming_error", "read_noise", "drift_30d"), \
            f"dominant_error_source must be one of the individual scenarios, got '{dom}'"

    def test_dominant_source_matches_max(self):
        ed = self.results["error_decomposition"]
        individual = {
            "programming_error": ed["programming_error"],
            "read_noise": ed["read_noise"],
            "drift_30d": ed["drift_30d"],
        }
        expected = max(individual, key=individual.get)
        assert self.results["dominant_error_source"] == expected, \
            f"Expected dominant={expected}, got {self.results['dominant_error_source']}"

    def test_optimal_cell_bits(self):
        cb = self.results.get("optimal_cell_bits")
        assert isinstance(cb, int), f"optimal_cell_bits must be int, got {type(cb)}"
        assert 2 <= cb <= 10, f"optimal_cell_bits out of sweep range [2,10]: {cb}"

    def test_optimal_adc_bits(self):
        ab = self.results.get("optimal_adc_bits")
        assert isinstance(ab, int), f"optimal_adc_bits must be int, got {type(ab)}"
        assert ab in (4, 6, 8, 10, 12, 14, 16), \
            f"optimal_adc_bits not in sweep set: {ab}"

    def test_combined_exceeds_quantization(self):
        ed = self.results["error_decomposition"]
        assert ed["all_combined"] >= ed["quantization_only"] * 0.8, \
            ("all_combined NRMSE should be at least 80% of quantization_only; "
             f"got combined={ed['all_combined']:.6f}, quant={ed['quantization_only']:.6f}")

    def test_analysis_script_exists(self):
        assert os.path.exists("/app/error_decomposition.py"), \
            "/app/error_decomposition.py not found"
