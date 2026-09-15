"""Tests for the Stim surface code decoder.

"""

import stim
import numpy as np
import json
import os
import subprocess
import sys

import jsonschema

sys.path.insert(0, "/app")


def _load_circuit(path):
    with open(path) as f:
        return stim.Circuit(f.read())


class TestDecoderInterface:
    """Verify decoder class structure and basic contracts."""

    def test_importable(self):
        from decoder import StimDecoder
        assert callable(StimDecoder)

    def test_accepts_dem(self):
        from decoder import StimDecoder
        circuit = _load_circuit("/app/circuits/d3_p005.stim")
        dem = circuit.detector_error_model(decompose_errors=True)
        dec = StimDecoder(dem)
        assert dec is not None

    def test_output_shape(self):
        from decoder import StimDecoder
        circuit = _load_circuit("/app/circuits/d3_p005.stim")
        dem = circuit.detector_error_model(decompose_errors=True)
        dec = StimDecoder(dem)

        dets = np.zeros((1, dem.num_detectors), dtype=bool)
        result = dec.decode_batch(dets, dem.num_observables)
        assert result.shape == (1, dem.num_observables), \
            f"Expected (1, {dem.num_observables}), got {result.shape}"

    def test_zero_detection_events(self):
        from decoder import StimDecoder
        circuit = _load_circuit("/app/circuits/d3_p005.stim")
        dem = circuit.detector_error_model(decompose_errors=True)
        dec = StimDecoder(dem)

        dets = np.zeros((10, dem.num_detectors), dtype=bool)
        result = dec.decode_batch(dets, dem.num_observables)
        assert np.all(~result), \
            "Zero detection events should predict zero observable flips"

    def test_batch_multiple_shots(self):
        from decoder import StimDecoder
        circuit = _load_circuit("/app/circuits/d3_p005.stim")
        dem = circuit.detector_error_model(decompose_errors=True)
        dec = StimDecoder(dem)

        num_shots = 50
        sampler = circuit.compile_detector_sampler(seed=777)
        all_data = sampler.sample(shots=num_shots, append_observables=True)
        dets = all_data[:, :dem.num_detectors].astype(bool)

        result = dec.decode_batch(dets, dem.num_observables)
        assert result.shape == (num_shots, dem.num_observables)
        assert result.dtype == bool or result.dtype == np.bool_


class TestDecoderCorrectness:
    """Verify decoder produces valid predictions."""

    def test_single_detection_events(self):
        """Single detection events should produce valid predictions."""
        from decoder import StimDecoder
        circuit = _load_circuit("/app/circuits/d3_p005.stim")
        dem = circuit.detector_error_model(decompose_errors=True)
        dec = StimDecoder(dem)

        for d in range(min(dem.num_detectors, 12)):
            dets = np.zeros((1, dem.num_detectors), dtype=bool)
            dets[0, d] = True
            result = dec.decode_batch(dets, dem.num_observables)
            assert result.shape == (1, dem.num_observables)

    def test_dem_from_cli(self):
        """Decoder must work with DEM obtained via stim CLI."""
        from decoder import StimDecoder

        with open("/app/circuits/d3_p005.stim") as f:
            circuit_text = f.read()

        proc = subprocess.run(
            ["stim", "analyze_errors", "--decompose_errors"],
            input=circuit_text,
            capture_output=True, text=True
        )
        assert proc.returncode == 0, \
            f"stim analyze_errors failed: {proc.stderr}"

        dem = stim.DetectorErrorModel(proc.stdout)
        dec = StimDecoder(dem)

        dets = np.zeros((1, dem.num_detectors), dtype=bool)
        result = dec.decode_batch(dets, dem.num_observables)
        assert result.shape == (1, dem.num_observables)

    def test_works_on_both_distances(self):
        """Decoder must handle both d=3 and d=5 circuits."""
        from decoder import StimDecoder

        for path in ["/app/circuits/d3_p005.stim",
                     "/app/circuits/d5_p005.stim"]:
            circuit = _load_circuit(path)
            dem = circuit.detector_error_model(decompose_errors=True)
            dec = StimDecoder(dem)

            sampler = circuit.compile_detector_sampler(seed=333)
            all_data = sampler.sample(shots=20, append_observables=True)
            dets = all_data[:, :dem.num_detectors].astype(bool)

            result = dec.decode_batch(dets, dem.num_observables)
            assert result.shape == (20, dem.num_observables)


class TestDecoderPerformance:
    """Verify decoder achieves acceptable logical error rates."""

    def _compute_ler(self, circuit_path, num_shots, seed):
        from decoder import StimDecoder
        circuit = _load_circuit(circuit_path)
        dem = circuit.detector_error_model(decompose_errors=True)
        dec = StimDecoder(dem)

        sampler = circuit.compile_detector_sampler(seed=seed)
        all_data = sampler.sample(shots=num_shots, append_observables=True)

        n_det = dem.num_detectors
        dets = all_data[:, :n_det].astype(bool)
        obs_actual = all_data[:, n_det:].astype(bool)

        obs_pred = dec.decode_batch(dets, dem.num_observables)
        errors = np.any(obs_pred != obs_actual, axis=1)
        return float(errors.sum()) / num_shots

    def test_logical_error_rate_d3(self):
        ler = self._compute_ler("/app/circuits/d3_p005.stim", 3000, 54321)
        assert ler < 0.20, \
            f"d=3 logical error rate {ler:.4f} exceeds threshold 0.20"

    def test_logical_error_rate_d5(self):
        ler = self._compute_ler("/app/circuits/d5_p005.stim", 3000, 54321)
        assert ler < 0.10, \
            f"d=5 logical error rate {ler:.4f} exceeds threshold 0.10"

    def test_threshold_behavior(self):
        """d=5 must have lower logical error rate than d=3 (threshold behavior)."""
        ler_d3 = self._compute_ler("/app/circuits/d3_p005.stim", 5000, 11111)
        ler_d5 = self._compute_ler("/app/circuits/d5_p005.stim", 5000, 11111)

        if ler_d3 > 0.005:
            assert ler_d5 < ler_d3, \
                (f"Threshold behavior violated: d=5 LER ({ler_d5:.4f}) "
                 f">= d=3 LER ({ler_d3:.4f})")

    def test_benchmark_script(self):
        """benchmark.py must run and produce valid results.json."""
        proc = subprocess.run(
            ["python3", "/app/benchmark.py"],
            capture_output=True, text=True,
            timeout=240
        )
        assert proc.returncode == 0, \
            f"benchmark.py failed:\nstdout: {proc.stdout}\nstderr: {proc.stderr}"

        assert os.path.exists("/app/results.json"), "results.json not created"

        with open("/app/results.json") as f:
            results = json.load(f)

        with open("/app/results_schema.json") as f:
            schema = json.load(f)

        jsonschema.validate(instance=results, schema=schema)

        assert isinstance(results, dict) and len(results) > 0, \
            "results.json must be a non-empty dict"

        for key, data in results.items():
            assert "logical_error_rate" in data, \
                f"Missing logical_error_rate in {key}"
            assert "distance" in data, \
                f"Missing distance in {key}"
            assert isinstance(data["logical_error_rate"], (int, float)), \
                f"logical_error_rate must be numeric in {key}"
            assert 0 <= data["logical_error_rate"] <= 1, \
                f"logical_error_rate out of range in {key}"
