"""Tests for mineral dust emission physics module.

Independently computes reference values using Python implementations
of the same physics equations, then compiles and runs the Fortran
driver to verify numerical correctness across multiple scenarios.
"""

import subprocess
import os
import tempfile
import math
import pytest

# ======== Physical constants (must match Fortran module) ========
GRAV = 9.81
A_N = 0.0123
GAMMA = 1.65e-4
RHO_A0 = 1.225
U_ST0 = 0.16
C_D0 = 4.4e-5
C_E = 2.0
C_A = 2.7

# Kok (2011) distribution constants
D_S_KOK = 3.4e-6
SIGMA_S = 3.0
LAMBDA_K = 12.0e-6
BIN_BOUNDS = [0.2e-6, 2.0e-6, 3.6e-6, 6.0e-6, 12.0e-6, 20.0e-6]

# Characteristic saltation diameter for pipeline
D_CHAR = 75.0e-6

# ======== Reference physics implementations ========

def ref_threshold_ustar(Dp, rho_p, rho_a):
    """Shao & Lu (2000) threshold friction velocity."""
    return math.sqrt(A_N * (rho_p * GRAV * Dp / rho_a
                            + GAMMA / (rho_a * Dp)))


def ref_fecan_moisture(w_pct, clay_pct):
    """Fecan et al. (1999) soil moisture correction."""
    w_prime = 0.0014 * clay_pct**2 + 0.17 * clay_pct
    if w_pct <= w_prime:
        return 1.0
    return math.sqrt(1.0 + 1.21 * (w_pct - w_prime)**0.68)


def ref_drag_partition(z0, z0s):
    """MacKinnon et al. (2004) drag partition correction."""
    if z0 > z0s and z0s > 0:
        val = 1.0 - math.log(z0 / z0s) / math.log(
            0.7 * (122.55 / z0s)**0.8)
        return max(0.0, min(1.0, val))
    return 1.0


def ref_mb95_ratio(clay_frac, max_ratio=2e-4):
    """Marticorena & Bergametti (1995) V/H flux ratio."""
    if clay_frac > 0.2:
        return max_ratio
    return 10.0**(13.4 * clay_frac - 6.0)


def ref_white79_flux(rho_a, ustar, ustar_t):
    """White (1979) horizontal saltation flux."""
    if ustar > ustar_t:
        return (rho_a / GRAV) * (ustar + ustar_t) * (ustar**2 - ustar_t**2)
    return 0.0


def ref_k14_flux(ustar, ustar_t, rho_a, f_erod, k_gamma):
    """Kok et al. (2014) vertical dust flux."""
    if ustar > ustar_t and f_erod > 0:
        u_st = ustar_t * math.sqrt(rho_a / RHO_A0)
        u_st = max(u_st, U_ST0)
        f_ust = (u_st - U_ST0) / U_ST0
        C_d = C_D0 * math.exp(-C_E * f_ust)
        return (C_d * f_erod * k_gamma * rho_a
                * ((ustar**2 - ustar_t**2) / u_st)
                * (ustar / ustar_t)**(C_A * f_ust))
    return 0.0


def ref_foroutan_z0(lam, h_eff):
    """Foroutan et al. (2017) aeolian surface roughness."""
    if lam < 0.2:
        z0h = 0.96 * lam**1.07
    else:
        z0h = 0.083 * lam**(-0.46)
    return z0h * h_eff


def ref_grav_moisture(w_vol, f_sand, f_w):
    """Zender gravimetric soil moisture conversion."""
    Q_s = 0.489 - 0.126 * f_sand
    rho_bulk = 2500.0 * (1.0 - Q_s)
    return 100.0 * f_w * (1000.0 / rho_bulk) * w_vol


def ref_erodibility(z0, is_bedrock):
    """Laurent et al. (2008) erodibility factor."""
    if is_bedrock:
        return 0.0
    if z0 <= 3e-5:
        return 1.0
    if z0 < 5e-3:
        return max(0.0, 0.7304 - 0.0804 * math.log10(100.0 * z0))
    return 0.0


def ref_sep(clay, silt, sand):
    """FENGSHA/CMAQ soil erodibility potential."""
    return 0.08 * clay + 1.0 * silt + 0.12 * sand


# ======== Kok (2011) size distribution ========

def _kok_integrand(D):
    """Kok (2011) mass size distribution integrand g(D)."""
    ln_arg = math.log(D / D_S_KOK) / (math.sqrt(2.0) * SIGMA_S)
    return (1.0 / D) * (1.0 + math.erf(ln_arg)) * math.exp(-(D / LAMBDA_K)**3)


def _simpson(f, a, b, n=1000):
    """Simpson's rule integration with n subintervals (must be even)."""
    if n % 2 != 0:
        n += 1
    h = (b - a) / n
    s = f(a) + f(b)
    for i in range(1, n, 2):
        s += 4.0 * f(a + i * h)
    for i in range(2, n - 1, 2):
        s += 2.0 * f(a + i * h)
    return s * h / 3.0


def ref_kok2011_size_fraction(D_low, D_high):
    """Fraction of emitted dust mass in [D_low, D_high]."""
    num = _simpson(_kok_integrand, D_low, D_high, 1000)
    den = _simpson(_kok_integrand, BIN_BOUNDS[0], BIN_BOUNDS[-1], 1000)
    if den > 0:
        return num / den
    return 0.0


# ======== Test scenarios ========

SCENARIOS = [
    {
        "name": "dry_desert_sand",
        "Dp": 75e-6, "rho_p": 2650.0, "rho_a": 1.225,
        "ustar": 0.5, "clay_frac": 0.05, "silt_frac": 0.15,
        "sand_frac": 0.80, "w_vol": 0.0,
        "z0": 1e-4, "z0s": 2.5e-6,
        "lambda_r": 0.05, "h_eff": 0.02,
        "bedrock": False, "f_w": 0.5,
    },
    {
        "name": "moist_loam",
        "Dp": 125e-6, "rho_p": 2650.0, "rho_a": 1.15,
        "ustar": 0.8, "clay_frac": 0.18, "silt_frac": 0.39,
        "sand_frac": 0.43, "w_vol": 0.12,
        "z0": 5e-4, "z0s": 4.17e-6,
        "lambda_r": 0.10, "h_eff": 0.03,
        "bedrock": False, "f_w": 0.5,
    },
    {
        "name": "vegetated_shrubland",
        "Dp": 210e-6, "rho_p": 2650.0, "rho_a": 1.15,
        "ustar": 1.2, "clay_frac": 0.10, "silt_frac": 0.30,
        "sand_frac": 0.60, "w_vol": 0.03,
        "z0": 2e-3, "z0s": 7e-6,
        "lambda_r": 0.35, "h_eff": 0.10,
        "bedrock": False, "f_w": 0.5,
    },
    {
        "name": "bedrock_no_emission",
        "Dp": 125e-6, "rho_p": 2650.0, "rho_a": 1.225,
        "ustar": 1.0, "clay_frac": 0.05, "silt_frac": 0.10,
        "sand_frac": 0.85, "w_vol": 0.0,
        "z0": 1e-5, "z0s": 4.17e-6,
        "lambda_r": 0.001, "h_eff": 0.02,
        "bedrock": True, "f_w": 0.5,
    },
]


# ======== Helpers ========

def build_code():
    """Compile the Fortran module and driver."""
    subprocess.run(
        ["make", "-C", "/app", "clean"],
        capture_output=True, text=True, timeout=60
    )
    result = subprocess.run(
        ["make", "-C", "/app", "all"],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Build failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def run_scenario(scenario):
    """Write input file, run driver, parse output dict."""
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.dat', delete=False
    ) as f:
        f.write(f"{scenario['Dp']}\n")
        f.write(f"{scenario['rho_p']}\n")
        f.write(f"{scenario['rho_a']}\n")
        f.write(f"{scenario['ustar']}\n")
        f.write(f"{scenario['clay_frac']}\n")
        f.write(f"{scenario['silt_frac']}\n")
        f.write(f"{scenario['sand_frac']}\n")
        f.write(f"{scenario['w_vol']}\n")
        f.write(f"{scenario['z0']}\n")
        f.write(f"{scenario['z0s']}\n")
        f.write(f"{scenario['lambda_r']}\n")
        f.write(f"{scenario['h_eff']}\n")
        f.write(f"{1 if scenario['bedrock'] else 0}\n")
        f.write(f"{scenario['f_w']}\n")
        input_file = f.name

    try:
        result = subprocess.run(
            ["/app/dust_driver", input_file],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Driver failed (exit {result.returncode}):\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
    finally:
        os.unlink(input_file)

    values = {}
    for line in result.stdout.strip().split('\n'):
        parts = line.split()
        if len(parts) >= 2:
            values[parts[0]] = float(parts[1])
    return values


def compute_individual_reference(s):
    """Compute reference values for individual routine diagnostics."""
    ref = {}
    ref['threshold_ustar'] = ref_threshold_ustar(
        s['Dp'], s['rho_p'], s['rho_a'])
    ref['grav_moisture_pct'] = ref_grav_moisture(
        s['w_vol'], s['sand_frac'], s['f_w'])
    ref['moisture_factor'] = ref_fecan_moisture(
        ref['grav_moisture_pct'], s['clay_frac'] * 100.0)
    ref['drag_partition'] = ref_drag_partition(s['z0'], s['z0s'])
    ref['ustar_soil'] = ref['drag_partition'] * s['ustar']
    ref['ustar_threshold'] = ref['threshold_ustar'] * ref['moisture_factor']
    ref['mb95_ratio'] = ref_mb95_ratio(s['clay_frac'], 2e-4)
    ref['sep'] = ref_sep(s['clay_frac'], s['silt_frac'], s['sand_frac'])
    ref['white79_flux'] = ref_white79_flux(
        s['rho_a'], ref['ustar_soil'], ref['ustar_threshold'])
    ref['erodibility'] = ref_erodibility(s['z0'], s['bedrock'])
    k_gamma = s['clay_frac']
    ref['k14_flux'] = ref_k14_flux(
        ref['ustar_soil'], ref['ustar_threshold'],
        s['rho_a'], ref['erodibility'], k_gamma)
    ref['foroutan_z0'] = ref_foroutan_z0(s['lambda_r'], s['h_eff'])
    return ref


def compute_size_fraction_reference():
    """Compute reference size fractions (same for all scenarios)."""
    fracs = {}
    for i in range(5):
        key = f'size_frac_{i+1}'
        fracs[key] = ref_kok2011_size_fraction(BIN_BOUNDS[i], BIN_BOUNDS[i+1])
    return fracs


def compute_bin_emission_reference(s):
    """Compute reference per-bin emissions using the coupled pipeline."""
    # Pipeline uses D_CHAR, not scenario Dp
    ust0 = ref_threshold_ustar(D_CHAR, s['rho_p'], s['rho_a'])
    w_pct = ref_grav_moisture(s['w_vol'], s['sand_frac'], s['f_w'])
    fm = ref_fecan_moisture(w_pct, s['clay_frac'] * 100.0)
    R = ref_drag_partition(s['z0'], s['z0s'])
    u_soil = R * s['ustar']
    u_thresh = ust0 * fm
    f_erod = ref_erodibility(s['z0'], s['bedrock'])
    k_gamma = s['clay_frac']
    F_total = ref_k14_flux(u_soil, u_thresh, s['rho_a'], f_erod, k_gamma)

    bins = {}
    for i in range(5):
        frac = ref_kok2011_size_fraction(BIN_BOUNDS[i], BIN_BOUNDS[i+1])
        bins[f'bin_emission_{i+1}'] = F_total * frac
    return bins, F_total


def check_values(actual, expected, label, rtol=1e-3):
    """Compare actual vs expected values, return error list."""
    errors = []
    for key in expected:
        exp_val = expected[key]
        act_val = actual.get(key)
        if act_val is None:
            errors.append(f"  {key}: MISSING from output")
            continue

        if abs(exp_val) < 1e-15:
            if abs(act_val) > 1e-10:
                errors.append(
                    f"  {key}: got {act_val:.6e}, expected ~0.0"
                )
        else:
            rel_err = abs(act_val - exp_val) / abs(exp_val)
            if rel_err > rtol:
                errors.append(
                    f"  {key}: got {act_val:.6e}, expected {exp_val:.6e}"
                    f" (rel_err={rel_err:.2e})"
                )
    return errors


# ======== Tests ========

class TestBuild:
    """Verify the code compiles successfully."""

    def test_compile(self):
        build_code()
        assert os.path.isfile("/app/dust_driver"), \
            "dust_driver executable not found after build"


class TestIndividualRoutines:
    """Verify individual physics routines produce correct results."""

    @classmethod
    def setup_class(cls):
        build_code()

    @pytest.mark.parametrize(
        "scenario", SCENARIOS,
        ids=[s["name"] for s in SCENARIOS]
    )
    def test_individual_values(self, scenario):
        """Check 12 individual routine outputs against reference."""
        out = run_scenario(scenario)
        ref = compute_individual_reference(scenario)
        errors = check_values(out, ref, scenario['name'])
        assert not errors, (
            f"Scenario '{scenario['name']}' individual routine errors:\n"
            + "\n".join(errors)
        )

    @pytest.mark.parametrize(
        "scenario", [s for s in SCENARIOS if not s["bedrock"]],
        ids=[s["name"] for s in SCENARIOS if not s["bedrock"]]
    )
    def test_nonzero_emission(self, scenario):
        """Non-bedrock scenarios with u* > u*t must produce emission."""
        out = run_scenario(scenario)
        ref = compute_individual_reference(scenario)
        if ref['ustar_soil'] > ref['ustar_threshold']:
            assert out.get('k14_flux', 0) > 0, \
                f"k14_flux should be > 0 for {scenario['name']}"
            assert out.get('white79_flux', 0) > 0, \
                f"white79_flux should be > 0 for {scenario['name']}"

    def test_bedrock_zero_k14(self):
        """Bedrock must produce zero K14 flux via erodibility."""
        bedrock = [s for s in SCENARIOS if s["bedrock"]][0]
        out = run_scenario(bedrock)
        assert abs(out.get('erodibility', 1.0)) < 1e-10, \
            "Erodibility must be 0 for bedrock"
        assert abs(out.get('k14_flux', 1.0)) < 1e-10, \
            "K14 flux must be 0 for bedrock"

    def test_threshold_increases_with_particle_size(self):
        """Threshold velocity should increase for larger particles."""
        small = dict(SCENARIOS[0])
        small['Dp'] = 75e-6
        large = dict(SCENARIOS[0])
        large['Dp'] = 690e-6

        out_small = run_scenario(small)
        out_large = run_scenario(large)
        assert out_large['threshold_ustar'] > out_small['threshold_ustar'], \
            "Threshold should increase for larger particles"

    def test_moisture_suppresses_emission(self):
        """Higher moisture should increase threshold (reduce emission)."""
        dry = dict(SCENARIOS[0])
        dry['w_vol'] = 0.0
        wet = dict(SCENARIOS[0])
        wet['w_vol'] = 0.20

        out_dry = run_scenario(dry)
        out_wet = run_scenario(wet)
        assert out_wet['moisture_factor'] >= out_dry['moisture_factor'], \
            "Moisture factor should increase with soil moisture"
        assert out_wet['ustar_threshold'] >= out_dry['ustar_threshold'], \
            "Threshold should increase with moisture"


class TestSizeDistribution:
    """Verify Kok (2011) size distribution implementation."""

    @classmethod
    def setup_class(cls):
        build_code()

    def test_size_fractions_match_reference(self):
        """Size fractions must match Kok (2011) reference values."""
        out = run_scenario(SCENARIOS[0])
        ref_fracs = compute_size_fraction_reference()
        errors = check_values(out, ref_fracs, "size_fractions")
        assert not errors, (
            "Size fraction errors:\n" + "\n".join(errors)
        )

    def test_size_fractions_sum_to_one(self):
        """Size fractions must sum to approximately 1.0."""
        out = run_scenario(SCENARIOS[0])
        total = sum(out.get(f'size_frac_{i}', 0) for i in range(1, 6))
        assert abs(total - 1.0) < 1e-4, \
            f"Size fractions sum to {total:.6f}, expected ~1.0"

    def test_size_fractions_all_positive(self):
        """All size fractions must be positive."""
        out = run_scenario(SCENARIOS[0])
        for i in range(1, 6):
            key = f'size_frac_{i}'
            val = out.get(key, 0)
            assert val > 0, f"{key} must be > 0, got {val}"

    def test_size_fractions_consistent_across_scenarios(self):
        """Size fractions should be identical across scenarios."""
        out1 = run_scenario(SCENARIOS[0])
        out2 = run_scenario(SCENARIOS[1])
        for i in range(1, 6):
            key = f'size_frac_{i}'
            v1 = out1.get(key, 0)
            v2 = out2.get(key, 0)
            if abs(v1) > 1e-15:
                assert abs(v1 - v2) / abs(v1) < 1e-6, \
                    f"{key} differs between scenarios: {v1} vs {v2}"


class TestCoupledPipeline:
    """Verify the compute_cell_emission coupled pipeline."""

    @classmethod
    def setup_class(cls):
        build_code()

    @pytest.mark.parametrize(
        "scenario", SCENARIOS,
        ids=[s["name"] for s in SCENARIOS]
    )
    def test_bin_emissions(self, scenario):
        """Per-bin emissions must match reference pipeline values."""
        out = run_scenario(scenario)
        ref_bins, _ = compute_bin_emission_reference(scenario)
        errors = check_values(out, ref_bins, scenario['name'])
        assert not errors, (
            f"Scenario '{scenario['name']}' bin emission errors:\n"
            + "\n".join(errors)
        )

    @pytest.mark.parametrize(
        "scenario", [s for s in SCENARIOS if not s["bedrock"]],
        ids=[s["name"] for s in SCENARIOS if not s["bedrock"]]
    )
    def test_bin_emissions_sum_to_total(self, scenario):
        """Sum of bin emissions should equal total K14 flux."""
        out = run_scenario(scenario)
        _, F_total = compute_bin_emission_reference(scenario)
        if F_total > 0:
            bin_sum = sum(out.get(f'bin_emission_{i}', 0) for i in range(1, 6))
            rel_err = abs(bin_sum - F_total) / F_total
            assert rel_err < 2e-3, (
                f"Bin emission sum {bin_sum:.6e} != total flux {F_total:.6e}"
                f" (rel_err={rel_err:.2e})"
            )

    @pytest.mark.parametrize(
        "scenario", [s for s in SCENARIOS if not s["bedrock"]],
        ids=[s["name"] for s in SCENARIOS if not s["bedrock"]]
    )
    def test_all_bins_nonzero(self, scenario):
        """Non-bedrock emitting scenarios must have nonzero per-bin flux."""
        out = run_scenario(scenario)
        _, F_total = compute_bin_emission_reference(scenario)
        if F_total > 0:
            for i in range(1, 6):
                key = f'bin_emission_{i}'
                assert out.get(key, 0) > 0, \
                    f"{key} must be > 0 for emitting scenario {scenario['name']}"

    def test_bedrock_zero_bins(self):
        """Bedrock scenario must have zero per-bin emissions."""
        bedrock = [s for s in SCENARIOS if s["bedrock"]][0]
        out = run_scenario(bedrock)
        for i in range(1, 6):
            key = f'bin_emission_{i}'
            assert abs(out.get(key, 1.0)) < 1e-10, \
                f"{key} must be 0 for bedrock"

    def test_bin_emission_proportional_to_size_fraction(self):
        """Bin emissions should be proportional to size fractions."""
        out = run_scenario(SCENARIOS[0])
        fracs = [out.get(f'size_frac_{i}', 0) for i in range(1, 6)]
        emissions = [out.get(f'bin_emission_{i}', 0) for i in range(1, 6)]

        # All ratios emission/fraction should be the same (= total flux)
        ratios = []
        for f, e in zip(fracs, emissions):
            if f > 1e-15 and e > 1e-15:
                ratios.append(e / f)

        if len(ratios) >= 2:
            mean_ratio = sum(ratios) / len(ratios)
            for r in ratios:
                assert abs(r - mean_ratio) / mean_ratio < 1e-3, \
                    "Bin emissions not proportional to size fractions"
