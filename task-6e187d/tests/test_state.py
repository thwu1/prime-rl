
import json
import os
import pytest
import yaml


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def get_nested(d, *keys, default=None):
    """Safely navigate a nested dict."""
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k, default)
        if current is default:
            return default
    return current


# ---------- helpers for navigating Nav2 YAML structure ----------

def get_controller_params(cfg):
    return get_nested(cfg, "controller_server", "ros__parameters", default={})


def get_follow_path(cfg):
    cp = get_controller_params(cfg)
    return cp.get("FollowPath", {})


def get_local_costmap_params(cfg):
    return get_nested(cfg, "local_costmap", "local_costmap", "ros__parameters", default={})


def get_global_costmap_params(cfg):
    return get_nested(cfg, "global_costmap", "global_costmap", "ros__parameters", default={})


def get_velocity_smoother(cfg):
    return get_nested(cfg, "velocity_smoother", "ros__parameters", default={})


# ========== Diagnosis Report Tests ==========

class TestDiagnosisReport:
    """Verify the diagnosis report identifies all real configuration issues
    and separates them from environmental observations."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        report_path = "/app/diagnosis_report.json"
        assert os.path.exists(report_path), "diagnosis_report.json not found at /app/diagnosis_report.json"
        self.report = load_json(report_path)
        assert "config_issues" in self.report, "diagnosis_report.json must have a 'config_issues' key"
        self.issues = self.report["config_issues"]
        for issue in self.issues:
            assert "id" in issue, "Each config issue must have an 'id' field"
            assert "severity" in issue, "Each config issue must have a 'severity' field"
            assert "description" in issue, "Each config issue must have a 'description' field"

    def _issue_covered(self, keywords_groups):
        """Check if at least one group of keywords is fully present in any single issue."""
        for issue in self.issues:
            text = (issue["id"] + " " + issue["description"]).lower()
            for kw_group in keywords_groups:
                if all(kw in text for kw in kw_group):
                    return True
        return False

    def test_minimum_issue_count(self):
        assert len(self.issues) >= 8, (
            f"Expected at least 8 configuration issues, found {len(self.issues)}"
        )

    def test_issues_have_evidence(self):
        """Each config issue should cite supporting evidence."""
        for issue in self.issues:
            assert "evidence" in issue, (
                f"Issue '{issue['id']}' must have an 'evidence' field with supporting data"
            )
            assert isinstance(issue["evidence"], list), (
                f"Issue '{issue['id']}' evidence must be an array"
            )
            assert len(issue["evidence"]) > 0, (
                f"Issue '{issue['id']}' evidence array must not be empty"
            )

    def test_has_environmental_observations(self):
        """Must separately catalog non-configuration observations from logs."""
        assert "environmental" in self.report, (
            "diagnosis_report.json must have an 'environmental' key for non-config observations"
        )
        env = self.report["environmental"]
        assert isinstance(env, list), "'environmental' must be an array"
        assert len(env) >= 3, (
            f"Expected at least 3 environmental observations (sensor noise, battery, "
            f"network, etc.), found {len(env)}"
        )
        for obs in env:
            assert "id" in obs, "Each environmental observation must have an 'id'"
            assert "description" in obs, "Each environmental observation must have a 'description'"

    def test_no_environmental_in_config_issues(self):
        """Environmental observations must not be classified as config issues."""
        non_config_keywords = ["battery", "wifi", "rssi", "cpu_temp", "temperature",
                               "encoder", "lidar_health", "lidar_self"]
        for issue in self.issues:
            issue_id = issue["id"].lower()
            for kw in non_config_keywords:
                assert kw not in issue_id, (
                    f"Environmental observation '{kw}' incorrectly classified as "
                    f"config issue (id='{issue['id']}')"
                )

    def test_detects_prediction_horizon_costmap(self):
        assert self._issue_covered([
            ["prediction", "costmap"],
            ["time_step", "costmap"],
            ["horizon", "costmap"],
            ["prediction", "exceed"],
            ["prediction", "width"],
            ["rollout", "costmap"],
            ["trajectory", "costmap", "beyond"],
        ]), "Must detect prediction horizon exceeds costmap coverage"

    def test_detects_wrong_motion_model(self):
        assert self._issue_covered([
            ["motion_model", "omni"],
            ["motion_model", "diff"],
            ["motion", "model", "omni"],
            ["omni", "differential"],
            ["motion", "drive"],
            ["lateral", "kinematic"],
            ["motion", "incompatible"],
        ]), "Must detect wrong motion model for differential drive robot"

    def test_detects_velocity_smoother_clipping(self):
        assert self._issue_covered([
            ["velocity", "smoother"],
            ["smoother", "clip"],
            ["smoother", "limit"],
            ["max_velocity", "smoother"],
            ["velocity", "mismatch"],
            ["linear", "clip"],
        ]), "Must detect velocity smoother clipping controller output"

    def test_detects_raytrace_range_issue(self):
        assert self._issue_covered([
            ["raytrace", "obstacle"],
            ["raytrace", "range"],
            ["ray", "trace"],
            ["raytrace_max", "obstacle_max"],
            ["clearing", "range"],
            ["ghost", "obstacle"],
            ["stale", "obstacle"],
        ]), "Must detect raytrace range less than obstacle range"

    def test_detects_inflation_radius_mismatch(self):
        assert self._issue_covered([
            ["inflation", "mismatch"],
            ["inflation", "inconsist"],
            ["inflation_radius", "local"],
            ["inflation_radius", "global"],
            ["inflation", "differ"],
            ["inflation", "parity"],
        ]), "Must detect inflation radius mismatch between costmaps"

    def test_detects_robot_radius_inconsistency(self):
        assert self._issue_covered([
            ["robot_radius", "inconsist"],
            ["robot_radius", "mismatch"],
            ["robot_radius", "differ"],
            ["robot_radius", "local"],
            ["robot", "radius", "0.22"],
            ["robot", "radius", "0.30"],
            ["robot", "radius", "0.3"],
        ]), "Must detect robot_radius inconsistency between costmaps"

    def test_detects_critic_threshold_mismatch(self):
        assert self._issue_covered([
            ["threshold", "pathfollow"],
            ["threshold", "goal"],
            ["pathfollowcritic", "goalcritic"],
            ["path_follow", "goal"],
            ["threshold_to_consider", "mismatch"],
            ["threshold", "handoff"],
            ["critic", "threshold"],
            ["critic", "conflict"],
            ["oscillat", "goal"],
        ]), "Must detect PathFollowCritic/GoalCritic threshold mismatch"

    def test_detects_model_dt_issue(self):
        assert self._issue_covered([
            ["model_dt", "frequency"],
            ["model_dt", "control"],
            ["model_dt", "period"],
            ["model_dt", "exceed"],
            ["model_dt", "large"],
            ["dt", "controller_frequency"],
            ["timestep", "coarser"],
            ["model_dt", "resolution"],
        ]), "Must detect model_dt exceeds control period"

    def test_detects_obstacle_layer_missing(self):
        assert self._issue_covered([
            ["obstacle_layer", "missing"],
            ["obstacle_layer", "plugin"],
            ["obstacle", "plugin", "list"],
            ["obstacle", "not", "plugin"],
            ["obstacle_layer", "global"],
            ["dynamic", "obstacle", "global"],
        ]), "Must detect obstacle_layer missing from global costmap plugins"

    def test_detects_acceleration_mismatch(self):
        assert self._issue_covered([
            ["accel", "mismatch"],
            ["accel", "smoother"],
            ["acceleration", "mismatch"],
            ["acceleration", "smoother"],
            ["max_accel", "mppi"],
            ["accel", "inconsist"],
            ["accel", "clip"],
            ["accel", "limit"],
            ["decel", "mismatch"],
        ]), "Must detect acceleration limits mismatch between smoother and controller"


# ========== Fixed Configuration Tests ==========

class TestFixedConfig:
    """Verify the fixed YAML satisfies all mathematical constraints."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        fixed_path = "/app/nav2_params_fixed.yaml"
        assert os.path.exists(fixed_path), "nav2_params_fixed.yaml not found"
        self.cfg = load_yaml(fixed_path)
        assert self.cfg is not None, "Fixed YAML is empty or invalid"

        spec_path = "/app/robot_spec.json"
        self.spec = load_json(spec_path)

        self.fp = get_follow_path(self.cfg)
        self.cp = get_controller_params(self.cfg)
        self.lc = get_local_costmap_params(self.cfg)
        self.gc = get_global_costmap_params(self.cfg)
        self.vs = get_velocity_smoother(self.cfg)

    def test_prediction_fits_costmap(self):
        time_steps = self.fp.get("time_steps", 56)
        model_dt = self.fp.get("model_dt", 0.05)
        vx_max = self.fp.get("vx_max", 0.5)
        width = self.lc.get("width", 3)
        prediction_distance = time_steps * model_dt * vx_max
        costmap_radius = width / 2.0
        assert prediction_distance <= costmap_radius + 0.01, (
            f"Prediction distance {prediction_distance:.2f}m exceeds "
            f"costmap radius {costmap_radius:.2f}m"
        )

    def test_correct_motion_model(self):
        mm = self.fp.get("motion_model", "").lower()
        assert "diff" in mm, (
            f"Motion model must be differential drive, got '{mm}'"
        )

    def test_velocity_smoother_does_not_clip_linear(self):
        vs_max = self.vs.get("max_velocity", [0, 0, 0])
        vx_max = self.fp.get("vx_max", 0.5)
        assert vs_max[0] >= vx_max - 0.01, (
            f"Velocity smoother max_velocity[0]={vs_max[0]} clips "
            f"MPPI vx_max={vx_max}"
        )

    def test_velocity_smoother_does_not_clip_angular(self):
        vs_max = self.vs.get("max_velocity", [0, 0, 0])
        wz_max = self.fp.get("wz_max", 1.9)
        assert vs_max[2] >= wz_max - 0.01, (
            f"Velocity smoother max_velocity[2]={vs_max[2]} clips "
            f"MPPI wz_max={wz_max}"
        )

    def test_raytrace_ge_obstacle_range(self):
        voxel = self.lc.get("voxel_layer", {})
        scan = voxel.get("scan", {})
        raytrace = scan.get("raytrace_max_range", 3.0)
        obstacle = scan.get("obstacle_max_range", 2.5)
        assert raytrace >= obstacle - 0.01, (
            f"raytrace_max_range={raytrace} < obstacle_max_range={obstacle}"
        )

    def test_inflation_radius_parity(self):
        local_infl = get_nested(self.lc, "inflation_layer", "inflation_radius", default=0.55)
        global_infl = get_nested(self.gc, "inflation_layer", "inflation_radius", default=0.55)
        assert abs(local_infl - global_infl) <= 0.15, (
            f"Inflation radius mismatch: local={local_infl}, global={global_infl}"
        )

    def test_robot_radius_consistency(self):
        local_rr = self.lc.get("robot_radius", 0.22)
        global_rr = self.gc.get("robot_radius", 0.22)
        assert abs(local_rr - global_rr) < 0.01, (
            f"Robot radius mismatch: local={local_rr}, global={global_rr}"
        )

    def test_robot_radius_matches_spec(self):
        spec_radius = self.spec.get("robot_radius_m", 0.22)
        local_rr = self.lc.get("robot_radius", 0)
        global_rr = self.gc.get("robot_radius", 0)
        assert abs(local_rr - spec_radius) < 0.01, (
            f"Local robot_radius={local_rr} doesn't match spec={spec_radius}"
        )
        assert abs(global_rr - spec_radius) < 0.01, (
            f"Global robot_radius={global_rr} doesn't match spec={spec_radius}"
        )

    def test_critic_thresholds_match(self):
        pf_thresh = get_nested(self.fp, "PathFollowCritic", "threshold_to_consider", default=1.4)
        gc_thresh = get_nested(self.fp, "GoalCritic", "threshold_to_consider", default=1.4)
        assert abs(pf_thresh - gc_thresh) <= 0.5, (
            f"PathFollowCritic threshold={pf_thresh} vs GoalCritic threshold={gc_thresh} "
            f"differ by more than 0.5 — prevents clean handoff"
        )

    def test_model_dt_within_control_period(self):
        model_dt = self.fp.get("model_dt", 0.05)
        ctrl_freq = self.cp.get("controller_frequency", 20.0)
        control_period = 1.0 / ctrl_freq
        assert model_dt <= control_period + 0.001, (
            f"model_dt={model_dt} exceeds control period "
            f"1/{ctrl_freq}={control_period:.4f}"
        )

    def test_obstacle_layer_in_global_plugins(self):
        plugins = self.gc.get("plugins", [])
        has_obstacle = any("obstacle" in p.lower() for p in plugins)
        has_voxel = any("voxel" in p.lower() for p in plugins)
        assert has_obstacle or has_voxel, (
            f"Global costmap plugins {plugins} must include an obstacle "
            f"detection layer (obstacle_layer or voxel_layer)"
        )

    def test_accel_smoother_matches_controller(self):
        vs_accel = self.vs.get("max_accel", [3.0, 0.0, 3.5])
        ax_max = self.fp.get("ax_max", 3.0)
        az_max = self.fp.get("az_max", 3.5)
        assert vs_accel[0] >= ax_max * 0.7, (
            f"Velocity smoother max_accel[0]={vs_accel[0]} much lower than "
            f"MPPI ax_max={ax_max}"
        )
        assert vs_accel[2] >= az_max * 0.7, (
            f"Velocity smoother max_accel[2]={vs_accel[2]} much lower than "
            f"MPPI az_max={az_max}"
        )

    def test_fixed_yaml_has_all_sections(self):
        required_sections = [
            "controller_server",
            "local_costmap",
            "global_costmap",
            "velocity_smoother",
            "planner_server",
        ]
        for section in required_sections:
            assert section in self.cfg, f"Missing section: {section}"

    def test_vx_max_matches_spec(self):
        spec_vx = self.spec.get("max_forward_velocity_ms", 0.5)
        vx_max = self.fp.get("vx_max", 0)
        assert abs(vx_max - spec_vx) < 0.1, (
            f"MPPI vx_max={vx_max} doesn't match spec={spec_vx}"
        )


# ========== Parameter Justification Tests ==========

class TestParameterJustification:
    """Verify the parameter justification report is complete and substantive."""

    @pytest.fixture(autouse=True)
    def load_justification(self):
        path = "/app/parameter_justification.json"
        assert os.path.exists(path), "parameter_justification.json not found at /app/"
        self.justification = load_json(path)
        assert "changes" in self.justification, "Must have a 'changes' key"
        self.changes = self.justification["changes"]

    def test_minimum_changes_documented(self):
        assert len(self.changes) >= 8, (
            f"Expected at least 8 documented parameter changes, found {len(self.changes)}"
        )

    def test_changes_have_required_fields(self):
        for i, change in enumerate(self.changes):
            assert "parameter" in change, f"Change {i} missing 'parameter' field"
            assert "old_value" in change, f"Change {i} missing 'old_value' field"
            assert "new_value" in change, f"Change {i} missing 'new_value' field"
            assert "rationale" in change, f"Change {i} missing 'rationale' field"
            assert len(str(change["rationale"])) >= 15, (
                f"Change {i} rationale too short — must explain reasoning"
            )

    def test_covers_motion_model_change(self):
        covered = any(
            "motion_model" in str(c.get("parameter", "")).lower()
            for c in self.changes
        )
        assert covered, "Must document and justify motion_model change"

    def test_covers_velocity_limit_changes(self):
        covered = any(
            any(kw in str(c.get("parameter", "")).lower()
                for kw in ["max_velocity", "velocity", "vx_max", "wz_max"])
            for c in self.changes
        )
        assert covered, "Must document and justify velocity limit changes"

    def test_covers_timing_parameter_changes(self):
        covered = any(
            any(kw in str(c.get("parameter", "")).lower()
                for kw in ["model_dt", "time_steps", "timestep"])
            for c in self.changes
        )
        assert covered, "Must document and justify timing parameter changes (model_dt/time_steps)"

    def test_covers_inflation_or_radius_changes(self):
        covered = any(
            any(kw in str(c.get("parameter", "")).lower()
                for kw in ["inflation", "robot_radius"])
            for c in self.changes
        )
        assert covered, "Must document and justify inflation radius or robot_radius changes"

    def test_covers_acceleration_changes(self):
        covered = any(
            any(kw in str(c.get("parameter", "")).lower()
                for kw in ["accel", "max_accel", "ax_max"])
            for c in self.changes
        )
        assert covered, "Must document and justify acceleration limit changes"
