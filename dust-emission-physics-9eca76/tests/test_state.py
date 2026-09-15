"""
Tests for FENGSHA and K14 windblown dust emission physics modules.

Verifies that all intermediate and final values match the correct
published parameterizations cited in the Fortran modules.

"""

import subprocess
import math
import pytest

# ---- Shared physical constants (must match Fortran modules) ----
GRAV = 9.81
VON_KARMAN = 0.4
RHO_PARTICLE = 2650.0
RHO_WATER = 1000.0
RHO_BULK_LS = 1000.0
A_N = 0.0123
GAMMA_COH = 1.65e-4
WHITE_C = 1.0

DP_SIZES = [690.0e-6, 210.0e-6, 125.0e-6, 2.0e-6]
EROPOT = [0.12, 0.12, 1.00, 0.08]

SIG_V = 1.45
M_V = 0.16
BETA_V = 202.0
SIG_S = 1.0
M_S = 0.5
BETA_S = 90.0

LAMBDA_S_TABLE = [0.03, 0.04, 0.0001, 0.15]
H_S_TABLE = [0.02, 0.02, 0.02, 0.02]
H_V_TABLE = [0.10, 0.12, 0.10, 0.50]

P_PLASTIC = [5000.0, 10000.0, 10000.0, 30000.0]
C_ALPHA_LS = [0.001, 0.0006, 0.0006, 0.0002]
F_FINE = [0.06, 0.18, 0.32, 0.72]
C_BETA_LS = [2.09, 2.09, 2.09, 2.09]

# ---- K14-specific constants ----
K14_RHO_A0 = 1.225
K14_U_ST0 = 0.16
K14_C_D0 = 4.4e-5
K14_C_E = 2.0
K14_C_A = 2.7
K14_DC_SOIL = [500.0e-6, 210.0e-6, 125.0e-6, 50.0e-6]
K14_Z0S_TABLE = [3.3e-5, 5.0e-5, 5.0e-5, 1.0e-4]


# ---- Shared reference implementations ----

def ref_threshold_fric_vel(dp, rho_a):
    """Shao and Lu (2000), Eq. 2 of Foroutan (2017) -- includes cohesion."""
    return math.sqrt(A_N * (RHO_PARTICLE * GRAV * dp / rho_a
                            + GAMMA_COH / (rho_a * dp)))


def ref_moisture_factor(w_grav_pct, clay_pct):
    """Fecan et al. (1999), Eqs. 3-4 of Foroutan (2017)."""
    w_prime = 0.0014 * clay_pct ** 2 + 0.17 * clay_pct
    if w_grav_pct <= w_prime:
        return 1.0
    else:
        return math.sqrt(1.0 + 1.21 * (w_grav_pct - w_prime) ** 0.68)


def ref_veg_roughness_density(veg_frac):
    """Eq. 6 of Foroutan (2017), Shao et al. (1996)."""
    vf = max(min(veg_frac, 0.95), 0.005)
    return -0.35 * math.log(1.0 - vf)


def ref_surface_roughness(lambda_total, h_eff):
    """Eq. 8 of Foroutan (2017)."""
    if lambda_total < 0.2:
        return 0.96 * lambda_total ** 1.07 * h_eff
    else:
        return 0.083 * lambda_total ** (-0.46) * h_eff


def ref_vol_to_grav(w_vol, sand_frac):
    """Zender volumetric-to-gravimetric moisture conversion."""
    return w_vol * RHO_WATER / (RHO_PARTICLE * (1.0 - (0.489 - 0.126 * sand_frac)))


def ref_compute_roughness_and_ustar(wind_10m, veg_frac, land_type):
    """Compute surface roughness and friction velocity (shared physics)."""
    lt = max(0, min(land_type - 1, 3))
    lambda_v = ref_veg_roughness_density(veg_frac)
    lambda_s = LAMBDA_S_TABLE[lt]
    lambda_total = lambda_v + lambda_s
    h_eff = ((H_V_TABLE[lt] * lambda_v + H_S_TABLE[lt] * lambda_s)
             / lambda_total)
    z0 = ref_surface_roughness(lambda_total, h_eff)
    z0 = max(z0, 1e-6)
    ustar = VON_KARMAN * wind_10m / math.log(10.0 / z0)
    return z0, ustar, lambda_v, lambda_s


# ---- FENGSHA-specific reference implementations ----

def ref_drag_partition(lambda_v, lambda_s_val, veg_frac):
    """Eq. 5 of Foroutan (2017) -- double drag partitioning."""
    veg_free = max(1.0 - veg_frac, 0.01)
    fr_sq = ((1.0 - SIG_V * M_V * lambda_v)
             * (1.0 + BETA_V * M_V * lambda_v)
             * (1.0 - SIG_S * M_S * lambda_s_val / veg_free)
             * (1.0 + BETA_S * M_S * lambda_s_val / veg_free))
    if fr_sq > 1.0:
        return math.sqrt(fr_sq)
    else:
        return 10.0


def ref_horiz_flux(ustar, ut, rho_a):
    """White (1979), Eq. 10 of Foroutan (2017)."""
    if ustar > ut:
        return (WHITE_C * (rho_a / GRAV) * ustar ** 3
                * (1.0 - ut / ustar) * (1.0 + ut / ustar) ** 2)
    else:
        return 0.0


def ref_vert_horiz_ratio(soil_type, ustar):
    """Lu and Shao (1999), Eq. 13 of Foroutan (2017)."""
    st = max(0, min(soil_type - 1, 3))
    ca = C_ALPHA_LS[st]
    ff = F_FINE[st]
    pp = P_PLASTIC[st]
    cb = C_BETA_LS[st]
    return (ca * GRAV * ff * (RHO_BULK_LS / 2.0) / pp
            * (0.24 + cb * ustar * math.sqrt(RHO_PARTICLE / pp)))


def compute_fengsha_reference(wind_10m, rho_air, soil_moist_vol,
                              clay_f, silt_f, sand_f, veg_frac,
                              land_type, soil_type):
    """Compute all FENGSHA reference values using correct formulas."""
    soil_fracs = [sand_f / 2.0, sand_f / 2.0, silt_f, clay_f]

    z0, ustar, lambda_v, lambda_s = \
        ref_compute_roughness_and_ustar(wind_10m, veg_frac, land_type)

    w_grav = ref_vol_to_grav(soil_moist_vol, sand_f)
    w_grav_pct = w_grav * 100.0
    clay_pct = clay_f * 100.0

    fm = ref_moisture_factor(w_grav_pct, clay_pct)
    fr = ref_drag_partition(lambda_v, lambda_s, veg_frac)

    uts0 = ref_threshold_fric_vel(75.0e-6, rho_air)
    sep = clay_f * 0.08 + silt_f * 1.00 + sand_f * 0.12

    hflux_total = 0.0
    for n in range(4):
        ut = ref_threshold_fric_vel(DP_SIZES[n], rho_air) * fm * fr
        hflux_total += ref_horiz_flux(ustar, ut, rho_air) * soil_fracs[n] * sep

    alpha = ref_vert_horiz_ratio(soil_type, ustar)
    vflux = alpha * hflux_total
    veg_free = max(1.0 - veg_frac, 0.0)
    emission = veg_free * vflux

    return {
        'u_star': ustar, 'u_ts0': uts0, 'f_moist': fm, 'f_rough': fr,
        'z0': z0, 'sep': sep, 'h_flux': hflux_total, 'alpha': alpha,
        'v_flux': vflux, 'emission': emission,
    }


# ---- K14-specific reference implementations ----

def ref_k14_clay_silt_param(clay_f, silt_f):
    """Ito and Kok (2017), Eq. 4."""
    return math.exp(0.831 * (clay_f + silt_f) - 0.0203)


def ref_k14_roughness_partition(z0, z0s):
    """MacKinnon et al. (2004)."""
    R = 1.0 - math.log(z0 / z0s) / math.log(0.7 * (122.55 / z0s) ** 0.8)
    return max(0.001, min(R, 1.0))


def ref_k14_emission_coeff(u_t, rho_air):
    """Kok et al. (2014), Eq. 5."""
    u_st = u_t * math.sqrt(rho_air / K14_RHO_A0)
    return K14_C_D0 * math.exp(-K14_C_E * (u_st / K14_U_ST0 - 1.0))


def ref_k14_vertical_flux(u, u_t, rho_air, f_erod, k_gamma, C_d):
    """Kok et al. (2014), Eq. 1."""
    if u <= u_t:
        return 0.0
    u_st = u_t * math.sqrt(rho_air / K14_RHO_A0)
    f_ust = u_st / K14_U_ST0
    return (C_d * f_erod * k_gamma * (rho_air / u_st)
            * (u ** 2 - u_t ** 2)
            * (u / u_t) ** (K14_C_A * f_ust))


def compute_k14_reference(wind_10m, rho_air, soil_moist_vol,
                          clay_f, silt_f, sand_f, veg_frac,
                          land_type, soil_type):
    """Compute all K14 reference values using correct formulas."""
    st = max(0, min(soil_type - 1, 3))

    z0, ustar, _, _ = \
        ref_compute_roughness_and_ustar(wind_10m, veg_frac, land_type)

    w_grav = ref_vol_to_grav(soil_moist_vol, sand_f)
    w_grav_pct = w_grav * 100.0
    clay_pct = clay_f * 100.0
    fm = ref_moisture_factor(w_grav_pct, clay_pct)

    k_gamma = ref_k14_clay_silt_param(clay_f, silt_f)
    z0s = K14_Z0S_TABLE[st]
    R = ref_k14_roughness_partition(z0, z0s)
    u_aeolian = R * ustar

    dp_rep = K14_DC_SOIL[st]
    u_t0 = ref_threshold_fric_vel(dp_rep, rho_air)
    u_t = u_t0 * fm

    C_d = ref_k14_emission_coeff(u_t, rho_air)
    f_erod = clay_f * 0.08 + silt_f * 1.00 + sand_f * 0.12
    v_flux = ref_k14_vertical_flux(u_aeolian, u_t, rho_air,
                                   f_erod, k_gamma, C_d)

    veg_free = max(1.0 - veg_frac, 0.0)
    emission = veg_free * v_flux
    uts0 = ref_threshold_fric_vel(75.0e-6, rho_air)

    return {
        'u_star': ustar, 'u_ts0': uts0, 'f_moist': fm, 'f_rough': R,
        'z0': z0, 'sep': k_gamma, 'h_flux': u_aeolian, 'alpha': C_d,
        'v_flux': v_flux, 'emission': emission,
    }


# ---- Test scenarios ----
FENGSHA_SCENARIOS = [
    # wind  rho   moist  clay  silt  sand  veg   land soil
    (15.0, 1.225, 0.005, 0.03, 0.05, 0.92, 0.02, 3, 1),  # dry barren desert
    (10.0, 1.150, 0.030, 0.18, 0.39, 0.43, 0.20, 1, 2),  # semi-arid shrubland
    (8.0,  1.200, 0.150, 0.42, 0.47, 0.11, 0.10, 1, 4),  # moist clay-rich
    (12.0, 1.180, 0.020, 0.10, 0.32, 0.58, 0.40, 4, 2),  # vegetated cropland
    (3.0,  1.250, 0.005, 0.05, 0.85, 0.10, 0.05, 3, 2),  # below threshold
    (20.0, 1.100, 0.002, 0.05, 0.10, 0.85, 0.01, 3, 1),  # strong wind barren
    (18.0, 1.150, 0.008, 0.15, 0.25, 0.60, 0.15, 2, 2),  # moderate shrubgrass
    (11.0, 1.200, 0.080, 0.15, 0.45, 0.40, 0.12, 1, 3),  # moist moderate veg
]

K14_SCENARIOS = [
    (15.0, 1.225, 0.005, 0.03, 0.05, 0.92, 0.02, 3, 1),  # dry barren sand
    (12.0, 1.150, 0.020, 0.18, 0.39, 0.43, 0.20, 1, 2),  # semi-arid loam
    (8.0,  1.200, 0.100, 0.30, 0.50, 0.20, 0.10, 1, 3),  # moist sandy clay loam
    (20.0, 1.100, 0.002, 0.05, 0.10, 0.85, 0.01, 3, 1),  # strong wind barren sand
    (3.0,  1.250, 0.005, 0.05, 0.85, 0.10, 0.05, 3, 2),  # below threshold
    (18.0, 1.150, 0.008, 0.15, 0.25, 0.60, 0.15, 2, 2),  # moderate shrubgrass loam
]


# ---- Helpers ----

def build_program():
    """Build the Fortran program."""
    subprocess.run(['make', '-C', '/app', 'clean'],
                   capture_output=True, text=True)
    result = subprocess.run(['make', '-C', '/app'],
                          capture_output=True, text=True)
    assert result.returncode == 0, \
        f"Build failed with return code {result.returncode}:\n{result.stderr}"


def run_program(scenario_file):
    """Run the program with a scenario file and return parsed output."""
    path = f'/app/scenarios/{scenario_file}'
    with open(path, 'r') as f:
        result = subprocess.run(
            ['/app/dust_emission'],
            stdin=f,
            capture_output=True,
            text=True,
            timeout=30
        )
    assert result.returncode == 0, \
        f"Program failed on {scenario_file} (rc={result.returncode}):\n{result.stderr}"

    lines = result.stdout.strip().split('\n')
    assert len(lines) >= 2, \
        f"Expected header + data lines, got {len(lines)} lines"

    data = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 11:
            continue
        values = [float(x) for x in parts[1:]]
        data.append({
            'cell_id': int(parts[0]),
            'u_star': values[0], 'u_ts0': values[1],
            'f_moist': values[2], 'f_rough': values[3],
            'z0': values[4], 'sep': values[5],
            'h_flux': values[6], 'alpha': values[7],
            'v_flux': values[8], 'emission': values[9],
        })
    return data


def rel_err(actual, expected):
    """Compute relative error, handling near-zero expected values."""
    if abs(expected) < 1e-30:
        return abs(actual)
    return abs(actual - expected) / abs(expected)


# ---- Fixtures ----

@pytest.fixture(scope='module')
def built():
    build_program()
    return True


@pytest.fixture(scope='module')
def fengsha_results(built):
    data = run_program('test_fengsha.txt')
    assert len(data) == len(FENGSHA_SCENARIOS), \
        f"Expected {len(FENGSHA_SCENARIOS)} FENGSHA cells, got {len(data)}"
    return data


@pytest.fixture(scope='module')
def fengsha_reference():
    return [compute_fengsha_reference(*s) for s in FENGSHA_SCENARIOS]


@pytest.fixture(scope='module')
def k14_results(built):
    data = run_program('test_k14.txt')
    assert len(data) == len(K14_SCENARIOS), \
        f"Expected {len(K14_SCENARIOS)} K14 cells, got {len(data)}"
    return data


@pytest.fixture(scope='module')
def k14_reference():
    return [compute_k14_reference(*s) for s in K14_SCENARIOS]


# =====================================================================
#                        FENGSHA TESTS
# =====================================================================

class TestFengshaThresholdVelocity:
    """Verify Shao-Lu (2000) threshold friction velocity."""

    def test_uts0_75um_all_cells(self, fengsha_results, fengsha_reference):
        """u*_t0 for 75um particle must include cohesion term."""
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            assert rel_err(fr['u_ts0'], ref['u_ts0']) < 0.01, \
                (f"FENGSHA cell {i+1}: u_ts0 = {fr['u_ts0']:.8e}, "
                 f"expected {ref['u_ts0']:.8e}")


class TestFengshaMoistureCorrection:
    """Verify Fecan (1999) soil moisture correction."""

    def test_moisture_factor_all_cells(self, fengsha_results, fengsha_reference):
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            assert rel_err(fr['f_moist'], ref['f_moist']) < 0.01, \
                (f"FENGSHA cell {i+1}: f_moist = {fr['f_moist']:.8e}, "
                 f"expected {ref['f_moist']:.8e}")

    def test_moisture_correction_activates(self, fengsha_reference):
        """At least one cell should have f_moist > 1."""
        has_active = any(ref['f_moist'] > 1.01 for ref in fengsha_reference)
        assert has_active, \
            "No FENGSHA cell exercises the active moisture correction branch"


class TestFengshaDragPartition:
    """Verify double drag partitioning correction."""

    def test_drag_partition_all_cells(self, fengsha_results, fengsha_reference):
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            assert rel_err(fr['f_rough'], ref['f_rough']) < 0.01, \
                (f"FENGSHA cell {i+1}: f_rough = {fr['f_rough']:.8e}, "
                 f"expected {ref['f_rough']:.8e}")


class TestFengshaSurfaceRoughness:
    """Verify Foroutan (2017) surface roughness and friction velocity."""

    def test_z0_all_cells(self, fengsha_results, fengsha_reference):
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            assert rel_err(fr['z0'], ref['z0']) < 0.01, \
                (f"FENGSHA cell {i+1}: z0 = {fr['z0']:.8e}, "
                 f"expected {ref['z0']:.8e}")

    def test_friction_velocity_all_cells(self, fengsha_results, fengsha_reference):
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            assert rel_err(fr['u_star'], ref['u_star']) < 0.01, \
                (f"FENGSHA cell {i+1}: u_star = {fr['u_star']:.8e}, "
                 f"expected {ref['u_star']:.8e}")


class TestFengshaHorizontalFlux:
    """Verify White (1979) horizontal saltation flux."""

    def test_total_horizontal_flux(self, fengsha_results, fengsha_reference):
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            if abs(ref['h_flux']) < 1e-30:
                assert abs(fr['h_flux']) < 1e-15, \
                    (f"FENGSHA cell {i+1}: h_flux should be ~0, "
                     f"got {fr['h_flux']:.8e}")
            else:
                assert rel_err(fr['h_flux'], ref['h_flux']) < 0.02, \
                    (f"FENGSHA cell {i+1}: h_flux = {fr['h_flux']:.8e}, "
                     f"expected {ref['h_flux']:.8e}")


class TestFengshaVerticalFluxRatio:
    """Verify Lu-Shao (1999) vertical-to-horizontal flux ratio."""

    def test_alpha_all_cells(self, fengsha_results, fengsha_reference):
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            assert rel_err(fr['alpha'], ref['alpha']) < 0.01, \
                (f"FENGSHA cell {i+1}: alpha = {fr['alpha']:.8e}, "
                 f"expected {ref['alpha']:.8e}")


class TestFengshaFinalEmission:
    """Verify final FENGSHA dust emission values."""

    def test_emission_flux_all_cells(self, fengsha_results, fengsha_reference):
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            if abs(ref['emission']) < 1e-30:
                assert abs(fr['emission']) < 1e-15, \
                    (f"FENGSHA cell {i+1}: emission should be ~0, "
                     f"got {fr['emission']:.8e}")
            else:
                assert rel_err(fr['emission'], ref['emission']) < 0.02, \
                    (f"FENGSHA cell {i+1}: emission = {fr['emission']:.8e}, "
                     f"expected {ref['emission']:.8e}")

    def test_vertical_flux_all_cells(self, fengsha_results, fengsha_reference):
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            if abs(ref['v_flux']) < 1e-30:
                assert abs(fr['v_flux']) < 1e-15
            else:
                assert rel_err(fr['v_flux'], ref['v_flux']) < 0.02, \
                    (f"FENGSHA cell {i+1}: v_flux = {fr['v_flux']:.8e}, "
                     f"expected {ref['v_flux']:.8e}")

    def test_zero_emission_below_threshold(self, fengsha_results,
                                            fengsha_reference):
        """Cell 5 (3 m/s wind) should have zero emission."""
        ref = fengsha_reference[4]
        fr = fengsha_results[4]
        assert abs(ref['h_flux']) < 1e-20, \
            "Reference shows cell 5 should have zero horizontal flux"
        assert abs(fr['emission']) < 1e-10, \
            (f"FENGSHA cell 5: emission should be ~0 (below threshold), "
             f"got {fr['emission']:.8e}")

    def test_nonzero_emission_strong_wind(self, fengsha_results,
                                          fengsha_reference):
        """Cell 6 (20 m/s, dry barren) should have significant emission."""
        ref = fengsha_reference[5]
        fr = fengsha_results[5]
        assert ref['emission'] > 1e-10, \
            "Reference shows cell 6 should have significant emission"
        assert fr['emission'] > 1e-10, \
            (f"FENGSHA cell 6: emission should be significant, "
             f"got {fr['emission']:.8e}")

    def test_sep_consistency(self, fengsha_results, fengsha_reference):
        """Soil erodibility potential should match direct computation."""
        for i, (fr, ref) in enumerate(zip(fengsha_results, fengsha_reference)):
            assert rel_err(fr['sep'], ref['sep']) < 0.001, \
                (f"FENGSHA cell {i+1}: sep = {fr['sep']:.8e}, "
                 f"expected {ref['sep']:.8e}")


# =====================================================================
#                          K14 TESTS
# =====================================================================

class TestK14Runs:
    """Verify K14 scheme produces output."""

    def test_k14_produces_data(self, k14_results):
        assert len(k14_results) == len(K14_SCENARIOS), \
            f"Expected {len(K14_SCENARIOS)} K14 cells, got {len(k14_results)}"


class TestK14SharedPhysics:
    """Verify K14 correctly uses shared physics (roughness, u_star, moisture)."""

    def test_k14_ustar_all_cells(self, k14_results, k14_reference):
        """K14 uses same log-profile friction velocity as FENGSHA."""
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            assert rel_err(fr['u_star'], ref['u_star']) < 0.01, \
                (f"K14 cell {i+1}: u_star = {fr['u_star']:.8e}, "
                 f"expected {ref['u_star']:.8e}")

    def test_k14_z0_all_cells(self, k14_results, k14_reference):
        """K14 uses same surface roughness as FENGSHA."""
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            assert rel_err(fr['z0'], ref['z0']) < 0.01, \
                (f"K14 cell {i+1}: z0 = {fr['z0']:.8e}, "
                 f"expected {ref['z0']:.8e}")

    def test_k14_uts0_all_cells(self, k14_results, k14_reference):
        """K14 uses same Shao-Lu threshold (with cohesion)."""
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            assert rel_err(fr['u_ts0'], ref['u_ts0']) < 0.01, \
                (f"K14 cell {i+1}: u_ts0 = {fr['u_ts0']:.8e}, "
                 f"expected {ref['u_ts0']:.8e}")

    def test_k14_moisture_all_cells(self, k14_results, k14_reference):
        """K14 uses same Fecan moisture correction."""
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            assert rel_err(fr['f_moist'], ref['f_moist']) < 0.01, \
                (f"K14 cell {i+1}: f_moist = {fr['f_moist']:.8e}, "
                 f"expected {ref['f_moist']:.8e}")


class TestK14ClaySiltParam:
    """Verify Ito-Kok (2017) clay-silt erodibility parameter."""

    def test_k14_kgamma_all_cells(self, k14_results, k14_reference):
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            assert rel_err(fr['sep'], ref['sep']) < 0.01, \
                (f"K14 cell {i+1}: k_gamma(sep) = {fr['sep']:.8e}, "
                 f"expected {ref['sep']:.8e}")

    def test_k14_kgamma_varies_with_soil(self, k14_reference):
        """k_gamma should differ between soil compositions."""
        kgammas = [ref['sep'] for ref in k14_reference]
        assert max(kgammas) / min(kgammas) > 1.5, \
            "k_gamma shows insufficient variation across soil types"


class TestK14RoughnessPartition:
    """Verify MacKinnon (2004) roughness drag partition."""

    def test_k14_R_all_cells(self, k14_results, k14_reference):
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            assert rel_err(fr['f_rough'], ref['f_rough']) < 0.01, \
                (f"K14 cell {i+1}: R(f_rough) = {fr['f_rough']:.8e}, "
                 f"expected {ref['f_rough']:.8e}")

    def test_k14_R_in_range(self, k14_results):
        """MacKinnon R should be in (0, 1]."""
        for i, fr in enumerate(k14_results):
            assert 0.0 < fr['f_rough'] <= 1.0, \
                f"K14 cell {i+1}: R = {fr['f_rough']:.8e} out of range (0,1]"


class TestK14AeolianVelocity:
    """Verify aeolian friction velocity u = R * u_star."""

    def test_k14_u_aeolian_all_cells(self, k14_results, k14_reference):
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            assert rel_err(fr['h_flux'], ref['h_flux']) < 0.01, \
                (f"K14 cell {i+1}: u_aeolian(h_flux) = {fr['h_flux']:.8e}, "
                 f"expected {ref['h_flux']:.8e}")

    def test_k14_u_aeolian_less_than_ustar(self, k14_results):
        """Aeolian velocity u = R * u_star should be <= u_star."""
        for i, fr in enumerate(k14_results):
            assert fr['h_flux'] <= fr['u_star'] * 1.01, \
                (f"K14 cell {i+1}: u_aeolian ({fr['h_flux']:.8e}) > "
                 f"u_star ({fr['u_star']:.8e})")


class TestK14EmissionCoeff:
    """Verify Kok (2014) emission coefficient C_d."""

    def test_k14_Cd_all_cells(self, k14_results, k14_reference):
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            assert rel_err(fr['alpha'], ref['alpha']) < 0.01, \
                (f"K14 cell {i+1}: C_d(alpha) = {fr['alpha']:.8e}, "
                 f"expected {ref['alpha']:.8e}")

    def test_k14_Cd_positive(self, k14_results):
        """C_d should always be positive."""
        for i, fr in enumerate(k14_results):
            assert fr['alpha'] > 0, \
                f"K14 cell {i+1}: C_d should be positive, got {fr['alpha']:.8e}"


class TestK14VerticalFlux:
    """Verify K14 vertical dust emission flux."""

    def test_k14_vflux_all_cells(self, k14_results, k14_reference):
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            if abs(ref['v_flux']) < 1e-30:
                assert abs(fr['v_flux']) < 1e-15, \
                    (f"K14 cell {i+1}: v_flux should be ~0, "
                     f"got {fr['v_flux']:.8e}")
            else:
                assert rel_err(fr['v_flux'], ref['v_flux']) < 0.02, \
                    (f"K14 cell {i+1}: v_flux = {fr['v_flux']:.8e}, "
                     f"expected {ref['v_flux']:.8e}")

    def test_k14_emission_all_cells(self, k14_results, k14_reference):
        for i, (fr, ref) in enumerate(zip(k14_results, k14_reference)):
            if abs(ref['emission']) < 1e-30:
                assert abs(fr['emission']) < 1e-15, \
                    (f"K14 cell {i+1}: emission should be ~0, "
                     f"got {fr['emission']:.8e}")
            else:
                assert rel_err(fr['emission'], ref['emission']) < 0.02, \
                    (f"K14 cell {i+1}: emission = {fr['emission']:.8e}, "
                     f"expected {ref['emission']:.8e}")

    def test_k14_zero_below_threshold(self, k14_results, k14_reference):
        """K14 cell 5 (3 m/s wind) should have zero emission."""
        ref = k14_reference[4]
        fr = k14_results[4]
        assert abs(ref['v_flux']) < 1e-20, \
            "K14 reference shows cell 5 should have zero flux"
        assert abs(fr['emission']) < 1e-10, \
            (f"K14 cell 5: emission should be ~0 (below threshold), "
             f"got {fr['emission']:.8e}")

    def test_k14_nonzero_strong_wind(self, k14_results, k14_reference):
        """K14 cell 4 (20 m/s, dry barren) should have significant emission."""
        ref = k14_reference[3]
        fr = k14_results[3]
        assert ref['emission'] > 1e-10, \
            "K14 reference shows cell 4 should have significant emission"
        assert fr['emission'] > 1e-10, \
            (f"K14 cell 4: emission should be significant, "
             f"got {fr['emission']:.8e}")


class TestK14CrossSchemeConsistency:
    """Verify cross-scheme physical consistency."""

    def test_shared_roughness_produces_same_z0(self, fengsha_results,
                                                k14_results):
        """Same input conditions should produce same z0 in both schemes."""
        # FENGSHA cell 1 and K14 cell 1 share same inputs
        f_z0 = fengsha_results[0]['z0']
        k_z0 = k14_results[0]['z0']
        assert rel_err(f_z0, k_z0) < 0.001, \
            (f"z0 mismatch: FENGSHA={f_z0:.8e}, K14={k_z0:.8e}")

    def test_shared_ustar_produces_same_value(self, fengsha_results,
                                               k14_results):
        """Same input conditions should produce same u_star in both schemes."""
        f_ustar = fengsha_results[0]['u_star']
        k_ustar = k14_results[0]['u_star']
        assert rel_err(f_ustar, k_ustar) < 0.001, \
            (f"u_star mismatch: FENGSHA={f_ustar:.8e}, K14={k_ustar:.8e}")

    def test_shared_threshold_produces_same_uts0(self, fengsha_results,
                                                  k14_results):
        """Same rho_air should produce same u_ts0 in both schemes."""
        f_uts0 = fengsha_results[0]['u_ts0']
        k_uts0 = k14_results[0]['u_ts0']
        assert rel_err(f_uts0, k_uts0) < 0.001, \
            (f"u_ts0 mismatch: FENGSHA={f_uts0:.8e}, K14={k_uts0:.8e}")
