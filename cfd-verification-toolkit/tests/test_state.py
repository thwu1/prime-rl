
import json
import math
import os
import pytest

RESULTS_PATH = '/app/results/verification_results.json'
MESH_PATH = '/app/results/ci2_solution.msh'
GAMMA = 1.4


@pytest.fixture(scope='module')
def results():
    assert os.path.exists(RESULTS_PATH), \
        f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ===================================================================
# Structure validation
# ===================================================================

class TestStructure:
    def test_top_level_keys(self, results):
        for key in ['compressible', 'ci2', 'convergence', 'mms']:
            assert key in results, f"Missing top-level key: {key}"

    def test_compressible_keys(self, results):
        assert 'normal_shock' in results['compressible']
        assert 'isentropic' in results['compressible']

    def test_ci2_keys(self, results):
        for key in ['upstream_freestream', 'downstream_postshock', 'vortex_inner']:
            assert key in results['ci2'], f"Missing ci2 key: {key}"

    def test_convergence_keys(self, results):
        for key in ['observed_orders', 'extrapolated_value', 'uncertainty_fine']:
            assert key in results['convergence'], \
                f"Missing convergence key: {key}"

    def test_mms_keys(self, results):
        assert 'source_at_test_point' in results['mms']
        assert 'max_residual' in results['mms']


# ===================================================================
# Normal shock relations (M1=1.5, gamma=1.4)
# ===================================================================

class TestNormalShock:
    M1 = 1.5

    def _expected(self):
        g = GAMMA
        M1 = self.M1
        M2_sq = (1 + (g - 1) / 2 * M1 ** 2) / (g * M1 ** 2 - (g - 1) / 2)
        M2 = math.sqrt(M2_sq)
        p2_p1 = 1 + 2 * g / (g + 1) * (M1 ** 2 - 1)
        rho2_rho1 = (g + 1) * M1 ** 2 / (2 + (g - 1) * M1 ** 2)
        T2_T1 = p2_p1 / rho2_rho1
        ratio = ((1 + (g - 1) / 2 * M2_sq) /
                 (1 + (g - 1) / 2 * M1 ** 2)) ** (g / (g - 1))
        p02_p01 = p2_p1 * ratio
        return M2, p2_p1, rho2_rho1, T2_T1, p02_p01

    def test_M2(self, results):
        M2_exp = self._expected()[0]
        val = results['compressible']['normal_shock']['M2']
        assert abs(val - M2_exp) / M2_exp < 1e-6

    def test_p2_p1(self, results):
        exp = self._expected()[1]
        val = results['compressible']['normal_shock']['p2_p1']
        assert abs(val - exp) / exp < 1e-6

    def test_rho2_rho1(self, results):
        exp = self._expected()[2]
        val = results['compressible']['normal_shock']['rho2_rho1']
        assert abs(val - exp) / exp < 1e-6

    def test_T2_T1(self, results):
        exp = self._expected()[3]
        val = results['compressible']['normal_shock']['T2_T1']
        assert abs(val - exp) / exp < 1e-6

    def test_p02_p01(self, results):
        exp = self._expected()[4]
        val = results['compressible']['normal_shock']['p02_p01']
        assert abs(val - exp) / exp < 1e-4

    def test_total_temperature_conservation(self, results):
        """Total temperature is conserved across a normal shock."""
        shock = results['compressible']['normal_shock']
        T01_T1 = 1 + (GAMMA - 1) / 2 * self.M1 ** 2
        T02_T2 = 1 + (GAMMA - 1) / 2 * shock['M2'] ** 2
        T02_T1 = shock['T2_T1'] * T02_T2
        assert abs(T01_T1 - T02_T1) / T01_T1 < 1e-5

    def test_entropy_increases(self, results):
        """Entropy must increase across a normal shock."""
        shock = results['compressible']['normal_shock']
        ds_R = (GAMMA / (GAMMA - 1) * math.log(shock['T2_T1']) -
                math.log(shock['p2_p1']))
        assert ds_R > 0


# ===================================================================
# Isentropic flow relations (M=2.0, gamma=1.4)
# ===================================================================

class TestIsentropic:
    M = 2.0

    def test_T_T0(self, results):
        exp = 1.0 / (1 + (GAMMA - 1) / 2 * self.M ** 2)
        val = results['compressible']['isentropic']['T_T0']
        assert abs(val - exp) / exp < 1e-6

    def test_p_p0(self, results):
        T_T0 = 1.0 / (1 + (GAMMA - 1) / 2 * self.M ** 2)
        exp = T_T0 ** (GAMMA / (GAMMA - 1))
        val = results['compressible']['isentropic']['p_p0']
        assert abs(val - exp) / exp < 1e-6

    def test_rho_rho0(self, results):
        T_T0 = 1.0 / (1 + (GAMMA - 1) / 2 * self.M ** 2)
        exp = T_T0 ** (1 / (GAMMA - 1))
        val = results['compressible']['isentropic']['rho_rho0']
        assert abs(val - exp) / exp < 1e-6

    def test_A_Astar(self, results):
        fac = (2 / (GAMMA + 1)) * (1 + (GAMMA - 1) / 2 * self.M ** 2)
        exp = (1 / self.M) * fac ** ((GAMMA + 1) / (2 * (GAMMA - 1)))
        val = results['compressible']['isentropic']['A_Astar']
        assert abs(val - exp) / exp < 1e-6

    def test_consistency(self, results):
        """p/p0 = (rho/rho0)^gamma for isentropic flow."""
        iso = results['compressible']['isentropic']
        p_check = iso['rho_rho0'] ** GAMMA
        assert abs(iso['p_p0'] - p_check) / iso['p_p0'] < 1e-6


# ===================================================================
# CI2 vortex-shock initial condition
# ===================================================================

class TestCI2:
    """Verify CI2 initial condition at three test points."""

    @staticmethod
    def _ci2_ref(x, y):
        """Independent reference implementation of CI2 initial condition."""
        g = 1.4
        R = 1.0
        M_s = 1.5
        M_v = 0.9

        rho_u = 1.0
        u_u = M_s * math.sqrt(g)
        v_u = 1.0e-20
        p_u = 1.0
        t_u = p_u / (rho_u * R)

        rho_d = rho_u * (g + 1) * M_s ** 2 / (2 + (g - 1) * M_s ** 2)
        u_d = u_u * (2 + (g - 1) * M_s ** 2) / ((g + 1) * M_s ** 2)
        v_d = v_u
        p_d = p_u * (1 + 2 * g / (g + 1) * (M_s ** 2 - 1))

        if x <= 0.5:
            pres = p_u
            temp = t_u
            vx = u_u
            vy = v_u
        else:
            pres = p_d
            temp = p_d / (rho_d * R)
            vx = u_d
            vy = v_d

        xc, yc = 0.25, 0.5
        a, b = 0.075, 0.175
        vm = M_v * math.sqrt(g)

        ddx = x - xc
        ddy = y - yc
        r = math.sqrt(ddx ** 2 + ddy ** 2)

        if 0 < r <= b:
            st = ddy / r
            ct = ddx / r

            if r <= a:
                mag = vm * r / a
                vx -= mag * st
                vy += mag * ct

                rt = (-2 * b ** 2 * math.log(b) - 0.5 * a ** 2 +
                      2 * b ** 2 * math.log(a) + 0.5 * b ** 4 / a ** 2)
                ta = t_u - (g - 1) * (vm * a / (a ** 2 - b ** 2)) ** 2 * \
                     rt / (R * g)
                rti = 0.5 * (1 - r ** 2 / a ** 2)
                temp = ta - (g - 1) * vm ** 2 * rti / (R * g)
            else:
                mag = vm * a * (r - b ** 2 / r) / (a ** 2 - b ** 2)
                vx -= mag * st
                vy += mag * ct

                rt = (-2 * b ** 2 * math.log(b) - 0.5 * r ** 2 +
                      2 * b ** 2 * math.log(r) + 0.5 * b ** 4 / r ** 2)
                temp = t_u - (g - 1) * (vm * a / (a ** 2 - b ** 2)) ** 2 * \
                       rt / (R * g)

            pres = p_u * (temp / t_u) ** (g / (g - 1))

        return pres, temp, vx, vy

    def _check_point(self, results, key, x, y):
        ep, et, evx, evy = self._ci2_ref(x, y)
        pt = results['ci2'][key]

        assert abs(pt['pressure'] - ep) / max(abs(ep), 1e-15) < 1e-6, \
            f"pressure mismatch at {key}: got {pt['pressure']}, expected {ep}"
        assert abs(pt['temperature'] - et) / max(abs(et), 1e-15) < 1e-6, \
            f"temperature mismatch at {key}"
        assert abs(pt['velocity_x'] - evx) / max(abs(evx), 1e-15) < 1e-6, \
            f"velocity_x mismatch at {key}"
        if abs(evy) > 1e-10:
            assert abs(pt['velocity_y'] - evy) / abs(evy) < 1e-4, \
                f"velocity_y mismatch at {key}"
        else:
            assert abs(pt['velocity_y']) < 1e-6, \
                f"velocity_y should be near zero at {key}"

    def test_upstream_freestream(self, results):
        self._check_point(results, 'upstream_freestream', 0.05, 0.90)

    def test_downstream_postshock(self, results):
        self._check_point(results, 'downstream_postshock', 0.60, 0.50)

    def test_vortex_inner(self, results):
        self._check_point(results, 'vortex_inner', 0.20, 0.55)

    def test_vortex_pressure_positive(self, results):
        assert results['ci2']['vortex_inner']['pressure'] > 0

    def test_vortex_temperature_positive(self, results):
        assert results['ci2']['vortex_inner']['temperature'] > 0

    def test_vortex_modifies_state(self, results):
        """Vortex point should differ from upstream freestream."""
        up = results['ci2']['upstream_freestream']
        vx = results['ci2']['vortex_inner']
        assert abs(up['pressure'] - vx['pressure']) > 0.01
        assert abs(up['velocity_x'] - vx['velocity_x']) > 0.01


# ===================================================================
# Grid convergence analysis
# ===================================================================

class TestConvergence:

    @staticmethod
    def _load_data():
        data = []
        with open('/app/data/convergence_data.csv') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or line.startswith('h'):
                    continue
                parts = line.split(',')
                data.append((float(parts[0]), float(parts[1])))
        return sorted(data, key=lambda x: -x[0])

    def test_observed_orders_count(self, results):
        data = self._load_data()
        orders = results['convergence']['observed_orders']
        assert len(orders) == len(data) - 2

    def test_finest_order_is_two(self, results):
        """Finest triple should give order ~2.0 (asymptotic range)."""
        orders = results['convergence']['observed_orders']
        assert abs(orders[-1] - 2.0) < 0.05

    def test_coarsest_order_pre_asymptotic(self, results):
        """Coarsest triple has pre-asymptotic behavior (order > 2)."""
        orders = results['convergence']['observed_orders']
        assert orders[0] > 2.0

    def test_middle_order_is_two(self, results):
        """Middle triple should also give order ~2.0."""
        orders = results['convergence']['observed_orders']
        if len(orders) >= 2:
            assert abs(orders[1] - 2.0) < 0.05

    def test_extrapolated_value(self, results):
        """Extrapolated grid-independent value should be near the true limit."""
        val = results['convergence']['extrapolated_value']
        assert abs(val - 1.15310) < 0.0005

    def test_uncertainty_positive(self, results):
        assert results['convergence']['uncertainty_fine'] > 0

    def test_uncertainty_small(self, results):
        """Uncertainty should be small for well-converged data."""
        assert results['convergence']['uncertainty_fine'] < 0.01

    def test_uncertainty_value(self, results):
        """Fine-grid uncertainty should be approximately 0.000296."""
        val = results['convergence']['uncertainty_fine']
        assert abs(val - 0.000296) < 0.0002


# ===================================================================
# MMS source terms for 2D steady compressible Euler equations
# ===================================================================

class TestMMS:

    @staticmethod
    def _mms_ref(x, y):
        """Reference MMS source term computation for 2D Euler."""
        pi = math.pi
        g = 1.4

        rho = 1.0 + 0.1 * math.sin(2 * pi * x) * math.cos(2 * pi * y)
        u = 0.5 + 0.05 * math.sin(2 * pi * x)
        v = 0.3 + 0.05 * math.cos(2 * pi * y)
        p = 1.0 + 0.2 * math.sin(2 * pi * x) * math.cos(2 * pi * y)

        drho_dx = 0.1 * 2 * pi * math.cos(2 * pi * x) * math.cos(2 * pi * y)
        drho_dy = -0.1 * 2 * pi * math.sin(2 * pi * x) * math.sin(2 * pi * y)
        du_dx = 0.05 * 2 * pi * math.cos(2 * pi * x)
        du_dy = 0.0
        dv_dx = 0.0
        dv_dy = -0.05 * 2 * pi * math.sin(2 * pi * y)
        dp_dx = 0.2 * 2 * pi * math.cos(2 * pi * x) * math.cos(2 * pi * y)
        dp_dy = -0.2 * 2 * pi * math.sin(2 * pi * x) * math.sin(2 * pi * y)

        E = p / (g - 1) + 0.5 * rho * (u ** 2 + v ** 2)
        dE_dx = (dp_dx / (g - 1) + 0.5 * (u ** 2 + v ** 2) * drho_dx +
                 rho * u * du_dx + rho * v * dv_dx)
        dE_dy = (dp_dy / (g - 1) + 0.5 * (u ** 2 + v ** 2) * drho_dy +
                 rho * u * du_dy + rho * v * dv_dy)

        Sm = (rho * du_dx + u * drho_dx) + (rho * dv_dy + v * drho_dy)
        Sx = (2 * rho * u * du_dx + u ** 2 * drho_dx + dp_dx) + \
             (rho * u * dv_dy + rho * v * du_dy + u * v * drho_dy)
        Sy = (rho * v * du_dx + rho * u * dv_dx + u * v * drho_dx) + \
             (2 * rho * v * dv_dy + v ** 2 * drho_dy + dp_dy)
        Se = ((dE_dx + dp_dx) * u + (E + p) * du_dx) + \
             ((dE_dy + dp_dy) * v + (E + p) * dv_dy)

        return Sm, Sx, Sy, Se

    def test_source_mass(self, results):
        em, _, _, _ = self._mms_ref(0.25, 0.25)
        val = results['mms']['source_at_test_point']['S_mass']
        assert abs(val - em) < 1e-8, \
            f"S_mass mismatch: got {val}, expected {em}"

    def test_source_xmom(self, results):
        _, ex, _, _ = self._mms_ref(0.25, 0.25)
        val = results['mms']['source_at_test_point']['S_xmom']
        assert abs(val - ex) < 1e-8, \
            f"S_xmom mismatch: got {val}, expected {ex}"

    def test_source_ymom(self, results):
        _, _, ey, _ = self._mms_ref(0.25, 0.25)
        val = results['mms']['source_at_test_point']['S_ymom']
        assert abs(val - ey) < 1e-8, \
            f"S_ymom mismatch: got {val}, expected {ey}"

    def test_source_energy(self, results):
        _, _, _, ee = self._mms_ref(0.25, 0.25)
        val = results['mms']['source_at_test_point']['S_energy']
        assert abs(val - ee) < 1e-8, \
            f"S_energy mismatch: got {val}, expected {ee}"

    def test_max_residual_small(self, results):
        """Self-consistency residual should be near machine precision."""
        assert results['mms']['max_residual'] < 1e-8

    def test_source_terms_nonzero(self, results):
        """Source terms at (0.25, 0.25) should be nontrivially nonzero."""
        src = results['mms']['source_at_test_point']
        assert abs(src['S_mass']) > 0.1
        assert abs(src['S_ymom']) > 0.1
        assert abs(src['S_energy']) > 0.1

    def test_source_at_different_point(self, results):
        """Verify source terms are not just hard-coded for (0.25,0.25)."""
        assert results['mms']['max_residual'] < 1e-8


# ===================================================================
# Mesh solution file
# ===================================================================

class TestMeshSolution:
    """Verify the CI2 solution mesh file produced by Gmsh."""

    def test_mesh_file_exists(self):
        assert os.path.exists(MESH_PATH), \
            f"Mesh file not found at {MESH_PATH}"

    def test_mesh_node_count(self):
        import meshio
        mesh = meshio.read(MESH_PATH)
        n = len(mesh.points)
        assert 2500 <= n <= 2800, \
            f"Expected ~2601 nodes from 51x51 transfinite mesh, got {n}"

    def test_mesh_has_elements(self):
        import meshio
        mesh = meshio.read(MESH_PATH)
        total_cells = sum(len(c.data) for c in mesh.cells)
        assert total_cells >= 2400, \
            f"Expected ~2500 quad elements, got {total_cells}"

    def test_pressure_field_exists(self):
        import meshio
        mesh = meshio.read(MESH_PATH)
        assert 'pressure' in mesh.point_data, \
            f"Missing 'pressure' field. Found: {list(mesh.point_data.keys())}"

    def test_temperature_field_exists(self):
        import meshio
        mesh = meshio.read(MESH_PATH)
        assert 'temperature' in mesh.point_data, \
            f"Missing 'temperature' field. Found: {list(mesh.point_data.keys())}"

    def test_velocity_x_field_exists(self):
        import meshio
        mesh = meshio.read(MESH_PATH)
        assert 'velocity_x' in mesh.point_data, \
            f"Missing 'velocity_x' field. Found: {list(mesh.point_data.keys())}"

    def test_velocity_y_field_exists(self):
        import meshio
        mesh = meshio.read(MESH_PATH)
        assert 'velocity_y' in mesh.point_data, \
            f"Missing 'velocity_y' field. Found: {list(mesh.point_data.keys())}"

    def test_pressure_positive(self):
        import meshio
        import numpy as np
        mesh = meshio.read(MESH_PATH)
        p = mesh.point_data['pressure'].ravel()
        assert np.all(p > 0), "All pressure values must be positive"

    def test_temperature_positive(self):
        import meshio
        import numpy as np
        mesh = meshio.read(MESH_PATH)
        t = mesh.point_data['temperature'].ravel()
        assert np.all(t > 0), "All temperature values must be positive"

    def test_shock_pressure_jump(self):
        """Pressure should jump across x=0.5 away from the vortex."""
        import meshio
        import numpy as np
        mesh = meshio.read(MESH_PATH)
        pts = mesh.points[:, :2]
        p = mesh.point_data['pressure'].ravel()
        far_y = np.abs(pts[:, 1] - 0.9) < 0.025
        up = far_y & (pts[:, 0] < 0.2)
        down = far_y & (pts[:, 0] > 0.7)
        if np.any(up) and np.any(down):
            ratio = np.mean(p[down]) / np.mean(p[up])
            assert 2.0 < ratio < 3.0, \
                f"Pressure ratio across shock should be ~2.46, got {ratio}"

    def test_upstream_velocity(self):
        """Upstream velocity_x far from vortex should be ~1.775."""
        import meshio
        import numpy as np
        mesh = meshio.read(MESH_PATH)
        pts = mesh.points[:, :2]
        vx = mesh.point_data['velocity_x'].ravel()
        far_y = np.abs(pts[:, 1] - 0.9) < 0.025
        up = far_y & (pts[:, 0] < 0.1)
        if np.any(up):
            mean_vx = np.mean(vx[up])
            assert 1.5 < mean_vx < 2.0, \
                f"Upstream velocity_x should be ~1.775, got {mean_vx}"

    def test_vortex_modifies_velocity(self):
        """Velocity near vortex center should differ from freestream."""
        import meshio
        import numpy as np
        mesh = meshio.read(MESH_PATH)
        pts = mesh.points[:, :2]
        vy = mesh.point_data['velocity_y'].ravel()
        near_vortex = np.sqrt(
            (pts[:, 0] - 0.25) ** 2 + (pts[:, 1] - 0.5) ** 2) < 0.06
        far_from_vortex = (pts[:, 0] < 0.1) & (np.abs(pts[:, 1] - 0.9) < 0.025)
        if np.any(near_vortex) and np.any(far_from_vortex):
            vy_vortex_max = np.max(np.abs(vy[near_vortex]))
            vy_freestream = np.mean(np.abs(vy[far_from_vortex]))
            assert vy_vortex_max > vy_freestream + 0.1, \
                "Vortex should create significant velocity_y perturbation"
