
"""
Verification tests for robotic workcell capability assessment.

Independently computes all reference quantities using PyBullet and compares
against the agent's results in /app/results.json.
"""

import pytest
import json
import os
import numpy as np
import pybullet as p
import pybullet_data


# ---------------------------------------------------------------------------
# Load config and agent results
# ---------------------------------------------------------------------------

with open('/app/workcell_config.json') as _f:
    CONFIG = json.load(_f)

RESULTS_FILE = '/app/results.json'

if os.path.exists(RESULTS_FILE):
    with open(RESULTS_FILE) as _f:
        RESULTS = json.load(_f)
else:
    RESULTS = None

# ---------------------------------------------------------------------------
# PyBullet setup and reference computation
# ---------------------------------------------------------------------------

_physics_client = p.connect(p.DIRECT)
p.setAdditionalSearchPath(pybullet_data.getDataPath())
p.setGravity(*CONFIG['robot']['gravity'])
ROBOT_ID = p.loadURDF(
    CONFIG['robot']['urdf'],
    CONFIG['robot']['base_position'],
    useFixedBase=True
)
EE_LINK = CONFIG['robot']['end_effector_link_index']
NUM_JOINTS = p.getNumJoints(ROBOT_ID)
TOOL = CONFIG['tool']
THRESHOLDS = CONFIG['classification_thresholds']
TORQUE_LIMITS = np.array(CONFIG['robot']['joint_torque_limits'], dtype=float)
LJ_THRESHOLD = THRESHOLDS.get('limiting_joint_utilization', 0.995)

STATION_IDS = sorted(CONFIG['stations'].keys())


def _compute_max_wrench_scale(tau_static, tau_task, tau_limits):
    """
    Find max s >= 0 such that |tau_static[i] + s * tau_task[i]| <= tau_limits[i]
    for all joints i.
    """
    n = len(tau_static)
    s_min_overall = 0.0
    s_max_overall = float('inf')

    for i in range(n):
        ts = float(tau_static[i])
        tt = float(tau_task[i])
        tl = float(tau_limits[i])

        if abs(tt) < 1e-12:
            if abs(ts) > tl + 1e-10:
                return 0.0
            continue

        a = (tl - ts) / tt
        b = (-tl - ts) / tt
        lo_i = min(a, b)
        hi_i = max(a, b)

        s_min_overall = max(s_min_overall, lo_i)
        s_max_overall = min(s_max_overall, hi_i)

    if s_max_overall < s_min_overall - 1e-10:
        return 0.0

    return max(0.0, s_max_overall)


def _compute_reference(station_id):
    """Compute all reference quantities for a given station."""
    station = CONFIG['stations'][station_id]
    q = station['joint_configuration']
    wrench = np.array(station['required_wrench'], dtype=float)
    n = len(q)
    tip_pos = TOOL['local_position']
    payload_mass = TOOL['mass_kg']
    gravity = np.array(CONFIG['robot']['gravity'], dtype=float)

    # Set joint states
    for i in range(n):
        p.resetJointState(ROBOT_ID, i, q[i])

    zero_vec = [0.0] * n

    # Jacobian at tool tip
    jac_lin, jac_ang = p.calculateJacobian(
        ROBOT_ID, EE_LINK, tip_pos,
        list(q), zero_vec, zero_vec
    )
    J_lin = np.array(jac_lin)
    J_ang = np.array(jac_ang)
    J = np.vstack([J_lin, J_ang])  # 6x7

    # Gravity compensation torques (bare robot)
    tau_gravity = np.array(p.calculateInverseDynamics(
        ROBOT_ID, list(q), zero_vec, zero_vec
    ))

    # Payload gravitational torques at tool tip
    F_payload = payload_mass * gravity  # [0, 0, -m*g]
    tau_payload = J_lin.T @ F_payload

    # Total static torques
    tau_static = tau_gravity + tau_payload

    # Task wrench torques
    tau_task = J.T @ wrench

    # Max wrench scale
    mws = _compute_max_wrench_scale(tau_static, tau_task, TORQUE_LIMITS)

    # Limiting joints at max scale
    tau_at_max = tau_static + mws * tau_task
    utilization_at_max = np.abs(tau_at_max) / TORQUE_LIMITS
    limiting = sorted([i for i in range(n) if float(utilization_at_max[i]) > LJ_THRESHOLD])

    # Torque utilization at s=1
    tau_at_one = tau_static + tau_task
    torque_util = (np.abs(tau_at_one) / TORQUE_LIMITS).tolist()

    # Kinematic analysis
    _, sigma, _ = np.linalg.svd(J)
    cond = float(sigma[0] / sigma[-1]) if sigma[-1] > 1e-15 else float('inf')
    is_singular = cond > THRESHOLDS['singularity_condition_number']

    JJt = J @ J.T
    manip = float(np.sqrt(max(0.0, np.linalg.det(JJt))))

    # Classification
    if mws >= THRESHOLDS['feasible_min_scale']:
        fclass = "FEASIBLE"
    elif mws >= THRESHOLDS['marginal_min_scale']:
        fclass = "MARGINAL"
    else:
        fclass = "INFEASIBLE"

    return {
        'station_id': station_id,
        'feasibility_class': fclass,
        'max_wrench_scale': mws,
        'limiting_joints': limiting,
        'condition_number': cond,
        'is_near_singular': is_singular,
        'manipulability': manip,
        'torque_utilization': torque_util,
    }


# Pre-compute references
REFS = {sid: _compute_reference(sid) for sid in STATION_IDS}

# Pre-compute reference ranking
_ranked = sorted(REFS.values(), key=lambda x: x['max_wrench_scale'], reverse=True)
REF_RANKING = [r['station_id'] for r in _ranked]
REF_SUMMARY = {
    'feasible_count': sum(1 for r in REFS.values() if r['feasibility_class'] == 'FEASIBLE'),
    'marginal_count': sum(1 for r in REFS.values() if r['feasibility_class'] == 'MARGINAL'),
    'infeasible_count': sum(1 for r in REFS.values() if r['feasibility_class'] == 'INFEASIBLE'),
}


def _get_agent_station(station_id):
    """Look up the agent's result for a given station."""
    if RESULTS is None:
        return None
    for s in RESULTS.get('stations', []):
        if s.get('station_id') == station_id:
            return s
    return None


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

class TestResultsStructure:

    def test_file_exists(self):
        assert os.path.exists(RESULTS_FILE), "results.json not found at /app/results.json"

    def test_valid_json(self):
        assert RESULTS is not None, "Could not parse results.json"

    def test_has_stations_key(self):
        assert 'stations' in RESULTS, "Missing 'stations' key in results"

    def test_has_summary_key(self):
        assert 'summary' in RESULTS, "Missing 'summary' key in results"

    def test_six_stations(self):
        assert len(RESULTS['stations']) == 6, \
            f"Expected 6 stations, got {len(RESULTS['stations'])}"

    def test_all_station_ids_present(self):
        ids = {s.get('station_id') for s in RESULTS['stations']}
        expected = set(STATION_IDS)
        assert ids == expected, f"Expected station IDs {expected}, got {ids}"

    @pytest.mark.parametrize("field", [
        "station_id", "feasibility_class", "max_wrench_scale",
        "limiting_joints", "condition_number", "is_near_singular",
        "manipulability", "torque_utilization"
    ])
    def test_required_station_fields(self, field):
        for s in RESULTS['stations']:
            assert field in s, \
                f"Missing field '{field}' in station {s.get('station_id')}"

    def test_summary_fields(self):
        summary = RESULTS['summary']
        for field in ['feasible_count', 'marginal_count', 'infeasible_count', 'station_ranking']:
            assert field in summary, f"Missing summary field '{field}'"

    def test_torque_utilization_length(self):
        for s in RESULTS['stations']:
            assert len(s['torque_utilization']) == 7, \
                f"torque_utilization length != 7 for {s['station_id']}"


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------

class TestClassification:

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_feasibility_class(self, station_id):
        agent = _get_agent_station(station_id)
        ref = REFS[station_id]
        assert agent is not None, f"No result found for {station_id}"
        assert agent['feasibility_class'] == ref['feasibility_class'], \
            f"{station_id}: expected {ref['feasibility_class']}, got {agent['feasibility_class']} " \
            f"(ref max_wrench_scale={ref['max_wrench_scale']:.4f})"

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_near_singular_flag(self, station_id):
        agent = _get_agent_station(station_id)
        ref = REFS[station_id]
        assert agent is not None, f"No result found for {station_id}"
        assert agent['is_near_singular'] == ref['is_near_singular'], \
            f"{station_id}: expected is_near_singular={ref['is_near_singular']} " \
            f"(cond={ref['condition_number']:.2f}, threshold={THRESHOLDS['singularity_condition_number']})"


# ---------------------------------------------------------------------------
# Numerical accuracy tests
# ---------------------------------------------------------------------------

class TestMaxWrenchScale:

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_max_wrench_scale(self, station_id):
        agent = _get_agent_station(station_id)
        ref = REFS[station_id]
        assert agent is not None, f"No result found for {station_id}"
        if ref['max_wrench_scale'] < 1e-6:
            assert agent['max_wrench_scale'] < 0.01, \
                f"{station_id}: max_wrench_scale should be near zero"
        elif ref['max_wrench_scale'] > 1e5:
            assert agent['max_wrench_scale'] > 1e4, \
                f"{station_id}: max_wrench_scale should be very large"
        else:
            np.testing.assert_allclose(
                agent['max_wrench_scale'],
                ref['max_wrench_scale'],
                rtol=0.02,
                err_msg=f"max_wrench_scale mismatch for {station_id}"
            )


class TestConditionNumber:

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_condition_number(self, station_id):
        agent = _get_agent_station(station_id)
        ref = REFS[station_id]
        assert agent is not None, f"No result found for {station_id}"
        if np.isinf(ref['condition_number']):
            assert agent['condition_number'] > 1e8, \
                f"{station_id}: condition number should be extremely large"
        else:
            np.testing.assert_allclose(
                agent['condition_number'],
                ref['condition_number'],
                rtol=0.05,
                err_msg=f"condition_number mismatch for {station_id}"
            )


class TestManipulability:

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_manipulability(self, station_id):
        agent = _get_agent_station(station_id)
        ref = REFS[station_id]
        assert agent is not None, f"No result found for {station_id}"
        if ref['manipulability'] < 1e-10:
            assert agent['manipulability'] < 1e-6, \
                f"{station_id}: manipulability should be near zero"
        else:
            np.testing.assert_allclose(
                agent['manipulability'],
                ref['manipulability'],
                rtol=0.05,
                err_msg=f"manipulability mismatch for {station_id}"
            )


class TestTorqueUtilization:

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_torque_utilization(self, station_id):
        agent = _get_agent_station(station_id)
        ref = REFS[station_id]
        assert agent is not None, f"No result found for {station_id}"
        np.testing.assert_allclose(
            np.array(agent['torque_utilization']),
            np.array(ref['torque_utilization']),
            atol=0.02,
            err_msg=f"torque_utilization mismatch for {station_id}"
        )


class TestLimitingJoints:

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_limiting_joints(self, station_id):
        agent = _get_agent_station(station_id)
        ref = REFS[station_id]
        assert agent is not None, f"No result found for {station_id}"
        assert set(agent['limiting_joints']) == set(ref['limiting_joints']), \
            f"{station_id}: limiting_joints mismatch - expected {ref['limiting_joints']}, " \
            f"got {agent['limiting_joints']}"


# ---------------------------------------------------------------------------
# Summary and ranking tests
# ---------------------------------------------------------------------------

class TestSummary:

    def test_feasible_count(self):
        assert RESULTS['summary']['feasible_count'] == REF_SUMMARY['feasible_count'], \
            f"feasible_count: expected {REF_SUMMARY['feasible_count']}, " \
            f"got {RESULTS['summary']['feasible_count']}"

    def test_marginal_count(self):
        assert RESULTS['summary']['marginal_count'] == REF_SUMMARY['marginal_count'], \
            f"marginal_count: expected {REF_SUMMARY['marginal_count']}, " \
            f"got {RESULTS['summary']['marginal_count']}"

    def test_infeasible_count(self):
        assert RESULTS['summary']['infeasible_count'] == REF_SUMMARY['infeasible_count'], \
            f"infeasible_count: expected {REF_SUMMARY['infeasible_count']}, " \
            f"got {RESULTS['summary']['infeasible_count']}"

    def test_counts_add_up(self):
        s = RESULTS['summary']
        total = s['feasible_count'] + s['marginal_count'] + s['infeasible_count']
        assert total == 6, f"Classification counts sum to {total}, expected 6"

    def test_station_ranking(self):
        assert RESULTS['summary']['station_ranking'] == REF_RANKING, \
            f"station_ranking mismatch: expected {REF_RANKING}, " \
            f"got {RESULTS['summary']['station_ranking']}"

    def test_ranking_length(self):
        assert len(RESULTS['summary']['station_ranking']) == 6, \
            f"station_ranking should have 6 entries"

    def test_ranking_contains_all_stations(self):
        assert set(RESULTS['summary']['station_ranking']) == set(STATION_IDS), \
            "station_ranking should contain all station IDs"


# ---------------------------------------------------------------------------
# Consistency tests
# ---------------------------------------------------------------------------

class TestConsistency:

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_class_consistent_with_scale(self, station_id):
        """Verify classification is consistent with max_wrench_scale and thresholds."""
        agent = _get_agent_station(station_id)
        assert agent is not None
        mws = agent['max_wrench_scale']
        fclass = agent['feasibility_class']

        if mws >= THRESHOLDS['feasible_min_scale']:
            assert fclass == "FEASIBLE", \
                f"{station_id}: scale={mws:.4f} >= {THRESHOLDS['feasible_min_scale']} but class={fclass}"
        elif mws >= THRESHOLDS['marginal_min_scale']:
            assert fclass == "MARGINAL", \
                f"{station_id}: scale={mws:.4f} in marginal range but class={fclass}"
        else:
            assert fclass == "INFEASIBLE", \
                f"{station_id}: scale={mws:.4f} < {THRESHOLDS['marginal_min_scale']} but class={fclass}"

    @pytest.mark.parametrize("station_id", STATION_IDS)
    def test_singular_consistent_with_condition(self, station_id):
        """Verify singularity flag is consistent with condition number."""
        agent = _get_agent_station(station_id)
        assert agent is not None
        expected = agent['condition_number'] > THRESHOLDS['singularity_condition_number']
        assert agent['is_near_singular'] == expected, \
            f"{station_id}: cond={agent['condition_number']:.2f}, " \
            f"threshold={THRESHOLDS['singularity_condition_number']}, " \
            f"but is_near_singular={agent['is_near_singular']}"

    def test_ranking_monotonic(self):
        """Verify ranking is consistent with max_wrench_scale values."""
        ranking = RESULTS['summary']['station_ranking']
        scales = []
        for sid in ranking:
            agent = _get_agent_station(sid)
            scales.append(agent['max_wrench_scale'])
        for i in range(len(scales) - 1):
            assert scales[i] >= scales[i + 1] - 1e-6, \
                f"Ranking not monotonic: {ranking[i]}={scales[i]:.4f} < " \
                f"{ranking[i+1]}={scales[i+1]:.4f}"
