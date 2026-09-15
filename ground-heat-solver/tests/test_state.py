
import json
import os
import sqlite3
import pytest
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


# ---------------------------------------------------------------------------
# Reference finite-difference solver (independent of agent's FEM approach)
# ---------------------------------------------------------------------------

def reference_solve(case_params, slab_params, wall_params, h=0.05):
    """
    2D finite-difference steady-state heat conduction solver.
    Returns total heat loss per unit length (W/m) for full slab width.
    """
    a = case_params["slab_half_width_m"]
    far = case_params["far_field_distance_m"]
    D = case_params["deep_ground_depth_m"]
    k_soil = case_params["soil_conductivity_W_per_mK"]
    T_in = case_params["T_indoor_C"]
    T_out = case_params["T_outdoor_C"]
    T_deep = case_params["T_deep_ground_C"]
    k_slab = slab_params["conductivity_W_per_mK"]
    t_slab = slab_params["thickness_m"]
    w_wall = wall_params["width_m"]

    ins = case_params.get("insulation")
    k_ins = ins["conductivity_W_per_mK"] if ins else None
    t_ins = ins["thickness_m"] if ins else 0.0

    W = a + far
    dx = dy = h
    nx = int(round(W / dx)) + 1
    ny = int(round(D / dy)) + 1
    N = nx * ny

    i_slab = int(round(a / dx))
    i_wall = int(round((a + w_wall) / dx))
    j_slab = int(round(t_slab / dy))
    j_ins = int(round((t_slab + t_ins) / dy)) if ins else j_slab

    k_field = np.full((ny, nx), k_soil, dtype=np.float64)
    k_field[:j_slab, :i_wall + 1] = k_slab
    if ins and j_ins > j_slab:
        k_field[j_slab:j_ins, :i_slab + 1] = k_ins

    inv_dx2 = 1.0 / (dx * dx)
    inv_dy2 = 1.0 / (dy * dy)

    row_idx, col_idx, data = [], [], []
    b = np.zeros(N, dtype=np.float64)

    for j in range(ny):
        for i in range(nx):
            n = j * nx + i

            if j == 0:
                if i <= i_slab:
                    row_idx.append(n); col_idx.append(n); data.append(1.0)
                    b[n] = T_in; continue
                elif i <= i_wall:
                    pass
                else:
                    row_idx.append(n); col_idx.append(n); data.append(1.0)
                    b[n] = T_out; continue

            if j == ny - 1:
                row_idx.append(n); col_idx.append(n); data.append(1.0)
                b[n] = T_deep; continue

            if i == nx - 1:
                row_idx.append(n); col_idx.append(n); data.append(1.0)
                b[n] = T_out; continue

            ki = k_field[j, i]
            diag = 0.0

            ke = 2.0 * ki * k_field[j, i + 1] / (ki + k_field[j, i + 1])
            ce = ke * inv_dx2; diag += ce
            row_idx.append(n); col_idx.append(j * nx + i + 1); data.append(-ce)

            if i > 0:
                kw = 2.0 * ki * k_field[j, i - 1] / (ki + k_field[j, i - 1])
                cw = kw * inv_dx2; diag += cw
                row_idx.append(n); col_idx.append(j * nx + i - 1); data.append(-cw)
            else:
                kw = 2.0 * ki * k_field[j, 1] / (ki + k_field[j, 1])
                cw = kw * inv_dx2; diag += cw
                row_idx.append(n); col_idx.append(j * nx + 1); data.append(-cw)

            if j == 0:
                ks = 2.0 * ki * k_field[1, i] / (ki + k_field[1, i])
                cs = 2.0 * ks * inv_dy2; diag += cs
                row_idx.append(n); col_idx.append(nx + i); data.append(-cs)
            else:
                kn = 2.0 * ki * k_field[j - 1, i] / (ki + k_field[j - 1, i])
                cn = kn * inv_dy2; diag += cn
                row_idx.append(n); col_idx.append((j - 1) * nx + i); data.append(-cn)
                ks = 2.0 * ki * k_field[j + 1, i] / (ki + k_field[j + 1, i])
                cs = ks * inv_dy2; diag += cs
                row_idx.append(n); col_idx.append((j + 1) * nx + i); data.append(-cs)

            row_idx.append(n); col_idx.append(n); data.append(diag)

    A = coo_matrix(
        (np.array(data), (np.array(row_idx), np.array(col_idx))),
        shape=(N, N),
    ).tocsr()

    T_sol = spsolve(A, b).reshape((ny, nx))

    Q_half = 0.0
    for i in range(i_slab + 1):
        Q_half += k_field[0, i] * (T_in - T_sol[1, i]) / dy * dx

    return 2.0 * Q_half


def _load_agent_value(results, case_name):
    val = results[case_name]
    if isinstance(val, dict):
        for key in ("heat_loss_per_meter", "heat_loss_W_per_m", "value", "Q"):
            if key in val:
                return float(val[key])
        raise ValueError(f"Cannot extract value for case '{case_name}': {val}")
    return float(val)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def config():
    with open("/app/config.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def agent_results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference_values(config):
    slab = config["slab"]
    wall = config["foundation_wall"]
    refs = {}
    for name, params in config["cases"].items():
        refs[name] = reference_solve(params, slab, wall, h=0.05)
    return refs


# ---------------------------------------------------------------------------
# File and format checks
# ---------------------------------------------------------------------------

class TestResultsFormat:
    def test_results_json_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_all_cases_present(self, config, agent_results):
        for case_name in config["cases"]:
            assert case_name in agent_results, f"Missing case '{case_name}'"

    def test_values_are_numeric(self, config, agent_results):
        for case_name in config["cases"]:
            val = _load_agent_value(agent_results, case_name)
            assert isinstance(val, (int, float)), f"'{case_name}' not numeric"
            assert np.isfinite(val), f"'{case_name}' not finite"


class TestMeshFiles:
    def test_meshes_directory_exists(self):
        assert os.path.isdir("/app/meshes"), "/app/meshes directory not found"

    def test_each_case_has_mesh(self, config):
        for case_name in config["cases"]:
            path = f"/app/meshes/{case_name}.msh"
            assert os.path.isfile(path), f"Mesh file {path} not found"

    def test_mesh_files_nonempty(self, config):
        for case_name in config["cases"]:
            path = f"/app/meshes/{case_name}.msh"
            size = os.path.getsize(path)
            assert size > 100, f"Mesh file {path} too small ({size} bytes)"


class TestSQLiteDatabase:
    def test_db_exists(self):
        assert os.path.isfile("/app/results.db"), "results.db not found"

    def test_table_schema(self):
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(results)")
        columns = {row[1]: row[2] for row in cur.fetchall()}
        conn.close()
        assert "case_name" in columns, "Missing column 'case_name'"
        assert "heat_loss_W_per_m" in columns, "Missing column 'heat_loss_W_per_m'"
        assert "num_nodes" in columns, "Missing column 'num_nodes'"
        assert "num_elements" in columns, "Missing column 'num_elements'"

    def test_all_cases_in_db(self, config):
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        cur.execute("SELECT case_name FROM results")
        db_cases = {row[0] for row in cur.fetchall()}
        conn.close()
        for case_name in config["cases"]:
            assert case_name in db_cases, f"Case '{case_name}' missing from database"

    def test_db_matches_json(self, agent_results):
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        cur.execute("SELECT case_name, heat_loss_W_per_m FROM results")
        db_vals = {row[0]: row[1] for row in cur.fetchall()}
        conn.close()
        for case_name, json_val in agent_results.items():
            json_v = _load_agent_value(agent_results, case_name)
            db_v = db_vals.get(case_name)
            assert db_v is not None, f"Case '{case_name}' missing from DB"
            assert abs(json_v - db_v) < 0.01, (
                f"JSON ({json_v}) != DB ({db_v}) for '{case_name}'"
            )

    def test_mesh_stats_positive(self):
        conn = sqlite3.connect("/app/results.db")
        cur = conn.cursor()
        cur.execute("SELECT case_name, num_nodes, num_elements FROM results")
        for name, nn, ne in cur.fetchall():
            assert nn > 0, f"num_nodes must be positive for '{name}'"
            assert ne > 0, f"num_elements must be positive for '{name}'"
        conn.close()


# ---------------------------------------------------------------------------
# Physics consistency
# ---------------------------------------------------------------------------

class TestPhysicsConsistency:
    def test_all_positive(self, config, agent_results):
        for case_name in config["cases"]:
            val = _load_agent_value(agent_results, case_name)
            assert val > 0, f"'{case_name}': heat loss must be positive, got {val}"

    def test_high_conductivity_increases_loss(self, agent_results):
        q_base = _load_agent_value(agent_results, "base")
        q_high = _load_agent_value(agent_results, "high_conductivity")
        assert q_high > q_base, (
            f"high_conductivity ({q_high:.2f}) should exceed base ({q_base:.2f})"
        )

    def test_smaller_slab_less_loss(self, agent_results):
        q_base = _load_agent_value(agent_results, "base")
        q_small = _load_agent_value(agent_results, "small_slab")
        assert q_small < q_base, (
            f"small_slab ({q_small:.2f}) should be less than base ({q_base:.2f})"
        )

    def test_shallow_ground_increases_loss(self, agent_results):
        q_base = _load_agent_value(agent_results, "base")
        q_shallow = _load_agent_value(agent_results, "shallow_ground")
        assert q_shallow > q_base, (
            f"shallow_ground ({q_shallow:.2f}) should exceed base ({q_base:.2f})"
        )

    def test_insulation_reduces_loss(self, agent_results):
        q_base = _load_agent_value(agent_results, "base")
        q_ins = _load_agent_value(agent_results, "insulated")
        assert q_ins < q_base, (
            f"insulated ({q_ins:.2f}) should be less than base ({q_base:.2f})"
        )

    def test_insulation_reduction_significant(self, agent_results):
        q_base = _load_agent_value(agent_results, "base")
        q_ins = _load_agent_value(agent_results, "insulated")
        ratio = q_ins / q_base
        assert ratio < 0.85, (
            f"Insulation ratio {ratio:.3f} not low enough (expected < 0.85)"
        )


# ---------------------------------------------------------------------------
# Numerical accuracy
# ---------------------------------------------------------------------------

class TestNumericalAccuracy:
    TOLERANCE = 0.05

    def _check_case(self, agent_results, reference_values, case_name):
        q_agent = _load_agent_value(agent_results, case_name)
        q_ref = reference_values[case_name]
        rel_err = abs(q_agent - q_ref) / abs(q_ref)
        assert rel_err < self.TOLERANCE, (
            f"Case '{case_name}': agent={q_agent:.4f} W/m, ref={q_ref:.4f} W/m, "
            f"rel_error={rel_err:.4f} (tolerance={self.TOLERANCE})"
        )

    def test_base(self, agent_results, reference_values):
        self._check_case(agent_results, reference_values, "base")

    def test_high_conductivity(self, agent_results, reference_values):
        self._check_case(agent_results, reference_values, "high_conductivity")

    def test_small_slab(self, agent_results, reference_values):
        self._check_case(agent_results, reference_values, "small_slab")

    def test_shallow_ground(self, agent_results, reference_values):
        self._check_case(agent_results, reference_values, "shallow_ground")

    def test_insulated(self, agent_results, reference_values):
        self._check_case(agent_results, reference_values, "insulated")
