
import json
import math
import os
import pytest

# ---- Physical parameters ----
GAMMA = 1.4
R_GAS = 1.0
M_S = 2.5
M_V = 0.8
RHO_U = 1.0
P_U = 1.0
T_U = P_U / (RHO_U * R_GAS)
U_U = M_S * math.sqrt(GAMMA * R_GAS * T_U)
V_U = 0.0
X_SHOCK = 0.5
X_C = 0.25
Y_C = 0.5
A = 0.075
B = 0.175
V_M = M_V * math.sqrt(GAMMA)

# ---- Rankine-Hugoniot downstream conditions ----
_M2 = M_S * M_S
RHO_D = RHO_U * (GAMMA + 1.0) * _M2 / (2.0 + (GAMMA - 1.0) * _M2)
U_D = U_U * (2.0 + (GAMMA - 1.0) * _M2) / ((GAMMA + 1.0) * _M2)
P_D = P_U * (1.0 + 2.0 * GAMMA / (GAMMA + 1.0) * (_M2 - 1.0))
T_D = P_D / (RHO_D * R_GAS)

EXP_RHO_RATIO = RHO_D / RHO_U
EXP_P_RATIO = P_D / P_U
EXP_T_RATIO = T_D / T_U

# Mesh expectations (200x200 transfinite quad mesh)
EXPECTED_NUM_NODES = 201 * 201    # 40401
EXPECTED_NUM_ELEMENTS = 200 * 200  # 40000

NX = 200
NY = 200
DX = 1.0 / NX
DY = 1.0 / NY

PROBE_COORDS = [
    (0.80, 0.50),
    (0.10, 0.20),
    (0.255, 0.50),
    (0.32, 0.50),
    (0.25, 0.42),
    (0.10, 0.50),
    (0.45, 0.50),
]


def _ref_compute(x, y):
    """Reference implementation of the flow field at a single point."""
    if x <= X_SHOCK:
        p = P_U
        t = T_U
        u = U_U
        v = V_U
    else:
        p = P_D
        t = T_D
        u = U_D
        v = V_U

    dx = x - X_C
    dy = y - Y_C
    r = math.sqrt(dx * dx + dy * dy)

    if r <= B and r > 1e-15:
        sin_th = dy / r
        cos_th = dx / r

        a2 = A * A
        b2 = B * B
        a2_b2 = a2 - b2  # negative since a < b

        if r <= A:
            mag = V_M * r / A
            u -= mag * sin_th
            v += mag * cos_th

            fac = V_M * A / a2_b2
            fac2 = fac * fac
            rt_a = (-2.0 * b2 * math.log(B)
                    - 0.5 * a2
                    + 2.0 * b2 * math.log(A)
                    + 0.5 * b2 * b2 / a2)
            t_a = T_U - (GAMMA - 1.0) * fac2 * rt_a / (R_GAS * GAMMA)

            rt_core = 0.5 * (1.0 - r * r / a2)
            t = t_a - (GAMMA - 1.0) * V_M * V_M * rt_core / (R_GAS * GAMMA)
        else:
            mag = V_M * A * (r - b2 / r) / a2_b2
            u -= mag * sin_th
            v += mag * cos_th

            fac = V_M * A / a2_b2
            fac2 = fac * fac
            rt = (-2.0 * b2 * math.log(B)
                  - 0.5 * r * r
                  + 2.0 * b2 * math.log(r)
                  + 0.5 * b2 * b2 / (r * r))
            t = T_U - (GAMMA - 1.0) * fac2 * rt / (R_GAS * GAMMA)

        p = P_U * math.pow(t / T_U, GAMMA / (GAMMA - 1.0))

    rho = p / (R_GAS * t)
    c = math.sqrt(GAMMA * R_GAS * t)
    mach = math.sqrt(u * u + v * v) / c

    return {
        "rho": rho, "u": u, "v": v,
        "p": p, "T": t, "mach": mach,
    }


def _load_results():
    with open("/app/results.json") as f:
        return json.load(f)


def _parse_msh_nodes(filename):
    """Parse nodes from a Gmsh MSH 2.2 file."""
    nodes = {}
    with open(filename) as f:
        while True:
            line = f.readline()
            if not line:
                break
            if line.strip() == "$Nodes":
                n = int(f.readline().strip())
                for _ in range(n):
                    parts = f.readline().split()
                    nid = int(parts[0])
                    x, y = float(parts[1]), float(parts[2])
                    nodes[nid] = (x, y)
                break
    return nodes


def _count_msh_quads(filename):
    """Count quad elements (type 3) in a Gmsh MSH 2.2 file."""
    count = 0
    with open(filename) as f:
        while True:
            line = f.readline()
            if not line:
                break
            if line.strip() == "$Elements":
                n = int(f.readline().strip())
                for _ in range(n):
                    parts = f.readline().split()
                    if int(parts[1]) == 3:
                        count += 1
                break
    return count


def _parse_nodedata(filename):
    """Parse all $NodeData sections from a Gmsh .msh file (line-by-line)."""
    fields = {}
    with open(filename) as f:
        while True:
            line = f.readline()
            if not line:
                break
            if line.strip() == "$NodeData":
                # String tags
                n_str = int(f.readline().strip())
                field_name = f.readline().strip().strip('"')
                for _ in range(n_str - 1):
                    f.readline()
                # Real tags
                n_real = int(f.readline().strip())
                for _ in range(n_real):
                    f.readline()
                # Integer tags
                n_int = int(f.readline().strip())
                int_tags = []
                for _ in range(n_int):
                    int_tags.append(int(f.readline().strip()))
                n_values = int_tags[-1]  # last int tag = num entities

                values = {}
                for _ in range(n_values):
                    parts = f.readline().split()
                    nid = int(parts[0])
                    val = float(parts[1])
                    values[nid] = val

                fields[field_name] = values
                # read $EndNodeData
                f.readline()
    return fields


def _find_nearest_node(nodes, tx, ty):
    """Find node ID closest to (tx, ty)."""
    best_id = None
    best_dist = float("inf")
    for nid, (x, y) in nodes.items():
        d2 = (x - tx) ** 2 + (y - ty) ** 2
        if d2 < best_dist:
            best_dist = d2
            best_id = nid
    return best_id, math.sqrt(best_dist)


# ---------- Tests: Result file ----------

class TestResultsExist:
    def test_file_exists(self):
        assert os.path.isfile("/app/results.json"), \
            "results.json not found at /app/results.json"

    def test_json_loadable(self):
        data = _load_results()
        assert isinstance(data, dict)


# ---------- Tests: Mesh generation ----------

class TestMeshGeneration:
    def test_mesh_file_exists(self):
        assert os.path.isfile("/app/mesh.msh"), \
            "mesh.msh not found — Gmsh mesh generation required"

    def test_mesh_node_count(self):
        nodes = _parse_msh_nodes("/app/mesh.msh")
        assert len(nodes) == EXPECTED_NUM_NODES, \
            f"Expected {EXPECTED_NUM_NODES} nodes, got {len(nodes)}"

    def test_mesh_element_count(self):
        nq = _count_msh_quads("/app/mesh.msh")
        assert nq == EXPECTED_NUM_ELEMENTS, \
            f"Expected {EXPECTED_NUM_ELEMENTS} quad elements, got {nq}"

    def test_results_mesh_stats(self):
        data = _load_results()
        assert data["num_nodes"] == EXPECTED_NUM_NODES, \
            f"num_nodes: expected {EXPECTED_NUM_NODES}, got {data['num_nodes']}"
        assert data["num_elements"] == EXPECTED_NUM_ELEMENTS, \
            f"num_elements: expected {EXPECTED_NUM_ELEMENTS}, got {data['num_elements']}"


# ---------- Tests: Solution MSH file ----------

class TestSolutionMsh:
    def test_solution_file_exists(self):
        assert os.path.isfile("/app/solution.msh"), \
            "solution.msh not found — NodeData output required"

    def test_nodedata_fields_present(self):
        fields = _parse_nodedata("/app/solution.msh")
        for name in ["rho", "u", "v", "p", "T", "mach"]:
            assert name in fields, \
                f"NodeData section '{name}' missing from solution.msh"

    def test_nodedata_value_counts(self):
        fields = _parse_nodedata("/app/solution.msh")
        for name, values in fields.items():
            assert len(values) == EXPECTED_NUM_NODES, \
                f"NodeData '{name}': expected {EXPECTED_NUM_NODES} values, got {len(values)}"

    def test_nodedata_downstream_spot_check(self):
        """Verify NodeData at a node in the downstream (post-shock) region."""
        fields = _parse_nodedata("/app/solution.msh")
        nodes = _parse_msh_nodes("/app/solution.msh")

        nid, dist = _find_nearest_node(nodes, 0.8, 0.5)
        assert dist < 0.01
        nx, ny = nodes[nid]
        ref = _ref_compute(nx, ny)

        for key in ["rho", "u", "v", "p", "T", "mach"]:
            got = fields[key][nid]
            exp = ref[key]
            denom = max(abs(exp), 1e-10)
            rel_err = abs(got - exp) / denom
            assert rel_err < 1e-4, \
                f"NodeData {key} at downstream node {nid}: expected {exp}, got {got}"

    def test_nodedata_vortex_core_spot_check(self):
        """Verify NodeData at a node inside the vortex core."""
        fields = _parse_nodedata("/app/solution.msh")
        nodes = _parse_msh_nodes("/app/solution.msh")

        nid, dist = _find_nearest_node(nodes, 0.255, 0.50)
        assert dist < 0.01
        nx, ny = nodes[nid]
        ref = _ref_compute(nx, ny)

        for key in ["rho", "p", "T"]:
            got = fields[key][nid]
            exp = ref[key]
            denom = max(abs(exp), 1e-10)
            rel_err = abs(got - exp) / denom
            assert rel_err < 1e-4, \
                f"NodeData {key} at core node {nid}: expected {exp}, got {got}"


# ---------- Tests: Shock ratios ----------

class TestShockRatios:
    def test_density_ratio(self):
        data = _load_results()
        assert "shock_density_ratio" in data
        assert abs(data["shock_density_ratio"] - EXP_RHO_RATIO) < 1e-6, \
            f"Expected {EXP_RHO_RATIO}, got {data['shock_density_ratio']}"

    def test_pressure_ratio(self):
        data = _load_results()
        assert "shock_pressure_ratio" in data
        assert abs(data["shock_pressure_ratio"] - EXP_P_RATIO) < 1e-6, \
            f"Expected {EXP_P_RATIO}, got {data['shock_pressure_ratio']}"

    def test_temperature_ratio(self):
        data = _load_results()
        assert "shock_temperature_ratio" in data
        assert abs(data["shock_temperature_ratio"] - EXP_T_RATIO) < 1e-6, \
            f"Expected {EXP_T_RATIO}, got {data['shock_temperature_ratio']}"


# ---------- Tests: Probe points ----------

class TestProbePoints:
    def test_probe_count(self):
        data = _load_results()
        assert "probe_points" in data
        assert len(data["probe_points"]) == 7

    @pytest.mark.parametrize("idx", range(7))
    def test_probe_values(self, idx):
        data = _load_results()
        probe = data["probe_points"][idx]
        px, py = PROBE_COORDS[idx]

        ref = _ref_compute(px, py)

        for key in ("rho", "u", "v", "p", "T", "mach"):
            got = probe[key]
            exp = ref[key]
            denom = max(abs(exp), 1e-10)
            rel_err = abs(got - exp) / denom
            assert rel_err < 1e-6, (
                f"Probe {idx} ({px},{py}): {key} expected {exp}, "
                f"got {got}, rel_err={rel_err:.2e}"
            )

    @pytest.mark.parametrize("idx", range(7))
    def test_ideal_gas_law(self, idx):
        """Verify p = rho * R * T at each probe point."""
        data = _load_results()
        probe = data["probe_points"][idx]
        p_check = probe["rho"] * R_GAS * probe["T"]
        rel_err = abs(probe["p"] - p_check) / max(abs(probe["p"]), 1e-10)
        assert rel_err < 1e-8, \
            f"Probe {idx}: ideal gas law violated, p={probe['p']}, rho*R*T={p_check}"

    def test_isentropic_relation_vortex_core(self):
        """Verify isentropic relation at a vortex core probe point."""
        data = _load_results()
        probe = data["probe_points"][2]
        p_isen = P_U * math.pow(probe["T"] / T_U, GAMMA / (GAMMA - 1.0))
        rel_err = abs(probe["p"] - p_isen) / max(abs(probe["p"]), 1e-10)
        assert rel_err < 1e-6, \
            f"Isentropic relation violated in core: p={probe['p']}, expected={p_isen}"

    def test_isentropic_relation_vortex_outer(self):
        """Verify isentropic relation at a vortex outer region probe point."""
        data = _load_results()
        probe = data["probe_points"][4]
        p_isen = P_U * math.pow(probe["T"] / T_U, GAMMA / (GAMMA - 1.0))
        rel_err = abs(probe["p"] - p_isen) / max(abs(probe["p"]), 1e-10)
        assert rel_err < 1e-6, \
            f"Isentropic relation violated in outer: p={probe['p']}, expected={p_isen}"

    def test_downstream_no_vortex(self):
        """Probe 0 (downstream) should have undisturbed post-shock values."""
        data = _load_results()
        probe = data["probe_points"][0]
        assert abs(probe["rho"] - RHO_D) / RHO_D < 1e-8
        assert abs(probe["u"] - U_D) / U_D < 1e-8
        assert abs(probe["v"]) < 1e-10
        assert abs(probe["p"] - P_D) / P_D < 1e-8

    def test_upstream_outside_vortex(self):
        """Probe 1 (upstream, outside vortex) should have undisturbed values."""
        data = _load_results()
        probe = data["probe_points"][1]
        assert abs(probe["rho"] - RHO_U) / RHO_U < 1e-8
        assert abs(probe["u"] - U_U) / U_U < 1e-8
        assert abs(probe["v"]) < 1e-10
        assert abs(probe["p"] - P_U) / P_U < 1e-8


# ---------- Tests: Integral quantities ----------

class TestIntegralQuantities:
    @pytest.fixture(scope="class")
    def ref_integrals(self):
        """Compute reference integrals on the 200x200 cell-centered grid."""
        total_mass = 0.0
        total_ke = 0.0
        max_mach = 0.0
        min_pressure = float("inf")

        for i in range(NX):
            x = (i + 0.5) * DX
            for j in range(NY):
                y = (j + 0.5) * DY
                ref = _ref_compute(x, y)
                rho = ref["rho"]
                u = ref["u"]
                v = ref["v"]
                p = ref["p"]
                mach = ref["mach"]

                total_mass += rho * DX * DY
                total_ke += 0.5 * rho * (u * u + v * v) * DX * DY
                if mach > max_mach:
                    max_mach = mach
                if p < min_pressure:
                    min_pressure = p

        return {
            "total_mass": total_mass,
            "total_kinetic_energy": total_ke,
            "max_mach": max_mach,
            "min_pressure": min_pressure,
        }

    def test_total_mass(self, ref_integrals):
        data = _load_results()
        exp = ref_integrals["total_mass"]
        got = data["total_mass"]
        rel_err = abs(got - exp) / abs(exp)
        assert rel_err < 1e-3, \
            f"total_mass: expected {exp}, got {got}, rel_err={rel_err:.2e}"

    def test_total_kinetic_energy(self, ref_integrals):
        data = _load_results()
        exp = ref_integrals["total_kinetic_energy"]
        got = data["total_kinetic_energy"]
        rel_err = abs(got - exp) / abs(exp)
        assert rel_err < 1e-3, \
            f"total_kinetic_energy: expected {exp}, got {got}, rel_err={rel_err:.2e}"

    def test_max_mach(self, ref_integrals):
        data = _load_results()
        exp = ref_integrals["max_mach"]
        got = data["max_mach"]
        rel_err = abs(got - exp) / max(abs(exp), 1e-10)
        assert rel_err < 5e-3, \
            f"max_mach: expected {exp}, got {got}, rel_err={rel_err:.2e}"

    def test_min_pressure(self, ref_integrals):
        data = _load_results()
        exp = ref_integrals["min_pressure"]
        got = data["min_pressure"]
        rel_err = abs(got - exp) / max(abs(exp), 1e-10)
        assert rel_err < 5e-3, \
            f"min_pressure: expected {exp}, got {got}, rel_err={rel_err:.2e}"

    def test_mass_physical_bounds(self):
        """Total mass must be between pure-upstream and pure-downstream limits."""
        data = _load_results()
        mass = data["total_mass"]
        assert RHO_U * 1.0 < mass < RHO_D * 1.0, \
            f"total_mass={mass} outside physical bounds [{RHO_U}, {RHO_D}]"

    def test_max_mach_physical_bounds(self):
        """Max Mach should exceed upstream Mach (vortex adds velocity)."""
        data = _load_results()
        assert data["max_mach"] > M_S, \
            f"max_mach={data['max_mach']} should exceed M_s={M_S}"

    def test_min_pressure_physical_bounds(self):
        """Min pressure should be below upstream pressure (vortex lowers it)."""
        data = _load_results()
        assert data["min_pressure"] < P_U, \
            f"min_pressure={data['min_pressure']} should be below P_u={P_U}"
