
"""
Independent verification of Rosenthal thermal model results for LPBF melt pool prediction.
Computes reference values using its own implementation and compares against agent results.
"""

import json
import os
import numpy as np
from scipy.optimize import brentq, minimize_scalar
from scipy.integrate import quad
import pytest


# ---------------------------------------------------------------------------
# Reference Rosenthal implementation
# ---------------------------------------------------------------------------

def rosenthal(xi, y, z, Q, k, alpha, V, T0):
    """Rosenthal quasi-steady-state solution for point source on semi-infinite body."""
    R = np.sqrt(xi**2 + y**2 + z**2)
    if R < 1e-15:
        return float('inf')
    return T0 + Q / (2.0 * np.pi * k * R) * np.exp(-V * (xi + R) / (2.0 * alpha))


def _max_temp_at_yz(y, z, Q, k, alpha, V, T0):
    """Maximum temperature at point (y,z) across all xi positions."""
    def neg_T(xi):
        R = np.sqrt(xi**2 + y**2 + z**2)
        if R < 1e-15:
            return -1e15
        return -(T0 + Q / (2.0 * np.pi * k * R) * np.exp(-V * (xi + R) / (2.0 * alpha)))

    r0 = np.sqrt(y**2 + z**2)
    xi_lo = -max(20.0 * r0, 2e-3)
    xi_hi = -1e-10
    res = minimize_scalar(neg_T, bounds=(xi_lo, xi_hi), method='bounded',
                          options={'xatol': 1e-12})
    return -res.fun


def _find_boundary(direction, Q, k, alpha, V, T0, T_target):
    """Find melt pool boundary extent in y (direction='y') or z (direction='z')."""
    def obj(val):
        if direction == 'y':
            return _max_temp_at_yz(val, 0.0, Q, k, alpha, V, T0) - T_target
        else:
            return _max_temp_at_yz(0.0, val, Q, k, alpha, V, T0) - T_target

    lo = 1e-8
    hi = 5e-4
    while obj(hi) > 0:
        hi *= 2
        if hi > 0.05:
            raise ValueError(f"Cannot bracket {direction} boundary")
    return brentq(obj, lo, hi, rtol=1e-8)


def _trailing_length(Q, k, T0, T_target):
    """Analytical trailing melt pool length on surface centerline."""
    return Q / (2.0 * np.pi * k * (T_target - T0))


def _preheat_from_tracks(x_eval, y_eval, t_eval, completed_tracks, Q, V, alpha, rho, Cp, L):
    """Compute residual temperature rise from completed tracks via Green's function integration."""
    T_rise = 0.0
    for (sx, ex, ty, ts) in completed_tracks:
        direction = 1.0 if ex > sx else -1.0
        t_end = ts + L / V
        if t_eval <= t_end + 1e-15:
            continue

        def integrand(s, _sx=sx, _dir=direction, _ty=ty, _ts=ts):
            xs = _sx + _dir * s
            tau = t_eval - (_ts + s / V)
            if tau < 1e-15:
                return 0.0
            dx = x_eval - xs
            dy = y_eval - _ty
            r2 = dx**2 + dy**2
            denom = (4.0 * np.pi * alpha * tau) ** 1.5
            if denom < 1e-300:
                return 0.0
            val = np.exp(-r2 / (4.0 * alpha * tau)) / denom
            return val if np.isfinite(val) else 0.0

        result, _ = quad(integrand, 0, L, limit=200, epsrel=1e-6, epsabs=1e-30)
        T_rise += (2.0 * Q / (V * rho * Cp)) * result

    return T_rise


# ---------------------------------------------------------------------------
# Compute all reference values
# ---------------------------------------------------------------------------

def _compute_reference():
    """Compute reference values independently."""
    with open('/app/config.json') as f:
        cfg = json.load(f)

    k = cfg['material']['thermal_conductivity_W_per_mK']
    rho = cfg['material']['density_kg_per_m3']
    Cp = cfg['material']['specific_heat_J_per_kgK']
    T_sol = cfg['material']['solidus_K']
    T_liq = cfg['material']['liquidus_K']
    T0 = cfg['material']['ambient_K']
    eta = cfg['material']['absorptivity']
    alpha = k / (rho * Cp)

    P = cfg['laser']['power_W']
    V = cfg['laser']['scan_speed_m_per_s']
    Q = eta * P

    L = cfg['pad']['track_length_m']
    h = cfg['pad']['hatch_spacing_m']
    n_tracks = cfg['pad']['num_tracks']
    t_turn = cfg['pad']['turnaround_time_s']

    A_pdas = cfg['solidification']['pdas_coefficient_um']
    n_pdas = cfg['solidification']['pdas_exponent']

    ref = {}

    # Single-track dimensions
    hw = _find_boundary('y', Q, k, alpha, V, T0, T_liq)
    dp = _find_boundary('z', Q, k, alpha, V, T0, T_liq)
    tl = _trailing_length(Q, k, T0, T_liq)

    ref['hw_um'] = hw * 1e6
    ref['depth_um'] = dp * 1e6
    ref['length_um'] = tl * 1e6

    # Build track timeline
    t_scan = L / V
    tracks = []
    t = 0.0
    for i in range(n_tracks):
        y_track = i * h
        if i % 2 == 0:
            start_x, end_x = 0.0, L
        else:
            start_x, end_x = L, 0.0
        tracks.append((start_x, end_x, y_track, t))
        t += t_scan + t_turn

    # Pre-heat temperatures
    preheat = {}
    for tn in cfg['queries']['preheat_tracks']:
        idx = tn - 1
        sx = tracks[idx][0]
        yt = tracks[idx][2]
        ts = tracks[idx][3]
        completed = tracks[:idx]
        rise = _preheat_from_tracks(sx, yt, ts, completed, Q, V, alpha, rho, Cp, L)
        preheat[str(tn)] = T0 + rise
    ref['preheat'] = preheat

    # Depth with pre-heat
    depth_pre = {}
    for tn in cfg['queries']['depth_tracks']:
        if tn == 1:
            T_pre = T0
        else:
            idx = tn - 1
            sx = tracks[idx][0]
            yt = tracks[idx][2]
            ts = tracks[idx][3]
            completed = tracks[:idx]
            rise = _preheat_from_tracks(sx, yt, ts, completed, Q, V, alpha, rho, Cp, L)
            T_pre = T0 + rise
        d_eff = _find_boundary('z', Q, k, alpha, V, T_pre, T_liq)
        depth_pre[str(tn)] = d_eff * 1e6
    ref['depth_pre'] = depth_pre

    # Cooling rate (analytical on surface centerline)
    cooling_rate = V * 2.0 * np.pi * k * (T_sol - T0) ** 2 / Q
    ref['cooling_rate'] = cooling_rate

    # PDAS
    pdas = A_pdas * cooling_rate ** (-n_pdas)
    ref['pdas_um'] = pdas

    return ref


# ---------------------------------------------------------------------------
# Pytest test class
# ---------------------------------------------------------------------------

class TestMeltPoolResults:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.ref = _compute_reference()
        results_path = '/app/results.json'
        assert os.path.exists(results_path), f"Results file not found at {results_path}"
        with open(results_path) as f:
            self.results = json.load(f)

    # -- structural checks --
    def test_required_keys(self):
        required = [
            'single_track_half_width_um',
            'single_track_depth_um',
            'single_track_length_um',
            'preheat_K',
            'depth_with_preheat_um',
            'cooling_rate_at_surface_K_per_s',
            'pdas_um',
        ]
        for key in required:
            assert key in self.results, f"Missing key: {key}"

    def test_preheat_keys(self):
        with open('/app/config.json') as f:
            cfg = json.load(f)
        for tn in cfg['queries']['preheat_tracks']:
            assert str(tn) in self.results['preheat_K'], \
                f"Missing preheat_K key for track {tn}"

    def test_depth_preheat_keys(self):
        with open('/app/config.json') as f:
            cfg = json.load(f)
        for tn in cfg['queries']['depth_tracks']:
            assert str(tn) in self.results['depth_with_preheat_um'], \
                f"Missing depth_with_preheat_um key for track {tn}"

    # -- single-track dimensions --
    def test_half_width(self):
        val = float(self.results['single_track_half_width_um'])
        ref = self.ref['hw_um']
        assert ref > 0, "Reference half-width must be positive"
        rel_err = abs(val - ref) / ref
        assert rel_err < 0.03, \
            f"Half-width mismatch: got {val:.2f}, expected {ref:.2f} (rel err {rel_err:.4f})"

    def test_depth(self):
        val = float(self.results['single_track_depth_um'])
        ref = self.ref['depth_um']
        assert ref > 0, "Reference depth must be positive"
        rel_err = abs(val - ref) / ref
        assert rel_err < 0.03, \
            f"Depth mismatch: got {val:.2f}, expected {ref:.2f} (rel err {rel_err:.4f})"

    def test_length(self):
        val = float(self.results['single_track_length_um'])
        ref = self.ref['length_um']
        assert ref > 0, "Reference length must be positive"
        rel_err = abs(val - ref) / ref
        assert rel_err < 0.02, \
            f"Length mismatch: got {val:.2f}, expected {ref:.2f} (rel err {rel_err:.4f})"

    # -- multi-track pre-heat --
    def test_preheat_values(self):
        T0 = 300.0
        for tn_str, ref_val in self.ref['preheat'].items():
            val = float(self.results['preheat_K'][tn_str])
            rise_ref = ref_val - T0
            rise_val = val - T0
            if rise_ref > 5.0:
                rel_err = abs(rise_val - rise_ref) / rise_ref
                assert rel_err < 0.10, \
                    f"Pre-heat track {tn_str}: rise got {rise_val:.2f} K, " \
                    f"expected {rise_ref:.2f} K (rel err {rel_err:.4f})"
            else:
                assert abs(val - ref_val) < 5.0, \
                    f"Pre-heat track {tn_str}: got {val:.2f}, expected {ref_val:.2f}"

    # -- depth with pre-heat --
    def test_depth_with_preheat(self):
        for tn_str, ref_val in self.ref['depth_pre'].items():
            val = float(self.results['depth_with_preheat_um'][tn_str])
            rel_err = abs(val - ref_val) / ref_val
            assert rel_err < 0.05, \
                f"Depth w/ preheat track {tn_str}: got {val:.2f}, " \
                f"expected {ref_val:.2f} (rel err {rel_err:.4f})"

    # -- depth monotonicity: pre-heat should increase melt pool depth --
    def test_depth_monotonic(self):
        depths = self.results['depth_with_preheat_um']
        track_nums = sorted(depths.keys(), key=lambda x: int(x))
        vals = [float(depths[t]) for t in track_nums]
        for i in range(1, len(vals)):
            assert vals[i] >= vals[i - 1] - 0.5, \
                f"Melt pool depth should not decrease with track number: " \
                f"track {track_nums[i-1]}={vals[i-1]:.2f}, track {track_nums[i]}={vals[i]:.2f}"

    # -- cooling rate --
    def test_cooling_rate(self):
        val = float(self.results['cooling_rate_at_surface_K_per_s'])
        ref = self.ref['cooling_rate']
        rel_err = abs(val - ref) / ref
        assert rel_err < 0.05, \
            f"Cooling rate: got {val:.0f}, expected {ref:.0f} (rel err {rel_err:.4f})"

    # -- PDAS --
    def test_pdas(self):
        val = float(self.results['pdas_um'])
        ref = self.ref['pdas_um']
        rel_err = abs(val - ref) / ref
        assert rel_err < 0.10, \
            f"PDAS: got {val:.4f}, expected {ref:.4f} (rel err {rel_err:.4f})"

    # -- physical sanity checks --
    def test_half_width_equals_depth(self):
        """For the Rosenthal point source, half-width and depth should be equal."""
        hw = float(self.results['single_track_half_width_um'])
        dp = float(self.results['single_track_depth_um'])
        rel_diff = abs(hw - dp) / max(hw, dp)
        assert rel_diff < 0.02, \
            f"Point source symmetry: half-width={hw:.2f}, depth={dp:.2f} should be equal"

    def test_length_greater_than_width(self):
        """Melt pool length should be much larger than width for high-speed LPBF."""
        length = float(self.results['single_track_length_um'])
        hw = float(self.results['single_track_half_width_um'])
        assert length > 5 * hw, \
            f"Expected length >> width for LPBF: length={length:.2f}, half-width={hw:.2f}"

    def test_cooling_rate_order_of_magnitude(self):
        """LPBF cooling rates should be in the 10^5 to 10^7 K/s range."""
        cr = float(self.results['cooling_rate_at_surface_K_per_s'])
        assert 1e5 < cr < 1e7, \
            f"Cooling rate {cr:.0f} K/s outside expected LPBF range (1e5-1e7)"

    def test_pdas_physical_range(self):
        """PDAS for LPBF should be in the sub-micron to few-micron range."""
        pdas = float(self.results['pdas_um'])
        assert 0.1 < pdas < 10.0, \
            f"PDAS {pdas:.2f} um outside expected LPBF range (0.1-10 um)"
