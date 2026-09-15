"""
Verification tests for the co-simulation master algorithm.

Tests validate correctness of coupling strategies, adaptive step-size control,
stability analysis, convergence properties, and XML topology parsing.

"""

import csv
import json
import os
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, '/app')
from reference_solver import generate_reference


def _read_csv_results(filepath):
    """Read time,w columns from a CSV results file."""
    times, ws = [], []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row['time']))
            ws.append(float(row['w']))
    return np.array(times), np.array(ws)


def _compute_rmse(res_t, res_w, ref_t, ref_w):
    """Compute RMSE of result vs reference (interpolated)."""
    ref_interp = np.interp(res_t, ref_t, ref_w)
    return float(np.sqrt(np.mean((res_w - ref_interp) ** 2)))


class TestOutputFilesExist:
    """Verify all required output files are present."""

    def test_gauss_seidel_csv(self):
        assert os.path.exists('/app/results/gauss_seidel.csv'), \
            "Missing /app/results/gauss_seidel.csv"

    def test_jacobi_csv(self):
        assert os.path.exists('/app/results/jacobi.csv'), \
            "Missing /app/results/jacobi.csv"

    def test_adaptive_csv(self):
        assert os.path.exists('/app/results/adaptive.csv'), \
            "Missing /app/results/adaptive.csv"

    def test_analysis_json(self):
        assert os.path.exists('/app/results/analysis.json'), \
            "Missing /app/results/analysis.json"


class TestCsvFormat:
    """Verify CSV files have correct headers and sufficient data."""

    def _check_csv(self, filepath):
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            assert 'time' in header, f"Missing 'time' column in {filepath}"
            assert 'w' in header, f"Missing 'w' column in {filepath}"
            rows = list(reader)
            assert len(rows) >= 10, \
                f"Too few data rows ({len(rows)}) in {filepath}"
            for i, row in enumerate(rows):
                t_idx = header.index('time')
                w_idx = header.index('w')
                t_val = float(row[t_idx])
                w_val = float(row[w_idx])
                assert np.isfinite(t_val), f"Non-finite time at row {i}"
                assert np.isfinite(w_val), f"Non-finite w at row {i}"

    def test_gauss_seidel_format(self):
        self._check_csv('/app/results/gauss_seidel.csv')

    def test_jacobi_format(self):
        self._check_csv('/app/results/jacobi.csv')

    def test_adaptive_format(self):
        self._check_csv('/app/results/adaptive.csv')


class TestAnalysisJson:
    """Verify analysis.json has all required fields with valid types."""

    def _load_analysis(self):
        with open('/app/results/analysis.json', 'r') as f:
            return json.load(f)

    def test_required_fields_exist(self):
        analysis = self._load_analysis()
        required = [
            'convergence_order',
            'stability_limit_jacobi',
            'stability_limit_gauss_seidel',
            'rmse_adaptive',
            'total_steps_adaptive',
        ]
        for field in required:
            assert field in analysis, f"Missing field: {field}"

    def test_field_types(self):
        analysis = self._load_analysis()
        for field in ['convergence_order', 'stability_limit_jacobi',
                      'stability_limit_gauss_seidel', 'rmse_adaptive']:
            assert isinstance(analysis[field], (int, float)), \
                f"{field} must be numeric, got {type(analysis[field])}"
        assert isinstance(analysis['total_steps_adaptive'], (int, float)), \
            "total_steps_adaptive must be numeric"


class TestAdaptiveAccuracy:
    """Verify the adaptive solution achieves required RMSE."""

    def test_rmse_below_threshold(self):
        ref_t, ref_w = generate_reference()
        res_t, res_w = _read_csv_results('/app/results/adaptive.csv')
        rmse = _compute_rmse(res_t, res_w, ref_t, ref_w)
        assert rmse < 0.01, \
            f"Adaptive RMSE ({rmse:.6e}) exceeds threshold (0.01)"

    def test_rmse_matches_reported(self):
        """Reported rmse_adaptive should be close to actual RMSE."""
        ref_t, ref_w = generate_reference()
        res_t, res_w = _read_csv_results('/app/results/adaptive.csv')
        actual_rmse = _compute_rmse(res_t, res_w, ref_t, ref_w)
        with open('/app/results/analysis.json', 'r') as f:
            reported_rmse = json.load(f)['rmse_adaptive']
        assert abs(actual_rmse - reported_rmse) < 0.05, \
            f"Reported RMSE ({reported_rmse:.6e}) differs from " \
            f"actual ({actual_rmse:.6e})"


class TestFixedStepAccuracy:
    """Verify fixed-step results are stable and reasonably accurate."""

    def test_gauss_seidel_stable(self):
        res_t, res_w = _read_csv_results('/app/results/gauss_seidel.csv')
        assert np.all(np.isfinite(res_w)), "GS solution contains NaN/Inf"
        assert np.max(np.abs(res_w)) < 1000, \
            f"GS solution diverged: max |w| = {np.max(np.abs(res_w))}"

    def test_jacobi_stable(self):
        res_t, res_w = _read_csv_results('/app/results/jacobi.csv')
        assert np.all(np.isfinite(res_w)), "Jacobi solution contains NaN/Inf"
        assert np.max(np.abs(res_w)) < 1000, \
            f"Jacobi solution diverged: max |w| = {np.max(np.abs(res_w))}"

    def test_gauss_seidel_accuracy(self):
        ref_t, ref_w = generate_reference()
        res_t, res_w = _read_csv_results('/app/results/gauss_seidel.csv')
        rmse = _compute_rmse(res_t, res_w, ref_t, ref_w)
        assert rmse < 0.5, \
            f"GS fixed-step RMSE ({rmse:.4f}) too large for h=0.001"

    def test_physical_plausibility(self):
        """Speed should start near 0, rise to ~10, and stay bounded."""
        res_t, res_w = _read_csv_results('/app/results/gauss_seidel.csv')
        assert abs(res_w[0]) < 0.1, \
            f"Initial velocity should be ~0, got {res_w[0]}"
        mask_steady = (res_t > 0.8) & (res_t < 0.95)
        if np.any(mask_steady):
            mean_w = np.mean(res_w[mask_steady])
            assert abs(mean_w - 10) < 3, \
                f"Steady-state velocity should be ~10 rad/s, got {mean_w:.2f}"


class TestConvergenceOrder:
    """Verify the measured convergence order is reasonable."""

    def test_order_in_range(self):
        with open('/app/results/analysis.json', 'r') as f:
            order = json.load(f)['convergence_order']
        assert 0.5 < order < 2.0, \
            f"Convergence order ({order:.2f}) outside expected range [0.5, 2.0]"


class TestStabilityLimits:
    """Verify stability limit analysis results."""

    def _load_analysis(self):
        with open('/app/results/analysis.json', 'r') as f:
            return json.load(f)

    def test_jacobi_limit_positive(self):
        analysis = self._load_analysis()
        assert analysis['stability_limit_jacobi'] > 0, \
            "Jacobi stability limit must be positive"

    def test_gs_limit_positive(self):
        analysis = self._load_analysis()
        assert analysis['stability_limit_gauss_seidel'] > 0, \
            "Gauss-Seidel stability limit must be positive"

    def test_gs_at_least_jacobi(self):
        """GS should have a stability region at least as large as Jacobi."""
        analysis = self._load_analysis()
        gs = analysis['stability_limit_gauss_seidel']
        jac = analysis['stability_limit_jacobi']
        assert gs >= jac, \
            f"GS limit ({gs}) should be >= Jacobi limit ({jac})"

    def test_limits_bounded(self):
        """Stability limits should be below 1.0 s for this system."""
        analysis = self._load_analysis()
        assert analysis['stability_limit_jacobi'] <= 1.0
        assert analysis['stability_limit_gauss_seidel'] <= 1.0


class TestTopologyParsing:
    """Verify the master reads topology from SSP/XML files."""

    def test_uses_xml_parsing(self):
        """Source must contain XML parsing code."""
        with open('/app/cosim_master.py', 'r') as f:
            source = f.read()
        xml_markers = ['xml.etree', 'lxml', 'ElementTree', 'minidom',
                       'ET.parse', 'etree.parse']
        assert any(m in source for m in xml_markers), \
            "cosim_master.py must include XML parsing code"

    def test_references_ssp_file(self):
        """Source must reference the SSP topology file."""
        with open('/app/cosim_master.py', 'r') as f:
            source = f.read()
        assert 'system_structure' in source, \
            "cosim_master.py must reference system_structure.ssd"

    def test_references_model_descriptions(self):
        """Source must reference model description files."""
        with open('/app/cosim_master.py', 'r') as f:
            source = f.read()
        assert 'model_description' in source.lower() or \
               'modeldescription' in source.lower() or \
               'model_descriptions' in source, \
            "cosim_master.py must reference modelDescription XML files"

    def test_requires_ssp_file(self):
        """Master must fail if SSP topology file is removed."""
        ssd = '/app/system_structure.ssd'
        bak = ssd + '.tmp_test_bak'
        results_bak = '/tmp/_test_results_bak_ssp'

        if os.path.exists('/app/results'):
            if os.path.exists(results_bak):
                shutil.rmtree(results_bak)
            shutil.copytree('/app/results', results_bak)

        shutil.rmtree('/app/results', ignore_errors=True)
        shutil.move(ssd, bak)
        try:
            r = subprocess.run(
                ['python3', '/app/cosim_master.py'],
                capture_output=True, timeout=60
            )
            has_results = os.path.exists('/app/results/analysis.json')
            assert r.returncode != 0 or not has_results, \
                "cosim_master.py must fail when system_structure.ssd is removed"
        except subprocess.TimeoutExpired:
            pass  # timeout means it did not complete normally
        finally:
            shutil.move(bak, ssd)
            if os.path.exists(results_bak):
                shutil.rmtree('/app/results', ignore_errors=True)
                shutil.copytree(results_bak, '/app/results')
                shutil.rmtree(results_bak, ignore_errors=True)

    def test_requires_model_descriptions(self):
        """Master must fail if model description XMLs are removed."""
        md_dir = '/app/model_descriptions'
        bak_dir = md_dir + '.tmp_test_bak'
        results_bak = '/tmp/_test_results_bak_md'

        if os.path.exists('/app/results'):
            if os.path.exists(results_bak):
                shutil.rmtree(results_bak)
            shutil.copytree('/app/results', results_bak)

        shutil.rmtree('/app/results', ignore_errors=True)
        shutil.move(md_dir, bak_dir)
        try:
            r = subprocess.run(
                ['python3', '/app/cosim_master.py'],
                capture_output=True, timeout=60
            )
            has_results = os.path.exists('/app/results/analysis.json')
            assert r.returncode != 0 or not has_results, \
                "cosim_master.py must fail when model_descriptions/ is removed"
        except subprocess.TimeoutExpired:
            pass
        finally:
            shutil.move(bak_dir, md_dir)
            if os.path.exists(results_bak):
                shutil.rmtree('/app/results', ignore_errors=True)
                shutil.copytree(results_bak, '/app/results')
                shutil.rmtree(results_bak, ignore_errors=True)
