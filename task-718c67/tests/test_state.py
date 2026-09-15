
import subprocess
import json
import os
import pytest

VALIDATOR = "/app/validate_plan.py"
PLANS_DIR = "/app/plans"


def run_validator(fplan_name):
    """Run the validator on a given fplan file and return the parsed JSON report."""
    fplan_path = os.path.join(PLANS_DIR, fplan_name)
    result = subprocess.run(
        ["python3", VALIDATOR, fplan_path],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.strip(), (
        f"Validator produced no stdout for {fplan_name}. "
        f"stderr: {result.stderr[:500]}"
    )
    report = json.loads(result.stdout)
    return report, result.returncode


# ── Valid mission: zero violations ──


class TestValidMission:
    def test_valid_plan_passes(self):
        report, rc = run_validator("valid_mission.fplan")
        assert report["valid"] is True
        assert report["summary"]["total_violations"] == 0
        assert len(report["violations"]) == 0

    def test_valid_plan_exit_code(self):
        _, rc = run_validator("valid_mission.fplan")
        assert rc == 0


# ── Camera errors: 3 violations ──


class TestCameraErrors:
    def test_total_violations(self):
        report, _ = run_validator("camera_errors.fplan")
        assert report["valid"] is False
        assert report["summary"]["total_violations"] >= 3

    def test_scicam_resolution_rejected(self):
        report, _ = run_validator("camera_errors.fplan")
        matches = [
            v
            for v in report["violations"]
            if v["type"] == "camera_resolution"
            and "Science" in v.get("message", "")
        ]
        assert len(matches) >= 1, "SciCam 320x240 should be flagged"

    def test_navcam_framerate_rejected(self):
        report, _ = run_validator("camera_errors.fplan")
        matches = [
            v
            for v in report["violations"]
            if v["type"] == "camera_frame_rate"
            and "Navigation" in v.get("message", "")
        ]
        assert len(matches) >= 1, "NavCam 25 Hz should be flagged"

    def test_hazcam_resolution_rejected(self):
        report, _ = run_validator("camera_errors.fplan")
        matches = [
            v
            for v in report["violations"]
            if v["type"] == "camera_resolution"
            and "Hazard" in v.get("message", "")
        ]
        assert len(matches) >= 1, "HazCam 640x480 should be flagged"


# ── Arm safety: 2 violations ──


class TestArmSafety:
    def test_total_violations(self):
        report, _ = run_validator("arm_safety.fplan")
        assert report["valid"] is False
        assert report["summary"]["total_violations"] >= 2

    def test_pan_nonzero_with_high_tilt(self):
        report, _ = run_validator("arm_safety.fplan")
        matches = [
            v
            for v in report["violations"]
            if v["type"] == "arm_collision_risk"
        ]
        assert len(matches) >= 1, (
            "pan=45 with tilt=120 should trigger arm collision risk"
        )

    def test_gripper_open_with_stow_tilt(self):
        report, _ = run_validator("arm_safety.fplan")
        matches = [
            v
            for v in report["violations"]
            if v["type"] == "arm_gripper_collision"
        ]
        assert len(matches) >= 1, (
            "tilt=170 with gripper open should trigger gripper collision"
        )

    def test_gripper_state_tracking(self):
        """The gripper is opened via gripperControl before the tilt=170 command.
        The validator must track this state across commands."""
        report, _ = run_validator("arm_safety.fplan")
        gripper_violations = [
            v
            for v in report["violations"]
            if v["type"] == "arm_gripper_collision"
        ]
        assert len(gripper_violations) >= 1


# ── Keepout zone violation ──


class TestKeepoutZone:
    def test_zone_violation_detected(self):
        report, _ = run_validator("zone_violation.fplan")
        assert report["valid"] is False
        zone_v = [
            v for v in report["violations"] if v["type"] == "keepout_zone"
        ]
        assert len(zone_v) >= 1

    def test_zone_name_in_message(self):
        report, _ = run_validator("zone_violation.fplan")
        zone_v = [
            v for v in report["violations"] if v["type"] == "keepout_zone"
        ]
        assert any(
            "us_lab_port_rack" in v.get("message", "") for v in zone_v
        ), "Should identify the specific keepout zone by name"


# ── Parameter errors: 4 violations ──


class TestParamErrors:
    def test_total_violations(self):
        report, _ = run_validator("param_errors.fplan")
        assert report["valid"] is False
        assert report["summary"]["total_violations"] >= 4

    def test_pan_range_exceeded(self):
        report, _ = run_validator("param_errors.fplan")
        range_v = [
            v
            for v in report["violations"]
            if v["type"] == "range_violation" and "pan" in v.get("message", "").lower()
        ]
        assert len(range_v) >= 1, "pan=100 exceeds max 90"

    def test_brightness_range_exceeded(self):
        report, _ = run_validator("param_errors.fplan")
        range_v = [
            v
            for v in report["violations"]
            if v["type"] == "range_violation"
            and "brightness" in v.get("message", "").lower()
        ]
        assert len(range_v) >= 1, "brightness=1.5 exceeds max 1.0"

    def test_invalid_camera_name(self):
        report, _ = run_validator("param_errors.fplan")
        enum_v = [
            v
            for v in report["violations"]
            if v["type"] == "invalid_enum"
            and "Thermal" in v.get("message", "")
        ]
        assert len(enum_v) >= 1, "cameraName='Thermal' is not valid"

    def test_unknown_command(self):
        report, _ = run_validator("param_errors.fplan")
        unknown_v = [
            v
            for v in report["violations"]
            if v["type"] == "unknown_command"
        ]
        assert len(unknown_v) >= 1, "Mobility.teleport should be unknown"


# ── Inertia matrix check ──


class TestInertiaCheck:
    def test_nonsymmetric_inertia_detected(self):
        report, _ = run_validator("inertia_check.fplan")
        assert report["valid"] is False
        inertia_v = [
            v
            for v in report["violations"]
            if v["type"] == "inertia_symmetry"
        ]
        assert len(inertia_v) >= 1, (
            "matrix[0][1]=0.02 != matrix[1][0]=0.01 should be caught"
        )


# ── Output format validation ──


class TestOutputFormat:
    def test_required_top_level_keys(self):
        report, _ = run_validator("valid_mission.fplan")
        for key in ["file", "valid", "violations", "summary"]:
            assert key in report, f"Missing top-level key: {key}"

    def test_summary_keys(self):
        report, _ = run_validator("valid_mission.fplan")
        for key in ["total_violations", "errors", "warnings"]:
            assert key in report["summary"], f"Missing summary key: {key}"

    def test_violations_is_list(self):
        report, _ = run_validator("valid_mission.fplan")
        assert isinstance(report["violations"], list)

    def test_violation_has_required_fields(self):
        report, _ = run_validator("camera_errors.fplan")
        for v in report["violations"]:
            assert "type" in v, "Violation missing 'type'"
            assert "severity" in v, "Violation missing 'severity'"
            assert "message" in v, "Violation missing 'message'"

    def test_invalid_plan_nonzero_exit(self):
        _, rc = run_validator("camera_errors.fplan")
        assert rc != 0, "Invalid plan should exit non-zero"
