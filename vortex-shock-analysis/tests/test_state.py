"""
Tests for compressible flow field reconstruction task.

All reference values are computed independently from physics first principles,
not imported from the provided ci2_init module.

"""
import json
import math
import os
import pytest

# ─── Physical constants ───
GAMMA = 1.4
R_GAS = 1.0
MS = 1.5
RHO_U = 1.0
U_U = 1.5 * math.sqrt(GAMMA)
P_U = 1.0
T_U = 1.0

# ─── Rankine-Hugoniot downstream state ───
MS2 = MS ** 2
RHO_D = RHO_U * (GAMMA + 1) * MS2 / (2 + (GAMMA - 1) * MS2)
U_D = U_U * (2 + (GAMMA - 1) * MS2) / ((GAMMA + 1) * MS2)
P_D = P_U * (1 + 2 * GAMMA / (GAMMA + 1) * (MS2 - 1))
T_D = P_D / (RHO_D * R_GAS)
A_D = math.sqrt(GAMMA * R_GAS * T_D)
M_D_REF = U_D / A_D

# ─── Total enthalpy ───
CP = GAMMA * R_GAS / (GAMMA - 1)
H_U = CP * T_U + 0.5 * U_U ** 2
H_D = CP * T_D + 0.5 * U_D ** 2

# ─── Entropy ───
S_U = P_U / RHO_U ** GAMMA
S_D = P_D / RHO_D ** GAMMA

# ─── Vortex parameters ───
XC, YC = 0.25, 0.5
A_V, B_V = 0.075, 0.175
MV = 0.9
V_M = MV * math.sqrt(GAMMA)


def _compute_vortex_center_state():
    """Reference computation for thermodynamic state at vortex center (r=0)."""
    coeff = V_M * A_V / (A_V ** 2 - B_V ** 2)
    radial_term_a = (
        -2 * B_V ** 2 * math.log(B_V)
        - 0.5 * A_V ** 2
        + 2 * B_V ** 2 * math.log(A_V)
        + 0.5 * B_V ** 4 / A_V ** 2
    )
    t_a = T_U - (GAMMA - 1) * coeff ** 2 * radial_term_a / (R_GAS * GAMMA)
    t_center = t_a - (GAMMA - 1) * V_M ** 2 * 0.5 / (R_GAS * GAMMA)
    p_center = P_U * (t_center / T_U) ** (GAMMA / (GAMMA - 1))
    rho_center = p_center / (R_GAS * t_center)
    return p_center, t_center, rho_center


P_VC, T_VC, RHO_VC = _compute_vortex_center_state()

# ─── Analytical peak vorticity (solid-body rotation: omega = 2*v_m/a) ───
PEAK_VORT = 2 * V_M / A_V

# ─── Analytical circulation at r=0.12 ───
R_CIRC = 0.12
CIRC_REF = (
    2 * math.pi * V_M * A_V * (R_CIRC ** 2 - B_V ** 2) / (A_V ** 2 - B_V ** 2)
)


@pytest.fixture
def results():
    """Load the agent's analysis results."""
    path = "/app/results/analysis.json"
    assert os.path.exists(path), f"Output file {path} not found"
    with open(path) as f:
        data = json.load(f)
    return data


# ═══════════════════════════════════════════════════════════
# Mesh quality (verifies Gmsh was used correctly)
# ═══════════════════════════════════════════════════════════
class TestMeshQuality:
    def test_mesh_file_exists(self):
        assert os.path.exists("/app/results/mesh.msh"), "Gmsh mesh file not found"

    def test_mesh_file_format(self):
        with open("/app/results/mesh.msh") as f:
            first_line = f.readline().strip()
        assert first_line == "$MeshFormat", "Not a valid Gmsh MSH file"

    def test_num_nodes(self, results):
        assert results["mesh_quality"]["num_nodes"] >= 160000

    def test_num_elements(self, results):
        assert results["mesh_quality"]["num_elements"] > 0

    def test_min_quality_range(self, results):
        q = results["mesh_quality"]["min_quality"]
        assert 0 < q <= 1.0, f"Element quality {q} outside valid range (0,1]"


# ═══════════════════════════════════════════════════════════
# Shock conditions (analytical — tight tolerance)
# ═══════════════════════════════════════════════════════════
class TestShockConditions:
    def test_rho_downstream(self, results):
        assert results["shock_conditions"]["rho_d"] == pytest.approx(RHO_D, rel=1e-6)

    def test_u_downstream(self, results):
        assert results["shock_conditions"]["u_d"] == pytest.approx(U_D, rel=1e-6)

    def test_p_downstream(self, results):
        assert results["shock_conditions"]["p_d"] == pytest.approx(P_D, rel=1e-6)

    def test_T_downstream(self, results):
        assert results["shock_conditions"]["T_d"] == pytest.approx(T_D, rel=1e-6)

    def test_M_downstream(self, results):
        assert results["shock_conditions"]["M_d"] == pytest.approx(M_D_REF, rel=1e-6)

    def test_M_downstream_subsonic(self, results):
        """Post-shock Mach number must be subsonic for Ms=1.5."""
        assert results["shock_conditions"]["M_d"] < 1.0


# ═══════════════════════════════════════════════════════════
# Total enthalpy conservation across the shock
# ═══════════════════════════════════════════════════════════
class TestConservation:
    def test_H_upstream_value(self, results):
        assert results["conservation"]["H_upstream"] == pytest.approx(H_U, rel=1e-6)

    def test_H_downstream_value(self, results):
        assert results["conservation"]["H_downstream"] == pytest.approx(H_D, rel=1e-6)

    def test_enthalpy_conserved(self, results):
        """Total enthalpy must be conserved across a normal shock."""
        assert results["conservation"]["relative_error"] < 1e-8


# ═══════════════════════════════════════════════════════════
# Entropy across the shock
# ═══════════════════════════════════════════════════════════
class TestEntropy:
    def test_s_upstream(self, results):
        assert results["entropy"]["s_upstream"] == pytest.approx(S_U, rel=1e-6)

    def test_s_downstream(self, results):
        assert results["entropy"]["s_downstream"] == pytest.approx(S_D, rel=1e-6)

    def test_entropy_increases(self, results):
        """Entropy must increase across a shock (2nd law)."""
        assert results["entropy"]["entropy_ratio"] > 1.0

    def test_entropy_ratio_value(self, results):
        assert results["entropy"]["entropy_ratio"] == pytest.approx(
            S_D / S_U, rel=1e-6
        )


# ═══════════════════════════════════════════════════════════
# Vortex center properties
# ═══════════════════════════════════════════════════════════
class TestVortexProperties:
    def test_center_pressure(self, results):
        assert results["vortex_properties"]["center_pressure"] == pytest.approx(
            P_VC, rel=1e-4
        )

    def test_center_temperature(self, results):
        assert results["vortex_properties"]["center_temperature"] == pytest.approx(
            T_VC, rel=1e-4
        )

    def test_center_density(self, results):
        assert results["vortex_properties"]["center_density"] == pytest.approx(
            RHO_VC, rel=1e-4
        )

    def test_center_pressure_below_freestream(self, results):
        """Vortex creates a pressure deficit at its center."""
        assert results["vortex_properties"]["center_pressure"] < P_U

    def test_center_temperature_below_freestream(self, results):
        """Isentropic vortex has lower temperature at center."""
        assert results["vortex_properties"]["center_temperature"] < T_U

    def test_peak_vorticity(self, results):
        """Peak vorticity should match 2*v_m/a for solid-body-rotation core."""
        assert results["vortex_properties"]["peak_vorticity"] == pytest.approx(
            PEAK_VORT, rel=0.05
        )

    def test_circulation_sign(self, results):
        """Circulation must be positive (counterclockwise vortex)."""
        assert results["vortex_properties"]["circulation_r012"] > 0

    def test_circulation_value(self, results):
        assert results["vortex_properties"]["circulation_r012"] == pytest.approx(
            CIRC_REF, rel=0.02
        )


# ═══════════════════════════════════════════════════════════
# Field statistics from the grid
# ═══════════════════════════════════════════════════════════
class TestFieldStatistics:
    def test_max_mach_exceeds_freestream(self, results):
        """Vortex velocity adds to freestream, increasing local Mach number."""
        assert results["field_statistics"]["max_mach"] > MS

    def test_max_mach_in_reasonable_range(self, results):
        """Max Mach should be ~2.5 where vortex velocity adds to freestream."""
        assert 2.0 < results["field_statistics"]["max_mach"] < 3.5

    def test_min_pressure_below_freestream(self, results):
        """Vortex core has pressure well below freestream."""
        assert results["field_statistics"]["min_pressure"] < 0.5

    def test_min_pressure_positive(self, results):
        """Pressure must remain positive everywhere."""
        assert results["field_statistics"]["min_pressure"] > 0.01

    def test_min_pressure_consistent_with_center(self, results):
        """Minimum pressure should be near the vortex center pressure."""
        assert results["field_statistics"]["min_pressure"] == pytest.approx(
            results["vortex_properties"]["center_pressure"], rel=0.15
        )

    def test_max_vorticity_grid(self, results):
        """Grid-computed max vorticity should approximate analytical peak."""
        assert results["field_statistics"]["max_vorticity"] == pytest.approx(
            PEAK_VORT, rel=0.15
        )

    def test_max_vorticity_positive(self, results):
        assert results["field_statistics"]["max_vorticity"] > 0
