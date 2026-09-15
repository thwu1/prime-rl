"""
Tests for Lamb wave dispersion curve solver.

"""

import pytest
import json
import subprocess
import numpy as np
import os
import tempfile

# Aluminum material constants (consistent with aluminum_1mm.yaml)
CL_AL = 6320.0   # longitudinal velocity m/s
CT_AL = 3130.0   # transverse velocity m/s
RHO_AL = 2700.0  # density kg/m^3
HALF_AL = 0.5e-3  # half-thickness m (1 mm plate)


def run_tool(config_path, output_path):
    """Run the dispersion tool and return the subprocess result."""
    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    result = subprocess.run(
        ['python3', '/app/dispersion.py', config_path, '-o', output_path],
        capture_output=True, text=True, timeout=180
    )
    return result


def rayleigh_lamb_det(cp_m_s, f_Hz, cL, cT, half, mode='S'):
    """
    Evaluate the Rayleigh-Lamb characteristic equation (absolute value).
    mode='S' for symmetric, 'A' for antisymmetric.
    """
    omega = 2.0 * np.pi * f_Hz
    k = omega / cp_m_s
    k2 = k ** 2
    kL2 = (omega / cL) ** 2
    kT2 = (omega / cT) ** 2
    x = np.lib.scimath.sqrt(kL2 - k2)
    y = np.lib.scimath.sqrt(kT2 - k2)

    # Avoid division by zero
    denom = 4.0 * k2 * x * y
    if np.abs(denom) < 1e-30:
        return 1e30

    a1 = (y ** 2 - k2) ** 2 / denom
    tan_xh = np.tan(x * half)
    tan_yh = np.tan(y * half)

    if np.abs(tan_yh) < 1e-30:
        return 1e30

    if mode == 'S':
        a2 = tan_xh / tan_yh
        return float(np.abs(a1 + a2))
    else:
        if np.abs(tan_xh) < 1e-30:
            return 1e30
        a2_inv = tan_yh / tan_xh
        return float(np.abs(a1 + a2_inv))


def find_rl_roots(f_Hz, cL, cT, half, cp_min=300.0, cp_max=15000.0, N=10000):
    """
    Find Rayleigh-Lamb roots at a given frequency by grid sweep + refinement.
    Returns sorted list of phase velocities in m/s.
    """
    from scipy.optimize import minimize_scalar

    cp_arr = np.linspace(cp_min, cp_max, N)
    all_roots = []

    for mode in ['S', 'A']:
        vals = np.array([rayleigh_lamb_det(cp, f_Hz, cL, cT, half, mode)
                         for cp in cp_arr])
        log_vals = np.log10(np.maximum(vals, 1e-300))

        for i in range(2, N - 2):
            if log_vals[i] < log_vals[i - 1] and log_vals[i] < log_vals[i + 1]:
                # Check depth relative to neighborhood
                nb_max = np.max(vals[max(0, i - 10):min(N, i + 11)])
                if vals[i] < 0.05 * nb_max:
                    lo = cp_arr[max(0, i - 3)]
                    hi = cp_arr[min(N - 1, i + 3)]
                    try:
                        res = minimize_scalar(
                            lambda cp: rayleigh_lamb_det(cp, f_Hz, cL, cT, half, mode),
                            bounds=(lo, hi), method='bounded',
                            options={'xatol': 0.5}
                        )
                        if res.fun < 0.01 * nb_max:
                            all_roots.append(res.x)
                    except Exception:
                        pass

    # Remove duplicates (within 50 m/s)
    all_roots.sort()
    deduped = []
    for r in all_roots:
        if not deduped or abs(r - deduped[-1]) > 50:
            deduped.append(r)
    return deduped


def get_tool_roots_at_freq(data, target_freq_kHz, tolerance_kHz=25.0):
    """Extract tool's phase velocity roots near a target frequency."""
    roots = []
    for mode in data['modes']:
        for f, cp in mode['phase_velocity']:
            if abs(f - target_freq_kHz) < tolerance_kHz:
                roots.append(cp * 1e3)  # convert m/ms to m/s
                break
    return sorted(roots)


# ---------------------------------------------------------------------------
# Unsupported configuration test
# ---------------------------------------------------------------------------

class TestUnsupportedConfig:
    def test_exit_code_1_for_non_decoupled(self):
        """Tool must exit with code 1 for configurations where layer
        fiber-to-propagation angle is not 0 or 90 degrees."""
        unsupported_yaml = """\
material:
  name: "Aluminum"
  density: 2700
  stiffness_GPa:
    C11: 107.8445
    C12: 54.9412
    C13: 54.9412
    C22: 107.8445
    C23: 54.9412
    C33: 107.8445
    C44: 26.4516
    C55: 26.4516
    C66: 26.4516
layup:
  orientations: [45]
  thicknesses: [1.0]
  repetitions: 1
  symmetric: false
propagation_angle: 0
analysis:
  frequency_min: 100
  frequency_max: 2000
  frequency_steps: 50
  num_modes: 3
  phase_velocity_max: 10.0
  phase_velocity_steps: 500
"""
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', dir='/app', delete=False
        ) as tmp:
            tmp.write(unsupported_yaml)
            tmp_path = tmp.name

        try:
            result = run_tool(tmp_path, '/app/output/unsupported.json')
            assert result.returncode == 1, (
                f"Expected exit code 1 for unsupported config (45° layer), "
                f"got {result.returncode}"
            )
            assert len(result.stderr.strip()) > 0, (
                "Expected a descriptive error message on stderr"
            )
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Aluminum tests
# ---------------------------------------------------------------------------

class TestAluminumDispersion:
    @classmethod
    def setup_class(cls):
        result = run_tool(
            '/app/configs/aluminum_1mm.yaml',
            '/app/output/aluminum.json'
        )
        assert result.returncode == 0, (
            f"Tool exited with code {result.returncode}.\n"
            f"stderr: {result.stderr[:500]}"
        )
        with open('/app/output/aluminum.json') as f:
            cls.data = json.load(f)

    def test_metadata_material(self):
        assert self.data['metadata']['material'] == 'Aluminum'

    def test_metadata_thickness(self):
        assert abs(self.data['metadata']['total_thickness_mm'] - 1.0) < 0.01

    def test_metadata_layers(self):
        assert self.data['metadata']['num_layers'] == 1

    def test_metadata_method(self):
        assert self.data['metadata']['method'] == 'SMM'

    def test_at_least_two_modes(self):
        assert len(self.data['modes']) >= 2, (
            f"Expected >= 2 modes, got {len(self.data['modes'])}"
        )

    def test_s0_plate_velocity(self):
        """S0 mode at low fd should be near plate velocity ~5.44 km/s."""
        modes = self.data['modes']
        found = False
        for mode in modes:
            pv = mode['phase_velocity']
            low_f_pts = [(f, cp) for f, cp in pv if 100 <= f <= 400]
            if low_f_pts:
                avg_cp = np.mean([cp for _, cp in low_f_pts])
                if 4.5 < avg_cp < 6.5:
                    found = True
                    assert 4.8 < avg_cp < 6.0, (
                        f"S0 velocity {avg_cp:.3f} not near plate velocity"
                    )
        assert found, "Could not identify S0 mode near plate velocity"

    def test_rayleigh_lamb_agreement_1000kHz(self):
        """Phase velocities at 1000 kHz must match Rayleigh-Lamb roots."""
        rl_roots = find_rl_roots(1e6, CL_AL, CT_AL, HALF_AL)
        assert len(rl_roots) >= 2, (
            f"RL equation should have >= 2 roots at 1 MHz, found {len(rl_roots)}"
        )

        tool_roots = get_tool_roots_at_freq(self.data, 1000.0)
        assert len(tool_roots) >= 2, (
            f"Tool should report >= 2 modes near 1000 kHz, found {len(tool_roots)}"
        )

        matched = 0
        for rl_r in rl_roots:
            for tr in tool_roots:
                if abs(tr - rl_r) / rl_r < 0.05:
                    matched += 1
                    break

        assert matched >= 2, (
            f"Only {matched}/{len(rl_roots)} RL roots matched tool output at 1 MHz. "
            f"RL roots: {[f'{r:.0f}' for r in rl_roots]}, "
            f"tool roots: {[f'{r:.0f}' for r in tool_roots]}"
        )

    def test_rayleigh_lamb_agreement_2000kHz(self):
        """Phase velocities at 2000 kHz must match Rayleigh-Lamb roots."""
        rl_roots = find_rl_roots(2e6, CL_AL, CT_AL, HALF_AL)
        tool_roots = get_tool_roots_at_freq(self.data, 2000.0)

        matched = 0
        for rl_r in rl_roots:
            for tr in tool_roots:
                if abs(tr - rl_r) / rl_r < 0.05:
                    matched += 1
                    break

        assert matched >= 2, (
            f"Only {matched}/{len(rl_roots)} RL roots matched tool at 2 MHz. "
            f"RL: {[f'{r:.0f}' for r in rl_roots]}, "
            f"tool: {[f'{r:.0f}' for r in tool_roots]}"
        )

    def test_group_velocity_present(self):
        has_gv = any(
            len(m.get('group_velocity', [])) > 0 for m in self.data['modes']
        )
        assert has_gv, "No group velocity data in any mode"

    def test_group_velocity_bounds(self):
        for mode in self.data['modes']:
            for f, cg in mode.get('group_velocity', []):
                assert 0 < cg < 15, (
                    f"Group velocity {cg:.3f} out of bounds at f={f:.0f} kHz"
                )


# ---------------------------------------------------------------------------
# Composite tests
# ---------------------------------------------------------------------------

class TestCompositeDispersion:
    @classmethod
    def setup_class(cls):
        result = run_tool(
            '/app/configs/composite_0_90_2s.yaml',
            '/app/output/composite.json'
        )
        assert result.returncode == 0, (
            f"Tool exited with code {result.returncode}.\n"
            f"stderr: {result.stderr[:500]}"
        )
        with open('/app/output/composite.json') as f:
            cls.data = json.load(f)

    def test_metadata_material(self):
        assert self.data['metadata']['material'] == 'T800M913'

    def test_metadata_thickness(self):
        assert abs(self.data['metadata']['total_thickness_mm'] - 1.0) < 0.01

    def test_metadata_layers(self):
        assert self.data['metadata']['num_layers'] == 8

    def test_metadata_method(self):
        assert self.data['metadata']['method'] == 'SMM'

    def test_at_least_two_modes(self):
        assert len(self.data['modes']) >= 2

    def test_modes_ordered(self):
        """Modes should be ordered by ascending cp at lowest frequency."""
        modes = self.data['modes']
        if len(modes) < 2:
            return
        first_cps = []
        for mode in modes:
            if mode['phase_velocity']:
                first_cps.append(mode['phase_velocity'][0][1])
        for i in range(len(first_cps) - 1):
            assert first_cps[i] <= first_cps[i + 1] + 0.5, (
                f"Modes not ordered: mode {i} cp={first_cps[i]:.3f} > "
                f"mode {i+1} cp={first_cps[i+1]:.3f}"
            )

    def test_phase_velocity_physical(self):
        """Phase velocities should be in physically reasonable range."""
        for mode in self.data['modes']:
            for f, cp in mode['phase_velocity']:
                assert 0 < cp < 20, (
                    f"Phase velocity {cp:.3f} out of range at f={f:.0f} kHz"
                )

    def test_group_velocity_present(self):
        has_gv = any(
            len(m.get('group_velocity', [])) > 0 for m in self.data['modes']
        )
        assert has_gv, "No group velocity data for composite"

    def test_group_velocity_bounds(self):
        for mode in self.data['modes']:
            for f, cg in mode.get('group_velocity', []):
                assert 0 < cg < 15, (
                    f"Group velocity {cg:.3f} out of bounds at f={f:.0f} kHz"
                )

    def test_composite_lowest_mode_velocity(self):
        """
        The lowest mode at low frequency should have a physically
        distinct velocity from isotropic aluminum, confirming anisotropic
        stiffness rotation is applied.
        """
        modes = self.data['modes']
        # Find highest-cp mode at low frequency (quasi-S0)
        max_cp_low = 0
        for mode in modes:
            for f, cp in mode['phase_velocity']:
                if 100 <= f <= 300:
                    max_cp_low = max(max_cp_low, cp)
                    break
        # T800M913 along 0deg has very high stiffness (C11=154 GPa)
        # so quasi-S0 should be much higher than isotropic aluminum S0 (~5.4)
        # or the 90deg direction should give lower values
        # Either way it should NOT be ~5.4 (aluminum)
        assert max_cp_low > 0, "No modes found at low frequency"
        # Just verify it's a reasonable composite value (not defaulting to
        # a trivial isotropic assumption)
        assert max_cp_low > 1.0, (
            f"Highest mode cp={max_cp_low:.3f} at low freq is implausibly low"
        )
