"""Tests for PLUMED metadynamics FES pipeline: AWK preprocessing, FES reconstruction,
Makefile orchestration, and convergence analysis."""
import json
import subprocess
import numpy as np
import os
import pytest
import math
import shutil


PI = math.pi


def parse_hills(filepath):
    """Parse a PLUMED HILLS file into structured data."""
    multivariate = False
    fields = []
    rows = []
    with open(filepath) as f:
        for line in f:
            s = line.strip()
            if s.startswith('#! FIELDS'):
                fields = s.split()[2:]
            elif s.startswith('#! SET multivariate'):
                multivariate = s.split()[-1].lower() == 'true'
            elif not s or s.startswith('#'):
                continue
            else:
                rows.append([float(x) for x in s.split()])
    data = np.array(rows)
    n_sigma = sum(1 for f in fields if f.startswith('sigma'))
    n_cv = len(fields) - 3 - n_sigma
    result = dict(
        n_cv=n_cv, multivariate=multivariate,
        times=data[:, 0],
        centers=data[:, 1:1 + n_cv],
        heights=data[:, -2],
        biasf=data[:, -1],
    )
    if multivariate:
        sigma_raw = data[:, 1 + n_cv:1 + n_cv + n_sigma]
        n_hills = len(data)
        cov = np.zeros((n_hills, n_cv, n_cv))
        for k in range(n_hills):
            idx = 0
            for i in range(n_cv):
                for j in range(i, n_cv):
                    cov[k, i, j] = cov[k, j, i] = sigma_raw[k, idx]
                    idx += 1
        result['cov_matrices'] = cov
    else:
        result['sigmas'] = data[:, 1 + n_cv:1 + n_cv + n_sigma]
    return result


def reference_fes(hd, gmin, gmax, gbins, peri):
    """Compute reference FES on a grid independently using numpy."""
    nc = hd['n_cv']
    grids = []
    for i in range(nc):
        dx = (gmax[i] - gmin[i]) / gbins[i]
        grids.append(np.linspace(gmin[i] + dx / 2, gmax[i] - dx / 2, gbins[i]))
    if nc == 1:
        pts = grids[0].reshape(-1, 1)
    else:
        mesh = np.meshgrid(*grids, indexing='ij')
        pts = np.stack([m.ravel() for m in mesh], axis=1)
    npts = pts.shape[0]
    periods = np.array([(gmax[i] - gmin[i]) if peri[i] else 0.0 for i in range(nc)])
    bias = np.zeros(npts)
    deriv = np.zeros((npts, nc))
    for k in range(len(hd['heights'])):
        dp = pts - hd['centers'][k]
        for i in range(nc):
            if peri[i]:
                dp[:, i] -= periods[i] * np.round(dp[:, i] / periods[i])
        if hd['multivariate']:
            ci = np.linalg.inv(hd['cov_matrices'][k])
            q = np.sum((dp @ ci) * dp, axis=1)
            g = hd['heights'][k] * np.exp(-0.5 * q)
            deriv += -g[:, None] * (dp @ ci)
        else:
            sig = hd['sigmas'][k]
            g = hd['heights'][k] * np.exp(-np.sum(dp ** 2 / (2 * sig ** 2), axis=1))
            deriv += -g[:, None] * dp / sig ** 2
        bias += g
    gamma = hd['biasf'][0]
    f = -gamma / (gamma - 1.0) if gamma > 1.0 else -1.0
    return pts, f * bias, f * deriv


def filter_hills_by_time(hd, tmax):
    """Return a filtered copy of hills data with only hills where time <= tmax."""
    mask = hd['times'] <= tmax + 1e-6
    filtered = dict(
        n_cv=hd['n_cv'], multivariate=hd['multivariate'],
        times=hd['times'][mask],
        centers=hd['centers'][mask],
        heights=hd['heights'][mask],
        biasf=hd['biasf'][mask],
    )
    if hd['multivariate']:
        filtered['cov_matrices'] = hd['cov_matrices'][mask]
    else:
        filtered['sigmas'] = hd['sigmas'][mask]
    return filtered


def parse_output(path, ncv):
    """Parse the solver's output file."""
    rows = []
    with open(path) as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            rows.append([float(x) for x in s.split()])
    d = np.array(rows)
    return d[:, :ncv], d[:, ncv], d[:, ncv + 1:ncv + 1 + ncv]


def run_tool(hills, gmin, gmax, gbins, peri, out):
    """Execute the solver's sum_hills tool."""
    cmd = [
        'python3', '/app/sum_hills',
        '--hills', hills,
        f'--grid-min={",".join(f"{x:.14f}" for x in gmin)}',
        f'--grid-max={",".join(f"{x:.14f}" for x in gmax)}',
        f'--grid-bins={",".join(str(x) for x in gbins)}',
        f'--periodic={",".join(str(x).lower() for x in peri)}',
        '--outfile', out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (
        f"sum_hills exited with code {r.returncode}.\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )


def run_awk_preprocess(hills_file, tmin, tmax):
    """Execute the solver's preprocess.awk and return stdout."""
    r = subprocess.run(
        ['gawk', '-v', f'tmin={tmin}', '-v', f'tmax={tmax}',
         '-f', '/app/preprocess.awk', hills_file],
        capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 0, f"preprocess.awk failed: {r.stderr}"
    return r.stdout


# ===========================================================================
# AWK preprocessing tests
# ===========================================================================

class TestAWKPreprocessing:
    HILLS = '/app/hills_1d_long.dat'

    def test_headers_preserved(self):
        """All #! header lines must appear in output."""
        out = run_awk_preprocess(self.HILLS, 0, 99999)
        header_lines = [l for l in out.strip().split('\n') if l.startswith('#!')]
        assert len(header_lines) >= 2, "Should preserve at least FIELDS and SET headers"
        assert any('FIELDS' in h for h in header_lines)
        assert any('multivariate' in h for h in header_lines)

    def test_time_filtering_range(self):
        """Only data rows within [tmin, tmax] should appear."""
        out = run_awk_preprocess(self.HILLS, 300, 700)
        data_lines = [l for l in out.strip().split('\n')
                      if l.strip() and not l.strip().startswith('#')]
        # Hills at times 300, 400, 500, 600, 700 should be included
        assert len(data_lines) == 5, f"Expected 5 hills in [300,700], got {len(data_lines)}"
        for line in data_lines:
            t = float(line.split()[0])
            assert 300 <= t <= 700, f"Time {t} outside [300, 700]"

    def test_empty_window(self):
        """A time window with no matching hills should output only headers."""
        out = run_awk_preprocess(self.HILLS, 50, 90)
        data_lines = [l for l in out.strip().split('\n')
                      if l.strip() and not l.strip().startswith('#')]
        assert len(data_lines) == 0, "Empty window should have no data rows"

    def test_boundary_exact_match(self):
        """Boundary values (tmin == time or tmax == time) should be included."""
        out = run_awk_preprocess(self.HILLS, 100, 100)
        data_lines = [l for l in out.strip().split('\n')
                      if l.strip() and not l.strip().startswith('#')]
        assert len(data_lines) == 1, "Exact boundary match should include the hill"
        assert abs(float(data_lines[0].split()[0]) - 100.0) < 1e-6

    def test_full_range_preserves_all(self):
        """A window covering the full time range should include all hills."""
        out = run_awk_preprocess(self.HILLS, 0, 99999)
        data_lines = [l for l in out.strip().split('\n')
                      if l.strip() and not l.strip().startswith('#')]
        # hills_1d_long.dat has 32 data rows
        assert len(data_lines) == 32, f"Full range should have 32 hills, got {len(data_lines)}"

    def test_preserves_data_columns(self):
        """Filtered data lines must have the same column structure."""
        out = run_awk_preprocess(self.HILLS, 100, 300)
        data_lines = [l for l in out.strip().split('\n')
                      if l.strip() and not l.strip().startswith('#')]
        for line in data_lines:
            cols = line.split()
            assert len(cols) == 5, f"Expected 5 columns per row, got {len(cols)}"


# ===========================================================================
# 1D periodic FES
# ===========================================================================

class TestFES1D:
    HILLS = '/app/hills_1d.dat'
    OUT = '/app/fes_1d.dat'
    GMIN, GMAX, GBINS = [-PI], [PI], [100]
    PERI = [True]

    @pytest.fixture(scope='class', autouse=True)
    def run_once(self):
        run_tool(self.HILLS, self.GMIN, self.GMAX, self.GBINS, self.PERI, self.OUT)

    def test_output_file_exists(self):
        assert os.path.isfile(self.OUT), "Output file not created"

    def test_grid_point_count(self):
        _, fes, _ = parse_output(self.OUT, 1)
        assert len(fes) == 100, f"Expected 100 grid points, got {len(fes)}"

    def test_fes_values_match_reference(self):
        hd = parse_hills(self.HILLS)
        _, ref_fes, _ = reference_fes(hd, self.GMIN, self.GMAX, self.GBINS, self.PERI)
        _, fes, _ = parse_output(self.OUT, 1)
        np.testing.assert_allclose(
            fes, ref_fes, atol=1e-4,
            err_msg="1D FES values differ from reference"
        )

    def test_derivative_values_match_reference(self):
        hd = parse_hills(self.HILLS)
        _, _, ref_d = reference_fes(hd, self.GMIN, self.GMAX, self.GBINS, self.PERI)
        _, _, d = parse_output(self.OUT, 1)
        np.testing.assert_allclose(
            d[:, 0], ref_d[:, 0], atol=1e-3,
            err_msg="1D derivative values differ from reference"
        )

    def test_periodic_wrapping_near_boundary(self):
        """Hills near grid edges should contribute across the periodic boundary."""
        grid, fes, _ = parse_output(self.OUT, 1)
        near_plus_pi = grid[:, 0] > 2.9
        assert np.any(np.abs(fes[near_plus_pi]) > 0.01), (
            "FES near +pi should have contributions from hills wrapping across boundary"
        )

    def test_derivatives_consistent_with_finite_differences(self):
        """Analytical derivatives should approximately match central finite differences."""
        grid, fes, derivs = parse_output(self.OUT, 1)
        dx = grid[1, 0] - grid[0, 0]
        num_d = np.zeros_like(fes)
        n = len(fes)
        for i in range(n):
            num_d[i] = (fes[(i + 1) % n] - fes[(i - 1) % n]) / (2 * dx)
        np.testing.assert_allclose(
            derivs[:, 0], num_d, atol=0.05,
            err_msg="Analytical derivatives inconsistent with finite differences"
        )


# ===========================================================================
# 2D periodic FES (diagonal covariance)
# ===========================================================================

class TestFES2D:
    HILLS = '/app/hills_2d.dat'
    OUT = '/app/fes_2d.dat'
    GMIN, GMAX, GBINS = [-PI, -PI], [PI, PI], [40, 40]
    PERI = [True, True]

    @pytest.fixture(scope='class', autouse=True)
    def run_once(self):
        run_tool(self.HILLS, self.GMIN, self.GMAX, self.GBINS, self.PERI, self.OUT)

    def test_output_file_exists(self):
        assert os.path.isfile(self.OUT)

    def test_grid_point_count(self):
        _, fes, _ = parse_output(self.OUT, 2)
        assert len(fes) == 1600, f"Expected 1600 grid points, got {len(fes)}"

    def test_fes_values_match_reference(self):
        hd = parse_hills(self.HILLS)
        _, ref_fes, _ = reference_fes(hd, self.GMIN, self.GMAX, self.GBINS, self.PERI)
        _, fes, _ = parse_output(self.OUT, 2)
        np.testing.assert_allclose(
            fes, ref_fes, atol=1e-4,
            err_msg="2D FES values differ from reference"
        )

    def test_deriv_cv1_match_reference(self):
        hd = parse_hills(self.HILLS)
        _, _, ref_d = reference_fes(hd, self.GMIN, self.GMAX, self.GBINS, self.PERI)
        _, _, d = parse_output(self.OUT, 2)
        np.testing.assert_allclose(
            d[:, 0], ref_d[:, 0], atol=1e-3,
            err_msg="2D derivative wrt cv1 differs from reference"
        )

    def test_deriv_cv2_match_reference(self):
        hd = parse_hills(self.HILLS)
        _, _, ref_d = reference_fes(hd, self.GMIN, self.GMAX, self.GBINS, self.PERI)
        _, _, d = parse_output(self.OUT, 2)
        np.testing.assert_allclose(
            d[:, 1], ref_d[:, 1], atol=1e-3,
            err_msg="2D derivative wrt cv2 differs from reference"
        )

    def test_periodic_boundary_cv2(self):
        """Hills near cv2 boundary should wrap and contribute across the edge."""
        grid, fes, _ = parse_output(self.OUT, 2)
        near_plus_pi_cv2 = grid[:, 1] > 2.9
        assert np.any(np.abs(fes[near_plus_pi_cv2]) > 0.001), (
            "FES near cv2=+pi should have contributions wrapping across boundary"
        )


# ===========================================================================
# 2D multivariate FES (full covariance, non-periodic)
# ===========================================================================

class TestFES2DMultivariate:
    HILLS = '/app/hills_2d_mv.dat'
    OUT = '/app/fes_2d_mv.dat'
    GMIN, GMAX, GBINS = [0.0, 0.0], [4.0, 4.0], [30, 30]
    PERI = [False, False]

    @pytest.fixture(scope='class', autouse=True)
    def run_once(self):
        run_tool(self.HILLS, self.GMIN, self.GMAX, self.GBINS, self.PERI, self.OUT)

    def test_output_file_exists(self):
        assert os.path.isfile(self.OUT)

    def test_grid_point_count(self):
        _, fes, _ = parse_output(self.OUT, 2)
        assert len(fes) == 900, f"Expected 900 grid points, got {len(fes)}"

    def test_fes_values_match_reference(self):
        hd = parse_hills(self.HILLS)
        _, ref_fes, _ = reference_fes(hd, self.GMIN, self.GMAX, self.GBINS, self.PERI)
        _, fes, _ = parse_output(self.OUT, 2)
        np.testing.assert_allclose(
            fes, ref_fes, atol=1e-4,
            err_msg="Multivariate FES values differ from reference"
        )

    def test_deriv_cv1_match_reference(self):
        hd = parse_hills(self.HILLS)
        _, _, ref_d = reference_fes(hd, self.GMIN, self.GMAX, self.GBINS, self.PERI)
        _, _, d = parse_output(self.OUT, 2)
        np.testing.assert_allclose(
            d[:, 0], ref_d[:, 0], atol=1e-3,
            err_msg="Multivariate derivative wrt cv1 differs from reference"
        )

    def test_deriv_cv2_match_reference(self):
        hd = parse_hills(self.HILLS)
        _, _, ref_d = reference_fes(hd, self.GMIN, self.GMAX, self.GBINS, self.PERI)
        _, _, d = parse_output(self.OUT, 2)
        np.testing.assert_allclose(
            d[:, 1], ref_d[:, 1], atol=1e-3,
            err_msg="Multivariate derivative wrt cv2 differs from reference"
        )

    def test_multivariate_anisotropy(self):
        """Multivariate FES should exhibit anisotropic structure from off-diagonal covariance."""
        _, fes, _ = parse_output(self.OUT, 2)
        fes_2d = fes.reshape(30, 30)
        row_var = np.var(fes_2d, axis=1).mean()
        col_var = np.var(fes_2d, axis=0).mean()
        ratio = max(row_var, col_var) / (min(row_var, col_var) + 1e-15)
        assert ratio > 1.05, "Multivariate FES should show anisotropy from off-diagonal covariance"


# ===========================================================================
# Grid construction and well-tempered factor tests
# ===========================================================================

class TestGridConstruction:
    def test_uniform_spacing_1d(self):
        out = '/app/fes_grid_test.dat'
        run_tool('/app/hills_1d.dat', [-PI], [PI], [50], [True], out)
        g, _, _ = parse_output(out, 1)
        diffs = np.diff(g[:, 0])
        np.testing.assert_allclose(
            diffs, diffs[0], rtol=1e-6,
            err_msg="Grid points must be uniformly spaced"
        )

    def test_bin_center_positions(self):
        out = '/app/fes_bc_test.dat'
        run_tool('/app/hills_1d.dat', [-PI], [PI], [50], [True], out)
        g, _, _ = parse_output(out, 1)
        dx = 2 * PI / 50
        np.testing.assert_allclose(g[0, 0], -PI + dx / 2, atol=1e-5)
        np.testing.assert_allclose(g[-1, 0], PI - dx / 2, atol=1e-5)


class TestWellTemperedCorrection:
    def test_fes_is_negative_at_hill_locations(self):
        out = '/app/fes_wt_test.dat'
        run_tool('/app/hills_1d.dat', [-PI], [PI], [100], [True], out)
        _, fes, _ = parse_output(out, 1)
        assert np.min(fes) < -0.5, "FES minimum should be significantly negative"

    def test_correction_factor_applied(self):
        hd = parse_hills('/app/hills_1d.dat')
        gmin, gmax, gbins, peri = [-PI], [PI], [100], [True]
        _, ref_fes, _ = reference_fes(hd, gmin, gmax, gbins, peri)
        out = '/app/fes_factor_test.dat'
        run_tool('/app/hills_1d.dat', gmin, gmax, gbins, peri, out)
        _, fes, _ = parse_output(out, 1)
        np.testing.assert_allclose(
            np.min(fes), np.min(ref_fes), atol=1e-4,
            err_msg="FES minimum doesn't match; well-tempered correction may be wrong"
        )


# ===========================================================================
# Makefile integration tests
# ===========================================================================

class TestMakefileFES:
    def test_make_fes_produces_correct_output(self):
        """make fes must invoke sum_hills and produce accurate FES."""
        out = '/app/_test_make_fes.dat'
        result = subprocess.run(
            ['make', '-C', '/app', 'fes',
             'HILLS=/app/hills_1d.dat',
             f'GRID_MIN={-PI:.14f}',
             f'GRID_MAX={PI:.14f}',
             'GRID_BINS=100',
             'PERIODIC=true',
             f'OUTFILE={out}'],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"make fes failed: {result.stderr}"
        assert os.path.isfile(out), "make fes did not create output"
        hd = parse_hills('/app/hills_1d.dat')
        _, ref_fes, _ = reference_fes(hd, [-PI], [PI], [100], [True])
        _, fes, _ = parse_output(out, 1)
        np.testing.assert_allclose(fes, ref_fes, atol=1e-4,
                                   err_msg="make fes output differs from reference")

    def test_make_fes_2d(self):
        """make fes must handle 2D comma-separated grid parameters."""
        out = '/app/_test_make_fes_2d.dat'
        result = subprocess.run(
            ['make', '-C', '/app', 'fes',
             'HILLS=/app/hills_2d.dat',
             f'GRID_MIN={-PI:.14f},{-PI:.14f}',
             f'GRID_MAX={PI:.14f},{PI:.14f}',
             'GRID_BINS=20,20',
             'PERIODIC=true,true',
             f'OUTFILE={out}'],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, f"make fes 2D failed: {result.stderr}"
        _, fes, _ = parse_output(out, 2)
        assert len(fes) == 400

    def test_make_clean_runs(self):
        """make clean must succeed without error."""
        result = subprocess.run(
            ['make', '-C', '/app', 'clean'],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"make clean failed: {result.stderr}"


# ===========================================================================
# Convergence pipeline tests
# ===========================================================================

class TestConvergencePipeline:
    HILLS = '/app/hills_1d_long.dat'
    OUTFILE = '/app/_test_converge.json'
    GMIN = f'{-PI:.14f}'
    GMAX = f'{PI:.14f}'
    GBINS = '50'
    PERIODIC = 'true'
    WINDOWS = '4'

    @pytest.fixture(scope='class', autouse=True)
    def run_once(self):
        result = subprocess.run(
            ['make', '-C', '/app', 'converge',
             f'HILLS={self.HILLS}',
             f'GRID_MIN={self.GMIN}',
             f'GRID_MAX={self.GMAX}',
             f'GRID_BINS={self.GBINS}',
             f'PERIODIC={self.PERIODIC}',
             f'WINDOWS={self.WINDOWS}',
             f'OUTFILE={self.OUTFILE}'],
            capture_output=True, text=True, timeout=180
        )
        assert result.returncode == 0, (
            f"make converge failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def _load(self):
        with open(self.OUTFILE) as f:
            return json.load(f)

    def test_json_output_valid(self):
        data = self._load()
        assert isinstance(data, dict)
        for key in ('n_windows', 'windows', 'pairwise_metrics', 'final_rmsd'):
            assert key in data, f"Missing key: {key}"

    def test_n_windows_correct(self):
        data = self._load()
        assert data['n_windows'] == 4

    def test_windows_count(self):
        data = self._load()
        assert len(data['windows']) == 4

    def test_pairwise_count(self):
        data = self._load()
        assert len(data['pairwise_metrics']) == 3, (
            "4 windows should produce 3 pairwise comparisons"
        )

    def test_n_hills_monotonically_increasing(self):
        """Cumulative windows: each successive window must include more hills."""
        data = self._load()
        n_hills_list = [w['n_hills'] for w in data['windows']]
        for i in range(1, len(n_hills_list)):
            assert n_hills_list[i] > n_hills_list[i - 1], (
                f"n_hills must increase: window {i-1} has {n_hills_list[i-1]}, "
                f"window {i} has {n_hills_list[i]}"
            )

    def test_final_rmsd_matches_last_pair(self):
        data = self._load()
        last_rmsd = data['pairwise_metrics'][-1]['fes_rmsd']
        assert abs(data['final_rmsd'] - last_rmsd) < 1e-10, (
            f"final_rmsd ({data['final_rmsd']}) must equal last pairwise RMSD ({last_rmsd})"
        )

    def test_rmsd_non_negative(self):
        data = self._load()
        for m in data['pairwise_metrics']:
            assert m['fes_rmsd'] >= 0, "RMSD must be non-negative"
            assert m['fes_max_diff'] >= 0, "max_diff must be non-negative"

    def test_window_time_ends_increasing(self):
        data = self._load()
        times = [w['time_end'] for w in data['windows']]
        for i in range(1, len(times)):
            assert times[i] > times[i - 1], "Window time_end must be increasing"

    def test_convergence_metrics_accuracy(self):
        """Independently verify convergence metrics against reference computation."""
        data = self._load()
        hd = parse_hills(self.HILLS)
        gmin, gmax = [-PI], [PI]
        gbins, peri = [50], [True]

        prev_fes = None
        for i, win in enumerate(data['windows']):
            t_end = win['time_end']
            filtered = filter_hills_by_time(hd, t_end)
            _, ref_fes_vals, _ = reference_fes(filtered, gmin, gmax, gbins, peri)
            if prev_fes is not None:
                diff = ref_fes_vals - prev_fes
                ref_rmsd = float(np.sqrt(np.mean(diff ** 2)))
                ref_max = float(np.max(np.abs(diff)))
                reported = data['pairwise_metrics'][i - 1]
                assert abs(reported['fes_rmsd'] - ref_rmsd) < 1e-3, (
                    f"Pair {i-1},{i}: RMSD mismatch: "
                    f"reported={reported['fes_rmsd']:.6f}, expected={ref_rmsd:.6f}"
                )
                assert abs(reported['fes_max_diff'] - ref_max) < 1e-3, (
                    f"Pair {i-1},{i}: max_diff mismatch: "
                    f"reported={reported['fes_max_diff']:.6f}, expected={ref_max:.6f}"
                )
            prev_fes = ref_fes_vals


# ===========================================================================
# Subprocess integration tests (multi-tool interoperability)
# ===========================================================================

class TestConvergenceSubprocessIntegration:
    """Verify that converge.py uses preprocess.awk and sum_hills as actual subprocesses."""

    CONVERGE_CMD = [
        'make', '-C', '/app', 'converge',
        'HILLS=/app/hills_1d_long.dat',
        f'GRID_MIN={-PI:.14f}',
        f'GRID_MAX={PI:.14f}',
        'GRID_BINS=20',
        'PERIODIC=true',
        'WINDOWS=2',
        'OUTFILE=/app/_test_subprocess_check.json',
    ]

    def test_requires_preprocess_awk(self):
        """Convergence pipeline must fail when preprocess.awk is unavailable."""
        orig = '/app/preprocess.awk'
        bak = '/app/preprocess.awk.__test_hidden__'
        if not os.path.exists(orig):
            pytest.skip("preprocess.awk not found")
        shutil.move(orig, bak)
        try:
            result = subprocess.run(
                self.CONVERGE_CMD,
                capture_output=True, text=True, timeout=60
            )
            assert result.returncode != 0, (
                "converge pipeline should fail when preprocess.awk is missing"
            )
        finally:
            shutil.move(bak, orig)

    def test_requires_sum_hills(self):
        """Convergence pipeline must fail when sum_hills is unavailable."""
        orig = '/app/sum_hills'
        bak = '/app/sum_hills.__test_hidden__'
        if not os.path.exists(orig):
            pytest.skip("sum_hills not found")
        shutil.move(orig, bak)
        try:
            result = subprocess.run(
                self.CONVERGE_CMD,
                capture_output=True, text=True, timeout=60
            )
            assert result.returncode != 0, (
                "converge pipeline should fail when sum_hills is missing"
            )
        finally:
            shutil.move(bak, orig)


# ===========================================================================
# Alternate grid resolutions (anti-hardcode)
# ===========================================================================

class TestAlternateResolutions:
    """Run with different grid sizes than the reference files to prevent hardcoding."""

    def test_1d_50_bins(self):
        out = '/app/fes_alt50_1d.dat'
        gmin, gmax, gbins, peri = [-PI], [PI], [50], [True]
        run_tool('/app/hills_1d.dat', gmin, gmax, gbins, peri, out)
        hd = parse_hills('/app/hills_1d.dat')
        _, ref_fes, ref_d = reference_fes(hd, gmin, gmax, gbins, peri)
        _, fes, d = parse_output(out, 1)
        assert len(fes) == 50
        np.testing.assert_allclose(fes, ref_fes, atol=1e-4,
                                   err_msg="1D FES at 50 bins differs")
        np.testing.assert_allclose(d[:, 0], ref_d[:, 0], atol=1e-3,
                                   err_msg="1D derivatives at 50 bins differ")

    def test_1d_asymmetric_domain(self):
        out = '/app/fes_asym_1d.dat'
        gmin, gmax, gbins, peri = [-2.0], [2.0], [80], [True]
        run_tool('/app/hills_1d.dat', gmin, gmax, gbins, peri, out)
        hd = parse_hills('/app/hills_1d.dat')
        _, ref_fes, _ = reference_fes(hd, gmin, gmax, gbins, peri)
        _, fes, _ = parse_output(out, 1)
        assert len(fes) == 80
        np.testing.assert_allclose(fes, ref_fes, atol=1e-4,
                                   err_msg="1D FES with asymmetric domain differs")

    def test_2d_25x25_bins(self):
        out = '/app/fes_alt25_2d.dat'
        gmin, gmax, gbins, peri = [-PI, -PI], [PI, PI], [25, 25], [True, True]
        run_tool('/app/hills_2d.dat', gmin, gmax, gbins, peri, out)
        hd = parse_hills('/app/hills_2d.dat')
        _, ref_fes, ref_d = reference_fes(hd, gmin, gmax, gbins, peri)
        _, fes, d = parse_output(out, 2)
        assert len(fes) == 625
        np.testing.assert_allclose(fes, ref_fes, atol=1e-4,
                                   err_msg="2D FES at 25x25 differs")

    def test_2d_mv_20x20_bins(self):
        out = '/app/fes_alt20_mv.dat'
        gmin, gmax, gbins, peri = [0.0, 0.0], [4.0, 4.0], [20, 20], [False, False]
        run_tool('/app/hills_2d_mv.dat', gmin, gmax, gbins, peri, out)
        hd = parse_hills('/app/hills_2d_mv.dat')
        _, ref_fes, ref_d = reference_fes(hd, gmin, gmax, gbins, peri)
        _, fes, d = parse_output(out, 2)
        assert len(fes) == 400
        np.testing.assert_allclose(fes, ref_fes, atol=1e-4,
                                   err_msg="Multivariate FES at 20x20 differs")
        np.testing.assert_allclose(d[:, 0], ref_d[:, 0], atol=1e-3,
                                   err_msg="Multivariate d/dcv1 at 20x20 differs")
        np.testing.assert_allclose(d[:, 1], ref_d[:, 1], atol=1e-3,
                                   err_msg="Multivariate d/dcv2 at 20x20 differs")

    def test_2d_mv_wider_domain(self):
        out = '/app/fes_wide_mv.dat'
        gmin, gmax, gbins, peri = [-1.0, -1.0], [5.0, 5.0], [25, 25], [False, False]
        run_tool('/app/hills_2d_mv.dat', gmin, gmax, gbins, peri, out)
        hd = parse_hills('/app/hills_2d_mv.dat')
        _, ref_fes, _ = reference_fes(hd, gmin, gmax, gbins, peri)
        _, fes, _ = parse_output(out, 2)
        assert len(fes) == 625
        np.testing.assert_allclose(fes, ref_fes, atol=1e-4,
                                   err_msg="Multivariate FES with wider domain differs")


# ===========================================================================
# Output format compliance
# ===========================================================================

class TestOutputFormat:
    def test_2d_blank_line_separators(self):
        """2D output must have blank lines between cv1 blocks."""
        out = '/app/fes_fmt_2d.dat'
        run_tool('/app/hills_2d.dat', [-PI, -PI], [PI, PI], [5, 5], [True, True], out)
        with open(out) as f:
            raw = f.read()
        lines = [l for l in raw.split('\n') if not l.strip().startswith('#')]
        content = '\n'.join(lines)
        blocks = [b.strip() for b in content.split('\n\n') if b.strip()]
        assert len(blocks) == 5, (
            f"Expected 5 cv1 blocks separated by blank lines, got {len(blocks)}"
        )

    def test_2d_column_count(self):
        out = '/app/fes_fmt_cols.dat'
        run_tool('/app/hills_2d.dat', [-PI, -PI], [PI, PI], [5, 5], [True, True], out)
        with open(out) as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                cols = s.split()
                assert len(cols) == 5, f"Expected 5 columns, got {len(cols)}: {s}"

    def test_1d_column_count(self):
        out = '/app/fes_fmt_1d.dat'
        run_tool('/app/hills_1d.dat', [-PI], [PI], [10], [True], out)
        with open(out) as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                cols = s.split()
                assert len(cols) == 3, f"Expected 3 columns, got {len(cols)}: {s}"

    def test_precision_at_least_6_digits(self):
        out = '/app/fes_prec.dat'
        run_tool('/app/hills_1d.dat', [-PI], [PI], [10], [True], out)
        with open(out) as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                for val in s.split():
                    if '.' in val:
                        total_decimals = len(val.split('.')[1])
                        assert total_decimals >= 6, (
                            f"Value {val} has only {total_decimals} decimal places"
                        )
