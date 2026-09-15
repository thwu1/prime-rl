
import json
import math
import yaml
import pytest
import xml.etree.ElementTree as ET


@pytest.fixture(scope="module")
def config():
    with open("/app/nav2_params.yaml", "r") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def robot_spec():
    with open("/app/robot_spec.yaml", "r") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def bt_root():
    tree = ET.parse("/app/nav2_bt.xml")
    return tree.getroot()


@pytest.fixture(scope="module")
def follow_path(config):
    return config["controller_server"]["ros__parameters"]["FollowPath"]


@pytest.fixture(scope="module")
def local_costmap(config):
    return config["local_costmap"]["local_costmap"]["ros__parameters"]


@pytest.fixture(scope="module")
def global_costmap(config):
    return config["global_costmap"]["global_costmap"]["ros__parameters"]


@pytest.fixture(scope="module")
def vel_smoother(config):
    return config["velocity_smoother"]["ros__parameters"]


@pytest.fixture(scope="module")
def collision_mon(config):
    return config["collision_monitor"]["ros__parameters"]


@pytest.fixture(scope="module")
def prediction_dist(follow_path):
    return follow_path["time_steps"] * follow_path["model_dt"] * follow_path["vx_max"]


class TestMotionModel:
    """Verify the MPPI motion model is correctly configured for Ackermann."""

    def test_motion_model_is_ackermann(self, follow_path):
        assert follow_path["motion_model"] == "ackermann", (
            f"motion_model should be 'ackermann', got '{follow_path['motion_model']}'"
        )

    def test_ackermann_plugin(self, follow_path):
        assert "ackermann" in follow_path, "Missing 'ackermann' motion model section"
        assert follow_path["ackermann"]["plugin"] == "mppi::AckermannMotionModel", (
            f"Ackermann plugin incorrect: {follow_path['ackermann'].get('plugin')}"
        )

    def test_min_turning_radius(self, follow_path, robot_spec):
        expected_r = robot_spec["robot"]["kinematics"]["min_turning_radius"]
        actual_r = follow_path["ackermann"]["min_turning_r"]
        assert actual_r == pytest.approx(expected_r, abs=0.01), (
            f"min_turning_r should be {expected_r}, got {actual_r}"
        )


class TestAckermannKinematics:
    """Verify kinematic constraints are correct for a non-holonomic Ackermann platform."""

    def test_no_lateral_velocity(self, follow_path):
        assert follow_path["vy_max"] == pytest.approx(0.0, abs=0.001), (
            f"vy_max must be 0.0 for Ackermann, got {follow_path['vy_max']}"
        )

    def test_no_lateral_acceleration(self, follow_path):
        assert follow_path["ay_max"] == pytest.approx(0.0, abs=0.001), (
            f"ay_max must be 0.0 for Ackermann, got {follow_path['ay_max']}"
        )
        assert follow_path["ay_min"] == pytest.approx(0.0, abs=0.001), (
            f"ay_min must be 0.0 for Ackermann, got {follow_path['ay_min']}"
        )


class TestVelocityLimitsMatchSpec:
    """Verify controller velocity limits match the robot specification."""

    def test_vx_max(self, follow_path, robot_spec):
        expected = robot_spec["robot"]["kinematics"]["max_forward_velocity"]
        assert follow_path["vx_max"] == pytest.approx(expected, abs=0.01)

    def test_vx_min(self, follow_path, robot_spec):
        expected = robot_spec["robot"]["kinematics"]["max_reverse_velocity"]
        assert follow_path["vx_min"] == pytest.approx(expected, abs=0.01)

    def test_wz_max(self, follow_path, robot_spec):
        expected = robot_spec["robot"]["kinematics"]["max_angular_velocity"]
        assert follow_path["wz_max"] == pytest.approx(expected, abs=0.01)


class TestControllerTimingUnchanged:
    """Verify protected parameters were not modified."""

    def test_time_steps(self, follow_path):
        assert follow_path["time_steps"] == 40

    def test_model_dt(self, follow_path):
        assert follow_path["model_dt"] == pytest.approx(0.05, abs=0.001)

    def test_controller_frequency(self, config):
        freq = config["controller_server"]["ros__parameters"]["controller_frequency"]
        assert freq == pytest.approx(20.0, abs=0.1)


class TestLocalCostmapSize:
    """Local costmap must contain the full MPPI prediction horizon at max speed."""

    def test_width_covers_prediction(self, local_costmap, prediction_dist):
        min_width = 2 * prediction_dist
        assert local_costmap["width"] >= min_width, (
            f"Local costmap width {local_costmap['width']} < {min_width} "
            f"(2 * prediction_dist={prediction_dist})"
        )

    def test_height_covers_prediction(self, local_costmap, prediction_dist):
        min_height = 2 * prediction_dist
        assert local_costmap["height"] >= min_height, (
            f"Local costmap height {local_costmap['height']} < {min_height} "
            f"(2 * prediction_dist={prediction_dist})"
        )


class TestLocalCostmapRollingWindow:
    """Local costmap with odom frame must use a rolling window."""

    def test_rolling_window_enabled(self, local_costmap):
        assert local_costmap["rolling_window"] is True, (
            "Local costmap rolling_window must be true for robot-centric view"
        )


class TestInflationRadius:
    """Inflation radius must exceed the robot's circumscribed radius."""

    def test_local_inflation(self, local_costmap, robot_spec):
        circumscribed_r = robot_spec["robot"]["circumscribed_radius"]
        actual = local_costmap["inflation_layer"]["inflation_radius"]
        assert actual >= circumscribed_r, (
            f"Local inflation_radius {actual} < circumscribed_radius {circumscribed_r}"
        )

    def test_global_inflation(self, global_costmap, robot_spec):
        circumscribed_r = robot_spec["robot"]["circumscribed_radius"]
        actual = global_costmap["inflation_layer"]["inflation_radius"]
        assert actual >= circumscribed_r, (
            f"Global inflation_radius {actual} < circumscribed_radius {circumscribed_r}"
        )


class TestVelocitySmootherConsistency:
    """Velocity smoother limits must match the MPPI controller limits."""

    def test_max_vx(self, vel_smoother, follow_path):
        assert vel_smoother["max_velocity"][0] == pytest.approx(
            follow_path["vx_max"], abs=0.01
        ), "velocity_smoother max_velocity[0] must match controller vx_max"

    def test_max_wz(self, vel_smoother, follow_path):
        assert vel_smoother["max_velocity"][2] == pytest.approx(
            follow_path["wz_max"], abs=0.01
        ), "velocity_smoother max_velocity[2] must match controller wz_max"

    def test_min_vx(self, vel_smoother, follow_path):
        assert vel_smoother["min_velocity"][0] == pytest.approx(
            follow_path["vx_min"], abs=0.01
        ), "velocity_smoother min_velocity[0] must match controller vx_min"

    def test_min_wz(self, vel_smoother, follow_path):
        assert vel_smoother["min_velocity"][2] == pytest.approx(
            -follow_path["wz_max"], abs=0.01
        ), "velocity_smoother min_velocity[2] must match -wz_max"


class TestCostCriticThresholds:
    """CostCritic near_collision_cost must be within valid OccupancyGrid range."""

    def test_near_collision_cost_valid(self, follow_path):
        ncc = follow_path["CostCritic"]["near_collision_cost"]
        assert 1 <= ncc <= 253, (
            f"near_collision_cost {ncc} outside valid OccupancyGrid range [1, 253]"
        )


class TestCriticHandoffThresholds:
    """GoalCritic and PathFollowCritic thresholds must enable clean handoff."""

    def test_thresholds_match_each_other(self, follow_path):
        goal_t = follow_path["GoalCritic"]["threshold_to_consider"]
        path_t = follow_path["PathFollowCritic"]["threshold_to_consider"]
        assert goal_t == pytest.approx(path_t, abs=0.01), (
            f"GoalCritic threshold ({goal_t}) != PathFollowCritic threshold ({path_t})"
        )

    def test_thresholds_match_prediction_horizon(self, follow_path, prediction_dist):
        goal_t = follow_path["GoalCritic"]["threshold_to_consider"]
        assert abs(goal_t - prediction_dist) <= 0.3, (
            f"GoalCritic threshold_to_consider ({goal_t}) should be near "
            f"prediction_dist ({prediction_dist}) for clean handoff"
        )


class TestCollisionMonitorTopology:
    """Collision monitor must receive velocity from the velocity smoother output."""

    def test_cmd_vel_in_topic(self, collision_mon):
        assert collision_mon["cmd_vel_in_topic"] == "cmd_vel_smoothed", (
            f"cmd_vel_in_topic should be 'cmd_vel_smoothed', "
            f"got '{collision_mon['cmd_vel_in_topic']}'"
        )


class TestBehaviorTree:
    """Verify behavior tree contains only Ackermann-compatible recovery actions."""

    def test_no_spin_recovery(self, bt_root):
        spin_nodes = list(bt_root.iter("Spin"))
        assert len(spin_nodes) == 0, (
            f"BT contains {len(spin_nodes)} Spin node(s) — "
            "Ackermann vehicles cannot rotate in place"
        )

    def test_has_backup_recovery(self, bt_root):
        backup_nodes = list(bt_root.iter("BackUp"))
        assert len(backup_nodes) >= 1, (
            "BT must include at least one BackUp recovery node for Ackermann platform"
        )

    def test_bt_structure_valid(self, bt_root):
        assert bt_root.tag == "root", "BT root element must be 'root'"
        bt = bt_root.find(".//BehaviorTree")
        assert bt is not None, "BT must contain a BehaviorTree element"
        recovery = bt_root.find(".//RecoveryNode")
        assert recovery is not None, "BT must contain a RecoveryNode"


class TestAuditReport:
    """Audit report must document discovered issues with physical justifications."""

    @pytest.fixture(scope="class")
    def audit(self):
        with open("/app/audit.json", "r") as f:
            return json.load(f)

    def test_is_valid_json_array(self, audit):
        assert isinstance(audit, list), "audit.json must be a JSON array"

    def test_minimum_issues_documented(self, audit):
        assert len(audit) >= 10, (
            f"Audit must document at least 10 configuration issues, found {len(audit)}"
        )

    def test_entries_have_required_fields(self, audit):
        required = {"file", "path", "old", "new", "reason"}
        for i, entry in enumerate(audit):
            missing = required - set(entry.keys())
            assert not missing, f"Audit entry {i} missing fields: {missing}"

    def test_old_and_new_differ(self, audit):
        for i, entry in enumerate(audit):
            assert str(entry["old"]) != str(entry["new"]), (
                f"Audit entry {i} has identical old and new values: {entry['old']}"
            )

    def test_reasons_are_substantive(self, audit):
        for i, entry in enumerate(audit):
            words = entry["reason"].split()
            assert len(words) >= 5, (
                f"Audit entry {i} reason too brief ({len(words)} words): "
                f"'{entry['reason']}'"
            )

    def test_covers_multiple_files(self, audit):
        files = set(entry["file"] for entry in audit)
        assert len(files) >= 2, (
            f"Audit should cover changes in at least 2 files, found: {files}"
        )
