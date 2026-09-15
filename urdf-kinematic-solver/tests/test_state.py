"""
Reference implementation and tests for advanced manipulator kinematic analysis.
Independently computes all expected results and compares against agent output.
"""


import json
import os
import xml.etree.ElementTree as ET

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Reference FK / Jacobian implementation
# ---------------------------------------------------------------------------

def _rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rot_z(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _rpy_to_rotation(roll, pitch, yaw):
    return _rot_z(yaw) @ _rot_y(pitch) @ _rot_x(roll)


def _axis_angle_rotation(axis, angle):
    axis = np.array(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0],
    ])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)


def _make_transform(R, p):
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


def _parse_urdf(urdf_path):
    tree = ET.parse(urdf_path)
    root = tree.getroot()
    joints = {}
    for je in root.findall("joint"):
        name = je.get("name")
        jtype = je.get("type")
        parent = je.find("parent").get("link")
        child = je.find("child").get("link")
        origin = je.find("origin")
        xyz = [0.0, 0.0, 0.0]
        rpy = [0.0, 0.0, 0.0]
        if origin is not None:
            if origin.get("xyz"):
                xyz = list(map(float, origin.get("xyz").split()))
            if origin.get("rpy"):
                rpy = list(map(float, origin.get("rpy").split()))
        axis = [0.0, 0.0, 1.0]
        ae = je.find("axis")
        if ae is not None and ae.get("xyz"):
            axis = list(map(float, ae.get("xyz").split()))
        limits = {"lower": -np.pi, "upper": np.pi}
        le = je.find("limit")
        if le is not None:
            if le.get("lower"):
                limits["lower"] = float(le.get("lower"))
            if le.get("upper"):
                limits["upper"] = float(le.get("upper"))
        joints[name] = {
            "name": name, "type": jtype, "parent": parent, "child": child,
            "xyz": xyz, "rpy": rpy, "axis": axis, "limits": limits,
        }
    return joints


def _build_chain(joints, start_link, end_link):
    child_to_joint = {j["child"]: j for j in joints.values()}
    chain = []
    cur = end_link
    while cur != start_link:
        if cur not in child_to_joint:
            raise ValueError(f"No path from {start_link} to {end_link}")
        j = child_to_joint[cur]
        chain.append(j)
        cur = j["parent"]
    chain.reverse()
    return chain


def _get_active(chain):
    return [j for j in chain if j["type"] in ("revolute", "continuous", "prismatic")]


def _fk(chain, jv, joint_order):
    active = _get_active(chain)
    q_map = {}
    for i, j in enumerate(active):
        if i < len(jv):
            q_map[j["name"]] = jv[i]
    T = np.eye(4)
    for j in chain:
        R_o = _rpy_to_rotation(j["rpy"][0], j["rpy"][1], j["rpy"][2])
        T_o = _make_transform(R_o, j["xyz"])
        T = T @ T_o
        if j["type"] in ("revolute", "continuous"):
            q = q_map.get(j["name"], 0.0)
            R_j = _axis_angle_rotation(j["axis"], q)
            T = T @ _make_transform(R_j, [0, 0, 0])
        elif j["type"] == "prismatic":
            q = q_map.get(j["name"], 0.0)
            T = T @ _make_transform(np.eye(3), q * np.array(j["axis"]))
    return T


def _joint_frames(chain, jv):
    active = _get_active(chain)
    q_map = {}
    for i, j in enumerate(active):
        if i < len(jv):
            q_map[j["name"]] = jv[i]
    frames = []
    T = np.eye(4)
    for j in chain:
        R_o = _rpy_to_rotation(j["rpy"][0], j["rpy"][1], j["rpy"][2])
        T_o = _make_transform(R_o, j["xyz"])
        T = T @ T_o
        if j["type"] in ("revolute", "continuous"):
            axis_w = T[:3, :3] @ np.array(j["axis"])
            frames.append({"axis": axis_w, "pos": T[:3, 3].copy(), "type": "revolute"})
            q = q_map.get(j["name"], 0.0)
            R_j = _axis_angle_rotation(j["axis"], q)
            T = T @ _make_transform(R_j, [0, 0, 0])
        elif j["type"] == "prismatic":
            axis_w = T[:3, :3] @ np.array(j["axis"])
            frames.append({"axis": axis_w, "pos": T[:3, 3].copy(), "type": "prismatic"})
            q = q_map.get(j["name"], 0.0)
            T = T @ _make_transform(np.eye(3), q * np.array(j["axis"]))
    return frames


def _jacobian(chain, jv, joint_order):
    T_ee = _fk(chain, jv, joint_order)
    p_ee = T_ee[:3, 3]
    frames = _joint_frames(chain, jv)
    n = len(frames)
    J = np.zeros((6, n))
    for i, f in enumerate(frames):
        z = f["axis"]
        p = f["pos"]
        if f["type"] == "revolute":
            J[:3, i] = np.cross(z, p_ee - p)
            J[3:, i] = z
        elif f["type"] == "prismatic":
            J[:3, i] = z
    return J


def _svd_analysis(J, sing_thresholds):
    U, s, Vt = np.linalg.svd(J)
    s_sorted = np.sort(s)[::-1]
    manipulability = float(np.prod(s))
    min_sv = float(s_sorted[-1])
    max_sv = float(s_sorted[0])
    cond = max_sv / min_sv if min_sv > 1e-10 else 1e12
    if min_sv < sing_thresholds["singular"]:
        sing_class = "singular"
    elif min_sv < sing_thresholds["near_singular"]:
        sing_class = "near_singular"
    else:
        sing_class = "well_conditioned"
    return {
        "manipulability": manipulability,
        "singular_values": s_sorted.tolist(),
        "condition_number": cond,
        "singularity_class": sing_class,
        "min_sv": min_sv,
    }


def _static_torques(J, wrench):
    return (J.T @ np.array(wrench)).tolist()


def _max_reach(chain, joints_data, joint_order):
    active = _get_active(chain)
    bounds = [(j["limits"]["lower"], j["limits"]["upper"]) for j in active]
    best = 0.0
    np.random.seed(123)  # Different seed from solution to ensure independence
    for _ in range(8000):
        q = np.array([np.random.uniform(lo, hi) for lo, hi in bounds])
        T = _fk(chain, q, joint_order)
        d = np.linalg.norm(T[:3, 3])
        if d > best:
            best = d
    key_configs = [
        [0, -np.pi / 2, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [0, -np.pi / 2, 0, np.pi / 2, 0, 0],
        [0, -np.pi / 2, 0, -np.pi / 2, 0, 0],
        [0, np.pi / 2, 0, 0, 0, 0],
        [0, -np.pi / 2, 0, 0, np.pi / 2, 0],
        [0, -np.pi / 2, 0, 0, -np.pi / 2, 0],
        [np.pi / 4, -np.pi / 2, 0, 0, 0, 0],
    ]
    for cfg in key_configs:
        T = _fk(chain, cfg, joint_order)
        d = np.linalg.norm(T[:3, 3])
        if d > best:
            best = d
    return best


def _workspace_monte_carlo(chain, joint_order, seed, n_samples, threshold):
    active = _get_active(chain)
    bounds = [(j["limits"]["lower"], j["limits"]["upper"]) for j in active]
    np.random.seed(seed)
    manip_values = []
    for _ in range(n_samples):
        q = np.array([np.random.uniform(lo, hi) for lo, hi in bounds])
        J = _jacobian(chain, q, joint_order)
        _, s, _ = np.linalg.svd(J)
        w = float(np.prod(s))
        manip_values.append(w)
    dex_frac = sum(1 for w in manip_values if w > threshold) / n_samples
    avg_manip = sum(manip_values) / n_samples
    return dex_frac, avg_manip


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RESULTS_PATH = "/app/output/results.json"
QUERIES_PATH = "/app/queries.json"
VALID_VARIANTS = ["variant_a", "variant_b"]
ALL_VARIANTS = ["variant_a", "variant_b", "variant_c"]

EXPECTED_COUNTS = {
    "variant_a": {"num_links": 9, "num_joints": 8},
    "variant_b": {"num_links": 9, "num_joints": 8},
    "variant_c": {"num_links": 10, "num_joints": 9},
}


@pytest.fixture(scope="module")
def queries():
    with open(QUERIES_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def ref(queries):
    """Compute all reference results for valid variants."""
    joint_order = queries["joint_order"]
    wrench = np.array(queries["external_wrench"]["wrench"])
    sing_thresh = queries["singularity_thresholds"]
    ws_params = queries["workspace_analysis"]

    results = {}
    for vid in VALID_VARIANTS:
        urdf_path = f"/app/{vid}.urdf"
        joints = _parse_urdf(urdf_path)
        chain = _build_chain(joints, "base_link", "tool0")

        kin = {}
        for q in queries["kinematic_queries"]:
            jv = q["joint_values"]
            T = _fk(chain, jv, joint_order)
            J = _jacobian(chain, jv, joint_order)
            svd = _svd_analysis(J, sing_thresh)
            torques = _static_torques(J, wrench)
            kin[q["id"]] = {
                "pos": T[:3, 3],
                "rot": T[:3, :3],
                "jacobian": J,
                "svd": svd,
                "static_torques": torques,
            }

        max_r = _max_reach(chain, joints, joint_order)
        dex_frac, avg_manip = _workspace_monte_carlo(
            chain, joint_order,
            ws_params["random_seed"],
            ws_params["num_samples"],
            ws_params["manipulability_threshold"],
        )
        results[vid] = {
            "kin": kin,
            "max_reach": max_r,
            "dex_frac": dex_frac,
            "avg_manip": avg_manip,
        }

    return results


@pytest.fixture(scope="module")
def agent_results():
    assert os.path.isfile(RESULTS_PATH), f"Output file {RESULTS_PATH} not found"
    with open(RESULTS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Tests: Output structure
# ---------------------------------------------------------------------------

class TestOutputStructure:

    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), "results.json not found"

    def test_top_level_keys(self, agent_results):
        assert "variants" in agent_results, "Missing 'variants' key"
        assert "comparative_summary" in agent_results, "Missing 'comparative_summary' key"

    def test_all_variants_present(self, agent_results):
        for vid in ALL_VARIANTS:
            assert vid in agent_results["variants"], f"Missing variant {vid}"


# ---------------------------------------------------------------------------
# Tests: Validation
# ---------------------------------------------------------------------------

class TestValidation:

    @pytest.mark.parametrize("vid", VALID_VARIANTS)
    def test_valid_variants(self, agent_results, vid):
        v = agent_results["variants"][vid]["validation"]
        assert v["is_valid"] is True, f"{vid} should be valid"

    def test_invalid_variant_c(self, agent_results):
        v = agent_results["variants"]["variant_c"]["validation"]
        assert v["is_valid"] is False, "variant_c should be invalid"

    @pytest.mark.parametrize("vid", VALID_VARIANTS)
    def test_root_link(self, agent_results, vid):
        v = agent_results["variants"][vid]["validation"]
        assert v["root_link"] == "base_link", f"{vid} root_link should be base_link"

    @pytest.mark.parametrize("vid", ALL_VARIANTS)
    def test_link_count(self, agent_results, vid):
        v = agent_results["variants"][vid]["validation"]
        assert v["num_links"] == EXPECTED_COUNTS[vid]["num_links"], \
            f"{vid}: expected {EXPECTED_COUNTS[vid]['num_links']} links, got {v['num_links']}"

    @pytest.mark.parametrize("vid", ALL_VARIANTS)
    def test_joint_count(self, agent_results, vid):
        v = agent_results["variants"][vid]["validation"]
        assert v["num_joints"] == EXPECTED_COUNTS[vid]["num_joints"], \
            f"{vid}: expected {EXPECTED_COUNTS[vid]['num_joints']} joints, got {v['num_joints']}"

    def test_invalid_null_kinematic(self, agent_results):
        assert agent_results["variants"]["variant_c"]["kinematic_analysis"] is None

    def test_invalid_null_workspace(self, agent_results):
        assert agent_results["variants"]["variant_c"]["workspace_analysis"] is None


# ---------------------------------------------------------------------------
# Tests: Forward Kinematics
# ---------------------------------------------------------------------------

QUERY_IDS = ["q1", "q2", "q3", "q4"]
FK_PARAMS = [(v, q) for v in VALID_VARIANTS for q in QUERY_IDS]


class TestForwardKinematics:

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_fk_position(self, agent_results, ref, vid, qid):
        agent_pos = np.array(
            agent_results["variants"][vid]["kinematic_analysis"][qid]["position"]
        )
        ref_pos = ref[vid]["kin"][qid]["pos"]
        np.testing.assert_allclose(
            agent_pos, ref_pos, atol=1e-4,
            err_msg=f"FK position mismatch for {vid}/{qid}",
        )

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_fk_rotation(self, agent_results, ref, vid, qid):
        agent_rot = np.array(
            agent_results["variants"][vid]["kinematic_analysis"][qid]["rotation_matrix"]
        )
        ref_rot = ref[vid]["kin"][qid]["rot"]
        np.testing.assert_allclose(
            agent_rot, ref_rot, atol=1e-3,
            err_msg=f"FK rotation mismatch for {vid}/{qid}",
        )

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_rotation_orthogonal(self, agent_results, vid, qid):
        R = np.array(
            agent_results["variants"][vid]["kinematic_analysis"][qid]["rotation_matrix"]
        )
        np.testing.assert_allclose(
            R @ R.T, np.eye(3), atol=1e-3,
            err_msg=f"R*R^T should be identity for {vid}/{qid}",
        )
        np.testing.assert_allclose(
            np.linalg.det(R), 1.0, atol=1e-3,
            err_msg=f"det(R) should be 1 for {vid}/{qid}",
        )


# ---------------------------------------------------------------------------
# Tests: Jacobian
# ---------------------------------------------------------------------------

class TestJacobian:

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_jacobian_shape(self, agent_results, vid, qid):
        J = np.array(
            agent_results["variants"][vid]["kinematic_analysis"][qid]["jacobian"]
        )
        assert J.shape == (6, 6), f"Jacobian shape should be (6,6) for {vid}/{qid}"

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_jacobian_values(self, agent_results, ref, vid, qid):
        agent_J = np.array(
            agent_results["variants"][vid]["kinematic_analysis"][qid]["jacobian"]
        )
        ref_J = ref[vid]["kin"][qid]["jacobian"]
        np.testing.assert_allclose(
            agent_J, ref_J, atol=1e-2,
            err_msg=f"Jacobian mismatch for {vid}/{qid}",
        )


# ---------------------------------------------------------------------------
# Tests: SVD / Manipulability
# ---------------------------------------------------------------------------

class TestManipulability:

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_manipulability_value(self, agent_results, ref, vid, qid):
        agent_w = agent_results["variants"][vid]["kinematic_analysis"][qid]["manipulability"]
        ref_w = ref[vid]["kin"][qid]["svd"]["manipulability"]
        if ref_w < 1e-6:
            assert abs(agent_w) < 1e-3, \
                f"Manipulability should be ~0 for {vid}/{qid}, got {agent_w}"
        else:
            np.testing.assert_allclose(
                agent_w, ref_w, rtol=0.05,
                err_msg=f"Manipulability mismatch for {vid}/{qid}",
            )

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_singular_values(self, agent_results, ref, vid, qid):
        agent_sv = np.array(
            agent_results["variants"][vid]["kinematic_analysis"][qid]["singular_values"]
        )
        ref_sv = np.array(ref[vid]["kin"][qid]["svd"]["singular_values"])
        assert len(agent_sv) == 6, f"Expected 6 singular values for {vid}/{qid}"
        # Check descending order
        for i in range(5):
            assert agent_sv[i] >= agent_sv[i + 1] - 1e-9, \
                f"Singular values not in descending order for {vid}/{qid}"
        np.testing.assert_allclose(
            agent_sv, ref_sv, atol=1e-3,
            err_msg=f"Singular values mismatch for {vid}/{qid}",
        )

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_condition_number(self, agent_results, ref, vid, qid):
        agent_cond = agent_results["variants"][vid]["kinematic_analysis"][qid]["condition_number"]
        ref_cond = ref[vid]["kin"][qid]["svd"]["condition_number"]
        if ref_cond >= 1e11:
            assert agent_cond >= 1e6, \
                f"Condition number should be very large for {vid}/{qid}, got {agent_cond}"
        else:
            np.testing.assert_allclose(
                agent_cond, ref_cond, rtol=0.15,
                err_msg=f"Condition number mismatch for {vid}/{qid}",
            )

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_singularity_class(self, agent_results, ref, vid, qid):
        agent_cls = agent_results["variants"][vid]["kinematic_analysis"][qid]["singularity_class"]
        ref_cls = ref[vid]["kin"][qid]["svd"]["singularity_class"]
        assert agent_cls == ref_cls, \
            f"Singularity class mismatch for {vid}/{qid}: agent={agent_cls}, ref={ref_cls}"


# ---------------------------------------------------------------------------
# Tests: Static torques
# ---------------------------------------------------------------------------

class TestStaticTorques:

    @pytest.mark.parametrize("vid,qid", FK_PARAMS)
    def test_static_torques(self, agent_results, ref, vid, qid):
        agent_tau = np.array(
            agent_results["variants"][vid]["kinematic_analysis"][qid]["static_torques"]
        )
        ref_tau = np.array(ref[vid]["kin"][qid]["static_torques"])
        assert len(agent_tau) == 6, f"Expected 6 torques for {vid}/{qid}"
        np.testing.assert_allclose(
            agent_tau, ref_tau, atol=5e-2,
            err_msg=f"Static torques mismatch for {vid}/{qid}",
        )


# ---------------------------------------------------------------------------
# Tests: Workspace analysis
# ---------------------------------------------------------------------------

class TestWorkspace:

    @pytest.mark.parametrize("vid", VALID_VARIANTS)
    def test_max_reach(self, agent_results, ref, vid):
        agent_mr = float(
            agent_results["variants"][vid]["workspace_analysis"]["max_reach"]
        )
        ref_mr = ref[vid]["max_reach"]
        assert abs(agent_mr - ref_mr) < 0.02, \
            f"Max reach mismatch for {vid}: agent={agent_mr:.4f}, ref={ref_mr:.4f}"

    @pytest.mark.parametrize("vid", VALID_VARIANTS)
    def test_max_reach_minimum(self, agent_results, vid):
        """Max reach must be at least as large as arm-straight-up config."""
        agent_mr = float(
            agent_results["variants"][vid]["workspace_analysis"]["max_reach"]
        )
        # Conservative lower bound (base + shoulder + links going up)
        assert agent_mr > 0.5, f"Max reach {agent_mr} is suspiciously small for {vid}"

    @pytest.mark.parametrize("vid", VALID_VARIANTS)
    def test_dexterous_fraction(self, agent_results, ref, vid):
        agent_df = float(
            agent_results["variants"][vid]["workspace_analysis"]["dexterous_workspace_fraction"]
        )
        ref_df = ref[vid]["dex_frac"]
        assert abs(agent_df - ref_df) < 0.05, \
            f"Dexterous fraction mismatch for {vid}: agent={agent_df:.4f}, ref={ref_df:.4f}"

    @pytest.mark.parametrize("vid", VALID_VARIANTS)
    def test_average_manipulability(self, agent_results, ref, vid):
        agent_am = float(
            agent_results["variants"][vid]["workspace_analysis"]["average_manipulability"]
        )
        ref_am = ref[vid]["avg_manip"]
        if ref_am < 1e-6:
            assert agent_am < 1e-3, \
                f"Average manipulability should be ~0 for {vid}"
        else:
            np.testing.assert_allclose(
                agent_am, ref_am, rtol=0.2,
                err_msg=f"Average manipulability mismatch for {vid}",
            )


# ---------------------------------------------------------------------------
# Tests: Comparative summary
# ---------------------------------------------------------------------------

class TestComparativeSummary:

    def test_best_max_reach(self, agent_results, ref):
        best_vid = max(VALID_VARIANTS, key=lambda v: ref[v]["max_reach"])
        assert agent_results["comparative_summary"]["best_max_reach"] == best_vid

    def test_best_avg_manipulability(self, agent_results, ref):
        best_vid = max(VALID_VARIANTS, key=lambda v: ref[v]["avg_manip"])
        assert agent_results["comparative_summary"]["best_avg_manipulability"] == best_vid

    def test_best_dexterous_fraction(self, agent_results, ref):
        best_vid = max(VALID_VARIANTS, key=lambda v: ref[v]["dex_frac"])
        assert agent_results["comparative_summary"]["best_dexterous_fraction"] == best_vid


# ---------------------------------------------------------------------------
# Tests: Tree diagrams
# ---------------------------------------------------------------------------

class TestTreeDiagrams:

    @pytest.mark.parametrize("vid", VALID_VARIANTS)
    def test_tree_png_exists(self, vid):
        png_path = f"/app/output/{vid}_tree.png"
        assert os.path.isfile(png_path), \
            f"Tree diagram PNG not found at {png_path}"

    @pytest.mark.parametrize("vid", VALID_VARIANTS)
    def test_tree_png_nonempty(self, vid):
        png_path = f"/app/output/{vid}_tree.png"
        if os.path.isfile(png_path):
            assert os.path.getsize(png_path) > 100, \
                f"Tree diagram PNG at {png_path} is suspiciously small"


# ---------------------------------------------------------------------------
# Sanity checks on the reference implementation
# ---------------------------------------------------------------------------

class TestReferenceSanity:

    def test_variant_a_zero_config_position(self, ref):
        """At zero config, variant_a arm extends horizontally along +X."""
        pos = ref["variant_a"]["kin"]["q1"]["pos"]
        np.testing.assert_allclose(pos, [0.915, 0.0, 0.15], atol=1e-6)

    def test_variant_a_arm_up_position(self, ref):
        """Shoulder lift at -pi/2 makes variant_a arm point straight up."""
        pos = ref["variant_a"]["kin"]["q2"]["pos"]
        np.testing.assert_allclose(pos, [0.0, 0.0, 1.065], atol=1e-6)

    def test_variant_b_reaches_further(self, ref):
        """variant_b should have greater max reach than variant_a."""
        assert ref["variant_b"]["max_reach"] > ref["variant_a"]["max_reach"]
