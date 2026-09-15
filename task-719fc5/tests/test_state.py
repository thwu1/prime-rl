
import subprocess
import json
import os
import sys

import yaml


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _run_auditor(config_path):
    """Run the auditor on the given config and return parsed JSON issues."""
    result = subprocess.run(
        ["python3", "/app/nav2_auditor.py", config_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Auditor exited with code {result.returncode}.\n"
        f"stdout: {result.stdout[:500]}\nstderr: {result.stderr[:500]}"
    )
    issues = json.loads(result.stdout)
    assert isinstance(issues, list), "Auditor output must be a JSON array"
    return issues


def _load_fixed():
    with open("/app/nav2_params_fixed.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 1. Auditor existence and basic execution
# ---------------------------------------------------------------------------

class TestAuditorBasics:
    def test_auditor_exists(self):
        assert os.path.isfile("/app/nav2_auditor.py"), "nav2_auditor.py not found"

    def test_auditor_runs_on_broken(self):
        issues = _run_auditor("/app/nav2_params.yaml")
        assert len(issues) >= 10, (
            f"Expected >= 10 issues on broken config, got {len(issues)}"
        )

    def test_auditor_distinct_rules(self):
        issues = _run_auditor("/app/nav2_params.yaml")
        rule_ids = {i["rule_id"] for i in issues}
        assert len(rule_ids) >= 10, (
            f"Expected >= 10 distinct rule_ids, got {len(rule_ids)}: {rule_ids}"
        )

    def test_issue_schema(self):
        issues = _run_auditor("/app/nav2_params.yaml")
        for issue in issues:
            assert "rule_id" in issue, "Each issue must have a rule_id"
            assert "severity" in issue, "Each issue must have a severity"
            assert "description" in issue, "Each issue must have a description"
            assert issue["severity"] in (
                "critical",
                "error",
                "warning",
            ), f"Invalid severity: {issue['severity']}"


# ---------------------------------------------------------------------------
# 2. Fixed config existence and validity
# ---------------------------------------------------------------------------

class TestFixedConfigBasics:
    def test_exists(self):
        assert os.path.isfile("/app/nav2_params_fixed.yaml")

    def test_valid_yaml(self):
        cfg = _load_fixed()
        assert isinstance(cfg, dict)

    def test_has_key_components(self):
        cfg = _load_fixed()
        for key in [
            "controller_server",
            "local_costmap",
            "global_costmap",
            "bt_navigator",
            "planner_server",
            "velocity_smoother",
            "collision_monitor",
        ]:
            assert key in cfg, f"Fixed config missing component: {key}"


# ---------------------------------------------------------------------------
# 3. Individual fix verification
# ---------------------------------------------------------------------------

class TestFixCostmapPluginOrder:
    """Bug 1: inflation_layer must come after all obstacle source layers."""

    def test_local_costmap_order(self):
        cfg = _load_fixed()
        plugins = cfg["local_costmap"]["local_costmap"]["ros__parameters"]["plugins"]
        obstacle_sources = [
            p for p in plugins if p in ("voxel_layer", "obstacle_layer", "static_layer")
        ]
        inflation_layers = [p for p in plugins if "inflation" in p.lower()]
        assert obstacle_sources, "No obstacle source layers in local costmap plugins"
        assert inflation_layers, "No inflation layer in local costmap plugins"
        last_source = max(plugins.index(s) for s in obstacle_sources)
        first_inflation = min(plugins.index(i) for i in inflation_layers)
        assert first_inflation > last_source, (
            f"Inflation (idx {first_inflation}) must come after last obstacle source "
            f"(idx {last_source}) in plugins list: {plugins}"
        )


class TestFixMotionModelConsistency:
    """Bug 2: motion model name and plugin class must match."""

    def test_diff_drive_plugin(self):
        cfg = _load_fixed()
        fp = cfg["controller_server"]["ros__parameters"]["FollowPath"]
        mm = fp.get("motion_model", "")
        if mm == "diff_drive" and "diff_drive" in fp:
            plugin = fp["diff_drive"].get("plugin", "")
            assert "DiffDrive" in plugin, (
                f"diff_drive motion model should use DiffDriveMotionModel, got: {plugin}"
            )
        elif mm == "omni" and "omni" in fp:
            plugin = fp["omni"].get("plugin", "")
            assert "Omni" in plugin


class TestFixRobotRadiusConsistency:
    """Bug 3: robot_radius must match between local and global costmaps."""

    def test_matching_radius(self):
        cfg = _load_fixed()
        local_rr = cfg["local_costmap"]["local_costmap"]["ros__parameters"]["robot_radius"]
        global_rr = cfg["global_costmap"]["global_costmap"]["ros__parameters"]["robot_radius"]
        assert abs(local_rr - global_rr) < 0.001, (
            f"robot_radius mismatch: local={local_rr}, global={global_rr}"
        )


class TestFixInflationRadius:
    """Bug 4: inflation_radius must be >= robot_radius."""

    def test_global_inflation(self):
        cfg = _load_fixed()
        gp = cfg["global_costmap"]["global_costmap"]["ros__parameters"]
        rr = gp["robot_radius"]
        ir = gp["inflation_layer"]["inflation_radius"]
        assert ir >= rr, f"inflation_radius ({ir}) < robot_radius ({rr})"


class TestFixKeepoutFilterType:
    """Bug 5: keepout filter info server type must be 0."""

    def test_type_zero(self):
        cfg = _load_fixed()
        t = cfg["keepout_costmap_filter_info_server"]["ros__parameters"]["type"]
        assert t == 0, f"Keepout filter type must be 0, got {t}"


class TestFixSpeedFilterMultiplier:
    """Bug 6: speed filter multiplier must be negative."""

    def test_negative_multiplier(self):
        cfg = _load_fixed()
        m = cfg["speed_costmap_filter_info_server"]["ros__parameters"]["multiplier"]
        assert m < 0, f"Speed filter multiplier must be negative, got {m}"


class TestFixCostmapSizeForHorizon:
    """Bug 7: local costmap must be large enough for MPPI prediction horizon."""

    def test_costmap_covers_horizon(self):
        cfg = _load_fixed()
        lp = cfg["local_costmap"]["local_costmap"]["ros__parameters"]
        mppi = cfg["controller_server"]["ros__parameters"]["FollowPath"]
        horizon_dist = mppi["time_steps"] * mppi["model_dt"] * mppi["vx_max"]
        half_width = lp["width"] / 2.0
        assert half_width >= horizon_dist, (
            f"Costmap half-width ({half_width}) < prediction distance ({horizon_dist})"
        )


class TestFixProgressCheckerVsGoal:
    """Bug 8: progress checker radius must be <= goal tolerance."""

    def test_radius_lte_tolerance(self):
        cfg = _load_fixed()
        ctrl = cfg["controller_server"]["ros__parameters"]
        pc = ctrl["progress_checker"]["required_movement_radius"]
        gc = ctrl["general_goal_checker"]["xy_goal_tolerance"]
        assert pc <= gc, (
            f"Progress checker radius ({pc}) > goal tolerance ({gc})"
        )


class TestFixFrameIdConsistency:
    """Bug 9: all components must use the same robot base frame."""

    def test_consistent_frames(self):
        cfg = _load_fixed()
        frames = set()
        cm = cfg.get("collision_monitor", {}).get("ros__parameters", {})
        if "base_frame_id" in cm:
            frames.add(cm["base_frame_id"])
        for cname in ("local_costmap", "global_costmap"):
            inner = cfg.get(cname, {}).get(cname, {}).get("ros__parameters", {})
            if "robot_base_frame" in inner:
                frames.add(inner["robot_base_frame"])
        assert len(frames) <= 1, f"Inconsistent base frame IDs: {frames}"


class TestFixVelocitySmoother:
    """Bug 10: velocity smoother limits must be >= controller limits."""

    def test_vx_not_clipped(self):
        cfg = _load_fixed()
        vs = cfg["velocity_smoother"]["ros__parameters"]
        mppi = cfg["controller_server"]["ros__parameters"]["FollowPath"]
        assert vs["max_velocity"][0] >= mppi["vx_max"], (
            f"Smoother vx ({vs['max_velocity'][0]}) < MPPI vx_max ({mppi['vx_max']})"
        )

    def test_wz_not_clipped(self):
        cfg = _load_fixed()
        vs = cfg["velocity_smoother"]["ros__parameters"]
        mppi = cfg["controller_server"]["ros__parameters"]["FollowPath"]
        assert vs["max_velocity"][2] >= mppi["wz_max"], (
            f"Smoother wz ({vs['max_velocity'][2]}) < MPPI wz_max ({mppi['wz_max']})"
        )


class TestFixBtTimeout:
    """Bug 11: BT navigator timeout must be >= planner costmap_update_timeout."""

    def test_bt_gte_planner(self):
        cfg = _load_fixed()
        bt = cfg["bt_navigator"]["ros__parameters"]["default_server_timeout"]
        pt = cfg["planner_server"]["ros__parameters"]["costmap_update_timeout"]
        assert bt >= pt, f"BT timeout ({bt}) < planner timeout ({pt})"


class TestFixStaticLayerInPlugins:
    """Bug 12: configured static_layer must appear in global costmap plugins list."""

    def test_static_in_plugins(self):
        cfg = _load_fixed()
        gp = cfg["global_costmap"]["global_costmap"]["ros__parameters"]
        if "static_layer" in gp and isinstance(gp["static_layer"], dict):
            assert "static_layer" in gp["plugins"], (
                "static_layer is configured but missing from plugins list"
            )


# ---------------------------------------------------------------------------
# 4. Auditor reports clean on fixed config
# ---------------------------------------------------------------------------

class TestAuditorOnFixed:
    def test_zero_issues(self):
        issues = _run_auditor("/app/nav2_params_fixed.yaml")
        assert len(issues) == 0, (
            f"Fixed config should have 0 issues, got {len(issues)}:\n"
            + json.dumps(issues, indent=2)
        )


# ---------------------------------------------------------------------------
# 5. Audit report file
# ---------------------------------------------------------------------------

class TestAuditReport:
    def test_report_exists(self):
        assert os.path.isfile("/app/audit_report.json"), "audit_report.json not found"

    def test_report_valid(self):
        with open("/app/audit_report.json") as f:
            report = json.load(f)
        assert isinstance(report, list)
        assert len(report) >= 10, f"Report should have >= 10 issues, got {len(report)}"
