"""
Tests for the Pekeris waveguide normal mode solver.

Independently computes reference eigenvalues, group velocities,
incoherent TL, coherent TL, and pressure field, then compares
against the Fortran solver output.
"""

import os
import shutil
import subprocess

import numpy as np
import pytest
from scipy.optimize import brentq

# ── Physical parameters from waveguide.cfg ──────────────────────
FREQ = 100.0
WATER_DEPTH = 100.0
C_WATER = 1500.0
RHO_WATER = 1.0
C_BOTTOM = 1700.0
RHO_BOTTOM = 1.5
ATTN_DBPLAM = 0.5
SRC_DEPTH = 36.0
RCV_DEPTH = 46.0
RNG_MIN = 1.0
RNG_MAX = 100.0
N_RANGES = 200

OMEGA = 2.0 * np.pi * FREQ
KW = OMEGA / C_WATER
KB = OMEGA / C_BOTTOM

APP_DIR = '/app'


# ── Reference computation helpers ───────────────────────────────

def _char_func(kr, kw, kb, rho_w, rho_b, H):
    """Correct characteristic equation for the Pekeris waveguide."""
    gamma = np.sqrt(kw ** 2 - kr ** 2)
    delta = np.sqrt(kr ** 2 - kb ** 2)
    gH = gamma * H
    return rho_b * gamma * np.cos(gH) + rho_w * delta * np.sin(gH)


def _find_eigenvalues(freq, H, c_w, rho_w, c_b, rho_b):
    """Find all modal eigenvalues for a Pekeris waveguide."""
    omega = 2.0 * np.pi * freq
    kw = omega / c_w
    kb = omega / c_b
    n_scan = 500000
    kr_lo = kb * 1.0000001
    kr_hi = kw * 0.9999999
    kr_vals = np.linspace(kr_lo, kr_hi, n_scan)
    f_vals = np.array([_char_func(k, kw, kb, rho_w, rho_b, H) for k in kr_vals])

    eigenvalues = []
    for i in range(len(f_vals) - 1):
        if f_vals[i] * f_vals[i + 1] < 0:
            root = brentq(
                _char_func, kr_vals[i], kr_vals[i + 1],
                args=(kw, kb, rho_w, rho_b, H),
                xtol=1e-15, rtol=1e-15,
            )
            eigenvalues.append(root)

    return sorted(eigenvalues, reverse=True)


def _mode_norm(kr, kw, kb, rho_w, rho_b, H):
    """Correct normalization including bottom half-space."""
    gamma = np.sqrt(kw ** 2 - kr ** 2)
    delta = np.sqrt(kr ** 2 - kb ** 2)
    gH = gamma * H
    return (H / 2.0 - np.sin(2.0 * gH) / (4.0 * gamma)
            + (rho_w / rho_b) * np.sin(gH) ** 2 / (2.0 * delta))


def _modal_attenuation(kr, kw, kb, rho_w, rho_b, H, freq, c_b, attn_dbplam):
    """Compute modal attenuation via perturbation theory."""
    gamma = np.sqrt(kw ** 2 - kr ** 2)
    delta = np.sqrt(kr ** 2 - kb ** 2)
    gH = gamma * H
    nrm = _mode_norm(kr, kw, kb, rho_w, rho_b, H)
    lambda_b = c_b / freq
    alpha_np = attn_dbplam / (20.0 * np.log10(np.e) * lambda_b)
    return alpha_np * (rho_w / rho_b) * np.sin(gH) ** 2 / (delta * nrm)


def _reference_group_vel(freq, H, c_w, rho_w, c_b, rho_b):
    """Compute group velocity by numerical differentiation of dispersion."""
    df = freq * 1e-4
    krs_base = _find_eigenvalues(freq, H, c_w, rho_w, c_b, rho_b)
    krs_plus = _find_eigenvalues(freq + df, H, c_w, rho_w, c_b, rho_b)
    krs_minus = _find_eigenvalues(freq - df, H, c_w, rho_w, c_b, rho_b)

    vg = []
    n = min(len(krs_base), len(krs_plus), len(krs_minus))
    for i in range(n):
        domega = 2.0 * np.pi * 2.0 * df
        dkr = krs_plus[i] - krs_minus[i]
        if abs(dkr) > 1e-20:
            vg.append(domega / dkr)
        else:
            vg.append(None)
    return vg


def _reference_incoherent_tl(ranges_km, freq, H, c_w, rho_w, c_b, rho_b,
                              attn_dbplam, z_s, z_r):
    """Compute reference incoherent TL with correct physics."""
    omega = 2.0 * np.pi * freq
    kw = omega / c_w
    kb = omega / c_b
    eigenvalues = _find_eigenvalues(freq, H, c_w, rho_w, c_b, rho_b)

    tl = np.zeros(len(ranges_km))
    for ir, r_km in enumerate(ranges_km):
        r_m = r_km * 1000.0
        if r_m < 1.0:
            r_m = 1.0

        psq = 0.0
        for kr in eigenvalues:
            nrm = _mode_norm(kr, kw, kb, rho_w, rho_b, H)
            gamma = np.sqrt(kw ** 2 - kr ** 2)
            phi_s = np.sin(gamma * z_s) / np.sqrt(nrm)
            phi_r = np.sin(gamma * z_r) / np.sqrt(nrm)
            alpha_m = _modal_attenuation(kr, kw, kb, rho_w, rho_b, H,
                                         freq, c_b, attn_dbplam)
            psq += phi_s ** 2 * phi_r ** 2 * np.exp(-2.0 * alpha_m * r_m) \
                   / (kr * r_m)

        psq /= (8.0 * np.pi)
        tl[ir] = -10.0 * np.log10(psq) if psq > 0 else 999.0

    return tl


def _reference_coherent_tl(ranges_km, freq, H, c_w, rho_w, c_b, rho_b,
                            attn_dbplam, z_s, z_r):
    """Compute reference coherent TL using Hankel function asymptotics."""
    omega = 2.0 * np.pi * freq
    kw = omega / c_w
    kb = omega / c_b
    eigenvalues = _find_eigenvalues(freq, H, c_w, rho_w, c_b, rho_b)

    tl = np.zeros(len(ranges_km))
    for ir, r_km in enumerate(ranges_km):
        r_m = r_km * 1000.0
        if r_m < 1.0:
            r_m = 1.0

        p_re = 0.0
        p_im = 0.0
        for kr in eigenvalues:
            nrm = _mode_norm(kr, kw, kb, rho_w, rho_b, H)
            gamma = np.sqrt(kw ** 2 - kr ** 2)
            phi_s = np.sin(gamma * z_s) / np.sqrt(nrm)
            phi_r = np.sin(gamma * z_r) / np.sqrt(nrm)
            alpha_m = _modal_attenuation(kr, kw, kb, rho_w, rho_b, H,
                                         freq, c_b, attn_dbplam)
            ampl = phi_s * phi_r * np.exp(-alpha_m * r_m) \
                   / np.sqrt(8.0 * np.pi * kr * r_m)
            phase = kr * r_m - np.pi / 4.0
            p_re += ampl * np.cos(phase)
            p_im += ampl * np.sin(phase)

        p_sq = p_re ** 2 + p_im ** 2
        tl[ir] = -10.0 * np.log10(p_sq) if p_sq > 0 else 999.0

    return tl


def _reference_pressure_field_tl(depths, ranges_km, freq, H, c_w, rho_w,
                                  c_b, rho_b, attn_dbplam, z_s):
    """Compute reference coherent TL at specific depth-range grid points."""
    omega = 2.0 * np.pi * freq
    kw = omega / c_w
    kb = omega / c_b
    eigenvalues = _find_eigenvalues(freq, H, c_w, rho_w, c_b, rho_b)

    results = {}
    for z in depths:
        for r_km in ranges_km:
            r_m = r_km * 1000.0
            if r_m < 1.0:
                r_m = 1.0

            p_re = 0.0
            p_im = 0.0
            for kr in eigenvalues:
                nrm = _mode_norm(kr, kw, kb, rho_w, rho_b, H)
                gamma = np.sqrt(kw ** 2 - kr ** 2)
                phi_s = np.sin(gamma * z_s) / np.sqrt(nrm)
                phi_z = np.sin(gamma * z) / np.sqrt(nrm)
                alpha_m = _modal_attenuation(kr, kw, kb, rho_w, rho_b, H,
                                             freq, c_b, attn_dbplam)
                ampl = phi_s * phi_z * np.exp(-alpha_m * r_m) \
                       / np.sqrt(8.0 * np.pi * kr * r_m)
                phase = kr * r_m - np.pi / 4.0
                p_re += ampl * np.cos(phase)
                p_im += ampl * np.sin(phase)

            p_sq = p_re ** 2 + p_im ** 2
            tl = -10.0 * np.log10(p_sq) if p_sq > 0 else 999.0
            results[(z, r_km)] = tl
    return results


# ── File parsers ────────────────────────────────────────────────

def parse_modes_file(filepath):
    modes = []
    num_modes = None
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('# num_modes'):
                num_modes = int(line.split()[-1])
            elif line.startswith('#'):
                continue
            else:
                parts = line.split()
                if len(parts) >= 5:
                    modes.append({
                        'index': int(parts[0]),
                        'kr': float(parts[1]),
                        'phase_speed': float(parts[2]),
                        'group_speed': float(parts[3]),
                        'attenuation': float(parts[4]),
                    })
    return num_modes, modes


def parse_tl_file(filepath):
    ranges, tl_values = [], []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                ranges.append(float(parts[0]))
                tl_values.append(float(parts[1]))
    return np.array(ranges), np.array(tl_values)


def parse_pressure_field(filepath):
    """Parse pressure_field.dat into structured arrays."""
    depths, ranges, tl_vals = [], [], []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 3:
                depths.append(float(parts[0]))
                ranges.append(float(parts[1]))
                tl_vals.append(float(parts[2]))
    return np.array(depths), np.array(ranges), np.array(tl_vals)


# ── Cached reference data ──────────────────────────────────────

_REF_EIGENVALUES = None
_REF_GROUP_VEL = None


def ref_eigenvalues():
    global _REF_EIGENVALUES
    if _REF_EIGENVALUES is None:
        _REF_EIGENVALUES = _find_eigenvalues(
            FREQ, WATER_DEPTH, C_WATER, RHO_WATER, C_BOTTOM, RHO_BOTTOM
        )
    return _REF_EIGENVALUES


def ref_group_vel():
    global _REF_GROUP_VEL
    if _REF_GROUP_VEL is None:
        _REF_GROUP_VEL = _reference_group_vel(
            FREQ, WATER_DEPTH, C_WATER, RHO_WATER, C_BOTTOM, RHO_BOTTOM
        )
    return _REF_GROUP_VEL


# ── Tests ───────────────────────────────────────────────────────

class TestModesOutput:
    """Verify modal eigenvalue computation."""

    def test_modes_file_exists(self):
        assert os.path.exists(os.path.join(APP_DIR, 'modes.dat')), \
            "modes.dat not produced"

    def test_mode_count(self):
        ref = ref_eigenvalues()
        num_modes, modes = parse_modes_file(os.path.join(APP_DIR, 'modes.dat'))
        assert num_modes is not None, "Cannot parse num_modes header"
        assert num_modes == len(ref), \
            f"Mode count: got {num_modes}, expected {len(ref)}"
        assert len(modes) == len(ref), \
            f"Mode data lines: got {len(modes)}, expected {len(ref)}"

    def test_eigenvalue_accuracy(self):
        ref = ref_eigenvalues()
        _, modes = parse_modes_file(os.path.join(APP_DIR, 'modes.dat'))
        assert len(modes) == len(ref), "Mode count mismatch"

        for i, (mode, ref_kr) in enumerate(zip(modes, ref)):
            rel_err = abs(mode['kr'] - ref_kr) / abs(ref_kr)
            assert rel_err < 1e-6, (
                f"Mode {i + 1} kr: got {mode['kr']:.12e}, "
                f"expected {ref_kr:.12e}, rel_err={rel_err:.2e}"
            )

    def test_modes_sorted_descending(self):
        _, modes = parse_modes_file(os.path.join(APP_DIR, 'modes.dat'))
        for i in range(len(modes) - 1):
            assert modes[i]['kr'] >= modes[i + 1]['kr'], \
                f"Not sorted: mode {i + 1} kr < mode {i + 2} kr"

    def test_phase_speeds_physical(self):
        _, modes = parse_modes_file(os.path.join(APP_DIR, 'modes.dat'))
        for mode in modes:
            cp = mode['phase_speed']
            assert C_WATER <= cp <= C_BOTTOM * 1.001, \
                f"Mode {mode['index']}: phase speed {cp:.2f} outside " \
                f"[{C_WATER}, {C_BOTTOM}]"


class TestGroupVelocity:
    """Verify group velocity computation."""

    def test_group_speed_physical_range(self):
        """Group speeds must lie in (0, c_water) for trapped modes."""
        _, modes = parse_modes_file(os.path.join(APP_DIR, 'modes.dat'))
        for mode in modes:
            vg = mode['group_speed']
            assert 0 < vg < C_WATER, (
                f"Mode {mode['index']}: group speed {vg:.2f} "
                f"outside (0, {C_WATER})"
            )

    def test_group_speed_accuracy(self):
        """Group speeds must agree with numerical differentiation reference."""
        ref_vg = ref_group_vel()
        _, modes = parse_modes_file(os.path.join(APP_DIR, 'modes.dat'))
        n = min(len(modes), len(ref_vg))
        assert n > 0, "No modes to compare"

        for i in range(n):
            if ref_vg[i] is None:
                continue
            rel_err = abs(modes[i]['group_speed'] - ref_vg[i]) / abs(ref_vg[i])
            assert rel_err < 1e-3, (
                f"Mode {i + 1} vg: got {modes[i]['group_speed']:.4f}, "
                f"expected {ref_vg[i]:.4f}, rel_err={rel_err:.2e}"
            )

    def test_group_speed_ordering(self):
        """Group speed should decrease with mode number (descending kr)."""
        _, modes = parse_modes_file(os.path.join(APP_DIR, 'modes.dat'))
        if len(modes) < 2:
            pytest.skip("Need >= 2 modes for ordering check")
        for i in range(len(modes) - 1):
            assert modes[i]['group_speed'] >= modes[i + 1]['group_speed'] * 0.99, (
                f"Group speed not monotonically decreasing: "
                f"mode {i + 1} vg={modes[i]['group_speed']:.2f} < "
                f"mode {i + 2} vg={modes[i + 1]['group_speed']:.2f}"
            )


class TestIncoherentTL:
    """Verify incoherent transmission loss computation."""

    def test_tl_incoherent_file_exists(self):
        assert os.path.exists(os.path.join(APP_DIR, 'tl_incoherent.dat')), \
            "tl_incoherent.dat not produced"

    def test_tl_incoherent_accuracy(self):
        ranges, tl_computed = parse_tl_file(
            os.path.join(APP_DIR, 'tl_incoherent.dat'))
        assert len(ranges) == N_RANGES, \
            f"Expected {N_RANGES} range points, got {len(ranges)}"

        tl_ref = _reference_incoherent_tl(
            ranges, FREQ, WATER_DEPTH, C_WATER, RHO_WATER,
            C_BOTTOM, RHO_BOTTOM, ATTN_DBPLAM, SRC_DEPTH, RCV_DEPTH,
        )

        max_err = np.max(np.abs(tl_computed - tl_ref))
        assert max_err < 0.5, (
            f"Incoherent TL max error = {max_err:.4f} dB (limit 0.5 dB)"
        )

    def test_tl_incoherent_physical_range(self):
        _, tl_values = parse_tl_file(
            os.path.join(APP_DIR, 'tl_incoherent.dat'))
        assert np.all(tl_values > 10), \
            f"TL suspiciously low: min={np.min(tl_values):.1f} dB"
        assert np.all(tl_values < 200), \
            f"TL suspiciously high: max={np.max(tl_values):.1f} dB"

    def test_tl_increases_with_range(self):
        _, tl_values = parse_tl_file(
            os.path.join(APP_DIR, 'tl_incoherent.dat'))
        n = len(tl_values)
        q1 = np.mean(tl_values[:n // 4])
        q4 = np.mean(tl_values[3 * n // 4:])
        assert q4 > q1, \
            f"TL should increase with range: Q1_mean={q1:.1f}, Q4_mean={q4:.1f}"


class TestCoherentTL:
    """Verify coherent transmission loss computation."""

    def test_tl_coherent_file_exists(self):
        assert os.path.exists(os.path.join(APP_DIR, 'tl_coherent.dat')), \
            "tl_coherent.dat not produced"

    def test_tl_coherent_accuracy(self):
        ranges, tl_computed = parse_tl_file(
            os.path.join(APP_DIR, 'tl_coherent.dat'))
        assert len(ranges) == N_RANGES, \
            f"Expected {N_RANGES} range points, got {len(ranges)}"

        tl_ref = _reference_coherent_tl(
            ranges, FREQ, WATER_DEPTH, C_WATER, RHO_WATER,
            C_BOTTOM, RHO_BOTTOM, ATTN_DBPLAM, SRC_DEPTH, RCV_DEPTH,
        )

        max_err = np.max(np.abs(tl_computed - tl_ref))
        assert max_err < 0.5, (
            f"Coherent TL max error = {max_err:.4f} dB (limit 0.5 dB)"
        )

    def test_tl_coherent_physical_range(self):
        _, tl_values = parse_tl_file(
            os.path.join(APP_DIR, 'tl_coherent.dat'))
        assert np.all(tl_values > 0), \
            f"Coherent TL has non-physical values: min={np.min(tl_values):.1f} dB"
        assert np.all(tl_values < 300), \
            f"Coherent TL suspiciously high: max={np.max(tl_values):.1f} dB"

    def test_coherent_vs_incoherent_trend(self):
        """Coherent TL should oscillate around incoherent TL."""
        _, tl_incoh = parse_tl_file(
            os.path.join(APP_DIR, 'tl_incoherent.dat'))
        _, tl_coh = parse_tl_file(
            os.path.join(APP_DIR, 'tl_coherent.dat'))
        n = min(len(tl_incoh), len(tl_coh))
        if n < 10:
            pytest.skip("Not enough range points")
        mean_diff = np.mean(tl_coh[:n] - tl_incoh[:n])
        assert abs(mean_diff) < 5.0, (
            f"Coherent TL should oscillate around incoherent TL, "
            f"but mean offset is {mean_diff:.2f} dB"
        )


class TestPressureField:
    """Verify pressure field computation over depth-range grid."""

    def test_pressure_field_exists(self):
        assert os.path.exists(os.path.join(APP_DIR, 'pressure_field.dat')), \
            "pressure_field.dat not produced"

    def test_pressure_field_row_count(self):
        d, r, t = parse_pressure_field(
            os.path.join(APP_DIR, 'pressure_field.dat'))
        expected_rows = int(WATER_DEPTH) * N_RANGES
        assert len(d) == expected_rows, (
            f"Pressure field rows: got {len(d)}, expected {expected_rows}"
        )

    def test_pressure_field_accuracy(self):
        """Spot-check pressure field at selected depth-range points."""
        d, r, t = parse_pressure_field(
            os.path.join(APP_DIR, 'pressure_field.dat'))

        ranges_all = np.linspace(RNG_MIN, RNG_MAX, N_RANGES)
        check_depths = [20.0, 40.0, 60.0, 80.0]
        check_range_idx = [0, 49, 99, 149, 199]
        check_ranges = [ranges_all[i] for i in check_range_idx]

        ref = _reference_pressure_field_tl(
            check_depths, check_ranges, FREQ, WATER_DEPTH, C_WATER,
            RHO_WATER, C_BOTTOM, RHO_BOTTOM, ATTN_DBPLAM, SRC_DEPTH,
        )

        for z in check_depths:
            for r_km in check_ranges:
                mask = (np.abs(d - z) < 0.5) & (np.abs(r - r_km) < 0.01)
                assert np.any(mask), \
                    f"Missing pressure field point at ({z}m, {r_km}km)"
                computed_tl = t[mask][0]
                ref_tl = ref[(z, r_km)]
                err = abs(computed_tl - ref_tl)
                assert err < 1.0, (
                    f"Pressure field at ({z}m, {r_km}km): "
                    f"got {computed_tl:.2f}, expected {ref_tl:.2f}, "
                    f"err={err:.2f} dB"
                )

    def test_pressure_field_depth_variation(self):
        """TL must vary with depth (mode interference pattern)."""
        d, r, t = parse_pressure_field(
            os.path.join(APP_DIR, 'pressure_field.dat'))
        ranges_all = np.linspace(RNG_MIN, RNG_MAX, N_RANGES)
        mid_range = ranges_all[N_RANGES // 2]
        mask = np.abs(r - mid_range) < 0.01
        tl_vs_depth = t[mask]
        assert len(tl_vs_depth) > 1, "Not enough depth points"
        assert np.std(tl_vs_depth) > 1.0, (
            f"Pressure field shows no depth variation "
            f"(std={np.std(tl_vs_depth):.3f} dB)"
        )

    def test_pressure_field_matches_coherent_at_rcv(self):
        """Pressure field at receiver depth must match coherent TL."""
        d, r_pf, t_pf = parse_pressure_field(
            os.path.join(APP_DIR, 'pressure_field.dat'))
        _, tl_coh = parse_tl_file(os.path.join(APP_DIR, 'tl_coherent.dat'))
        ranges_all = np.linspace(RNG_MIN, RNG_MAX, N_RANGES)

        for idx in [10, 50, 100, 150]:
            r_km = ranges_all[idx]
            mask = (np.abs(d - RCV_DEPTH) < 0.5) & \
                   (np.abs(r_pf - r_km) < 0.01)
            if not np.any(mask):
                continue
            pf_tl = t_pf[mask][0]
            coh_tl = tl_coh[idx]
            assert abs(pf_tl - coh_tl) < 0.5, (
                f"Pressure field at rcv depth ({RCV_DEPTH}m) != coherent TL "
                f"at r={r_km:.1f}km: {pf_tl:.2f} vs {coh_tl:.2f}"
            )


class TestAlternateConfig:
    """Verify solver works with different parameters (no hardcoding)."""

    def test_alternate_frequency_and_depth(self):
        # Save original outputs
        output_files = ('modes.dat', 'tl_incoherent.dat',
                        'tl_coherent.dat', 'pressure_field.dat')
        for fn in output_files:
            src = os.path.join(APP_DIR, fn)
            if os.path.exists(src):
                shutil.copy2(src, src + '.orig')

        alt_freq = 120.0
        alt_depth = 80.0
        alt_cw = 1480.0
        alt_cb = 1700.0
        alt_rw = 1.025
        alt_rb = 1.8
        alt_attn = 0.3
        alt_zs = 30.0
        alt_zr = 50.0
        alt_rmin = 2.0
        alt_rmax = 50.0
        alt_nranges = 80

        try:
            alt_cfg = os.path.join(APP_DIR, 'waveguide_alt.cfg')
            with open(alt_cfg, 'w') as f:
                f.write(f"frequency_hz     {alt_freq}\n")
                f.write(f"water_depth_m    {alt_depth}\n")
                f.write(f"water_speed_mps  {alt_cw}\n")
                f.write(f"water_density    {alt_rw}\n")
                f.write(f"bottom_speed_mps {alt_cb}\n")
                f.write(f"bottom_density   {alt_rb}\n")
                f.write(f"bottom_attn_dbplam {alt_attn}\n")
                f.write(f"source_depth_m   {alt_zs}\n")
                f.write(f"receiver_depth_m {alt_zr}\n")
                f.write(f"min_range_km     {alt_rmin}\n")
                f.write(f"max_range_km     {alt_rmax}\n")
                f.write(f"num_ranges       {alt_nranges}\n")

            ret = subprocess.run(
                ['./pekeris_solver', 'waveguide_alt.cfg'],
                cwd=APP_DIR, capture_output=True, timeout=60,
            )
            assert ret.returncode == 0, \
                f"Solver failed at alt config: {ret.stderr.decode()}"

            # Check eigenvalues
            ref_alt = _find_eigenvalues(alt_freq, alt_depth, alt_cw, alt_rw,
                                        alt_cb, alt_rb)
            num_modes, modes = parse_modes_file(
                os.path.join(APP_DIR, 'modes.dat'))

            assert num_modes == len(ref_alt), \
                f"Alt mode count: got {num_modes}, expected {len(ref_alt)}"

            for j, (mode, ref_kr) in enumerate(zip(modes, ref_alt)):
                rel_err = abs(mode['kr'] - ref_kr) / abs(ref_kr)
                assert rel_err < 1e-6, (
                    f"Alt mode {j + 1} kr: got {mode['kr']:.12e}, "
                    f"expected {ref_kr:.12e}, rel_err={rel_err:.2e}"
                )

            # Check group velocities
            ref_vg_alt = _reference_group_vel(alt_freq, alt_depth, alt_cw,
                                              alt_rw, alt_cb, alt_rb)
            n_check = min(len(modes), len(ref_vg_alt))
            for j in range(n_check):
                if ref_vg_alt[j] is None:
                    continue
                vg = modes[j]['group_speed']
                assert 0 < vg < alt_cw, \
                    f"Alt mode {j + 1}: vg={vg:.2f} outside (0, {alt_cw})"
                rel_err = abs(vg - ref_vg_alt[j]) / abs(ref_vg_alt[j])
                assert rel_err < 1e-3, (
                    f"Alt mode {j + 1} vg: got {vg:.4f}, "
                    f"expected {ref_vg_alt[j]:.4f}, rel_err={rel_err:.2e}"
                )

            # Check incoherent TL
            ranges, tl_comp = parse_tl_file(
                os.path.join(APP_DIR, 'tl_incoherent.dat'))
            tl_ref = _reference_incoherent_tl(
                ranges, alt_freq, alt_depth, alt_cw, alt_rw,
                alt_cb, alt_rb, alt_attn, alt_zs, alt_zr,
            )
            max_err = np.max(np.abs(tl_comp - tl_ref))
            assert max_err < 0.5, \
                f"Alt incoherent TL max error = {max_err:.4f} dB"

            # Check coherent TL
            ranges_c, tl_comp_c = parse_tl_file(
                os.path.join(APP_DIR, 'tl_coherent.dat'))
            tl_ref_c = _reference_coherent_tl(
                ranges_c, alt_freq, alt_depth, alt_cw, alt_rw,
                alt_cb, alt_rb, alt_attn, alt_zs, alt_zr,
            )
            max_err_c = np.max(np.abs(tl_comp_c - tl_ref_c))
            assert max_err_c < 0.5, \
                f"Alt coherent TL max error = {max_err_c:.4f} dB"

            # Check pressure field
            pf_path = os.path.join(APP_DIR, 'pressure_field.dat')
            assert os.path.exists(pf_path), \
                "Alt config: pressure_field.dat not produced"
            d, r_pf, t_pf = parse_pressure_field(pf_path)
            expected_pf_rows = int(alt_depth) * alt_nranges
            assert len(d) == expected_pf_rows, (
                f"Alt pressure field rows: got {len(d)}, "
                f"expected {expected_pf_rows}"
            )

            # Spot-check pressure field at a few points
            alt_ranges_all = np.linspace(alt_rmin, alt_rmax, alt_nranges)
            pf_check_depths = [20.0, 40.0, 60.0]
            pf_check_ridx = [0, alt_nranges // 2, alt_nranges - 1]
            pf_check_ranges = [alt_ranges_all[i] for i in pf_check_ridx]
            ref_pf = _reference_pressure_field_tl(
                pf_check_depths, pf_check_ranges, alt_freq, alt_depth,
                alt_cw, alt_rw, alt_cb, alt_rb, alt_attn, alt_zs,
            )
            for z in pf_check_depths:
                for r_km in pf_check_ranges:
                    mask = (np.abs(d - z) < 0.5) & (np.abs(r_pf - r_km) < 0.01)
                    if not np.any(mask):
                        continue
                    computed = t_pf[mask][0]
                    expected = ref_pf[(z, r_km)]
                    err = abs(computed - expected)
                    assert err < 1.0, (
                        f"Alt pressure field at ({z}m, {r_km}km): "
                        f"err={err:.2f} dB"
                    )

        finally:
            # Restore original outputs
            for fn in output_files:
                bak = os.path.join(APP_DIR, fn + '.orig')
                if os.path.exists(bak):
                    shutil.copy2(bak, os.path.join(APP_DIR, fn))
                    os.remove(bak)
            alt = os.path.join(APP_DIR, 'waveguide_alt.cfg')
            if os.path.exists(alt):
                os.remove(alt)
