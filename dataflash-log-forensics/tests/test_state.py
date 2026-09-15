
import json
import os
import pytest


@pytest.fixture
def assessment():
    path = "/app/fleet_assessment.json"
    assert os.path.exists(path), "fleet_assessment.json not found at /app/fleet_assessment.json"
    with open(path, "r") as f:
        data = json.load(f)
    return data


class TestStructure:
    def test_file_exists(self):
        assert os.path.exists("/app/fleet_assessment.json")

    def test_valid_json(self):
        with open("/app/fleet_assessment.json", "r") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_required_keys(self, assessment):
        for key in ["per_flight", "risk_ranking", "systemic_issues", "corrective_actions",
                     "fleet_airworthy_count", "fleet_conditional_count",
                     "fleet_grounded_count", "recommended_fleet_action"]:
            assert key in assessment, f"Missing top-level key: {key}"

    def test_all_flights_present(self, assessment):
        for flight in ["alpha", "bravo", "charlie"]:
            assert flight in assessment["per_flight"], f"Missing flight: {flight}"

    def test_per_flight_forensic_keys(self, assessment):
        for flight in ["alpha", "bravo", "charlie"]:
            fd = assessment["per_flight"][flight]
            for key in ["fault_chain", "failsafe_response_sec", "failsafe_assessment",
                         "airworthiness", "required_actions"]:
                assert key in fd, f"Missing forensic key '{key}' in flight {flight}"


class TestAlpha:
    def test_total_messages(self, assessment):
        assert assessment["per_flight"]["alpha"]["total_messages"] == 522

    def test_max_altitude(self, assessment):
        val = float(assessment["per_flight"]["alpha"]["max_altitude_m"])
        assert abs(val - 30.0) < 0.5

    def test_gps_score(self, assessment):
        val = float(assessment["per_flight"]["alpha"]["gps_score"])
        assert abs(val - 90.0) < 0.5

    def test_ekf_score(self, assessment):
        val = float(assessment["per_flight"]["alpha"]["ekf_score"])
        assert abs(val - 60.0) < 0.5

    def test_vibe_score(self, assessment):
        val = float(assessment["per_flight"]["alpha"]["vibe_score"])
        assert abs(val - 80.0) < 0.5

    def test_param_score(self, assessment):
        val = float(assessment["per_flight"]["alpha"]["param_score"])
        assert abs(val - 93.33) < 0.5

    def test_mode_score(self, assessment):
        val = float(assessment["per_flight"]["alpha"]["mode_score"])
        assert abs(val - 100.0) < 0.5

    def test_composite_score(self, assessment):
        val = float(assessment["per_flight"]["alpha"]["composite_score"])
        assert abs(val - 82.0) < 0.5

    def test_risk_level(self, assessment):
        assert assessment["per_flight"]["alpha"]["risk_level"] == "low"

    def test_root_cause(self, assessment):
        assert assessment["per_flight"]["alpha"]["root_cause"] == "none"

    def test_misconfigured_params(self, assessment):
        params = sorted(assessment["per_flight"]["alpha"]["misconfigured_params"])
        assert params == ["INS_ACCEL_FILTER"]


class TestBravo:
    def test_total_messages(self, assessment):
        assert assessment["per_flight"]["bravo"]["total_messages"] == 622

    def test_max_altitude(self, assessment):
        val = float(assessment["per_flight"]["bravo"]["max_altitude_m"])
        assert abs(val - 40.0) < 0.5

    def test_gps_score(self, assessment):
        val = float(assessment["per_flight"]["bravo"]["gps_score"])
        assert abs(val - 100.0) < 0.5

    def test_ekf_score(self, assessment):
        val = float(assessment["per_flight"]["bravo"]["ekf_score"])
        assert abs(val - 24.0) < 0.5

    def test_vibe_score(self, assessment):
        val = float(assessment["per_flight"]["bravo"]["vibe_score"])
        assert abs(val - 30.0) < 0.5

    def test_param_score(self, assessment):
        val = float(assessment["per_flight"]["bravo"]["param_score"])
        assert abs(val - 86.67) < 0.5

    def test_mode_score(self, assessment):
        val = float(assessment["per_flight"]["bravo"]["mode_score"])
        assert abs(val - 75.0) < 0.5

    def test_composite_score(self, assessment):
        val = float(assessment["per_flight"]["bravo"]["composite_score"])
        assert abs(val - 62.5) < 0.5

    def test_risk_level(self, assessment):
        assert assessment["per_flight"]["bravo"]["risk_level"] == "moderate"

    def test_root_cause(self, assessment):
        assert assessment["per_flight"]["bravo"]["root_cause"] == "mechanical_vibration"

    def test_misconfigured_params(self, assessment):
        params = sorted(assessment["per_flight"]["bravo"]["misconfigured_params"])
        assert params == ["INS_ACCEL_FILTER", "PILOT_THR_FILT"]


class TestCharlie:
    def test_total_messages(self, assessment):
        assert assessment["per_flight"]["charlie"]["total_messages"] == 904

    def test_max_altitude(self, assessment):
        val = float(assessment["per_flight"]["charlie"]["max_altitude_m"])
        assert abs(val - 35.0) < 0.5

    def test_gps_score(self, assessment):
        val = float(assessment["per_flight"]["charlie"]["gps_score"])
        assert abs(val - 65.34) < 0.5

    def test_ekf_score(self, assessment):
        val = float(assessment["per_flight"]["charlie"]["ekf_score"])
        assert abs(val - 4.0) < 0.5

    def test_vibe_score(self, assessment):
        val = float(assessment["per_flight"]["charlie"]["vibe_score"])
        assert abs(val - 20.0) < 0.5

    def test_param_score(self, assessment):
        val = float(assessment["per_flight"]["charlie"]["param_score"])
        assert abs(val - 73.33) < 0.5

    def test_mode_score(self, assessment):
        val = float(assessment["per_flight"]["charlie"]["mode_score"])
        assert abs(val - 75.0) < 0.5

    def test_composite_score(self, assessment):
        val = float(assessment["per_flight"]["charlie"]["composite_score"])
        assert abs(val - 43.10) < 0.5

    def test_risk_level(self, assessment):
        assert assessment["per_flight"]["charlie"]["risk_level"] == "high"

    def test_root_cause(self, assessment):
        assert assessment["per_flight"]["charlie"]["root_cause"] == "gps_glitch"

    def test_misconfigured_params(self, assessment):
        params = sorted(assessment["per_flight"]["charlie"]["misconfigured_params"])
        assert params == [
            "EK3_CHECK_SCALE", "FS_BATT_ENABLE",
            "INS_ACCEL_FILTER", "PILOT_THR_FILT"
        ]

    def test_ek3_check_scale_last_write_wins(self, assessment):
        """EK3_CHECK_SCALE logged twice: 100 then 50. Agent must use last value (50)."""
        assert "EK3_CHECK_SCALE" in assessment["per_flight"]["charlie"]["misconfigured_params"]


class TestFleetAnalysis:
    def test_risk_ranking_order(self, assessment):
        """Most dangerous first: charlie (43.10), bravo (62.5), alpha (82.0)"""
        assert assessment["risk_ranking"] == ["charlie", "bravo", "alpha"]

    def test_systemic_issues(self, assessment):
        """INS_ACCEL_FILTER=15 is misconfigured in all three flights"""
        assert sorted(assessment["systemic_issues"]) == ["INS_ACCEL_FILTER"]

    def test_systemic_not_pilot_thr(self, assessment):
        """PILOT_THR_FILT is only misconfigured in bravo and charlie, not alpha"""
        assert "PILOT_THR_FILT" not in assessment["systemic_issues"]

    def test_corrective_alpha(self, assessment):
        actions = assessment["corrective_actions"]["alpha"]
        assert float(actions["INS_ACCEL_FILTER"]) == 5.0
        assert len(actions) == 1

    def test_corrective_bravo(self, assessment):
        actions = assessment["corrective_actions"]["bravo"]
        assert float(actions["INS_ACCEL_FILTER"]) == 5.0
        assert abs(float(actions["PILOT_THR_FILT"]) - 0.5) < 0.01
        assert len(actions) == 2

    def test_corrective_charlie(self, assessment):
        actions = assessment["corrective_actions"]["charlie"]
        assert float(actions["EK3_CHECK_SCALE"]) == 100.0
        assert float(actions["FS_BATT_ENABLE"]) == 0.0
        assert float(actions["INS_ACCEL_FILTER"]) == 5.0
        assert abs(float(actions["PILOT_THR_FILT"]) - 0.5) < 0.01
        assert len(actions) == 4

    def test_corrective_has_all_flights(self, assessment):
        for flight in ["alpha", "bravo", "charlie"]:
            assert flight in assessment["corrective_actions"]


class TestAlphaForensics:
    """Alpha: clean flight with parameter issue only — no sensor anomalies detected."""

    def test_fault_chain_empty(self, assessment):
        """No GPS glitch (min status=2, not <2), no EKF exceedance, no vibration exceedance."""
        assert assessment["per_flight"]["alpha"]["fault_chain"] == []

    def test_failsafe_response_null(self, assessment):
        assert assessment["per_flight"]["alpha"]["failsafe_response_sec"] is None

    def test_failsafe_assessment(self, assessment):
        assert assessment["per_flight"]["alpha"]["failsafe_assessment"] == "not_applicable"

    def test_airworthiness_conditional(self, assessment):
        """No sensor anomalies but INS_ACCEL_FILTER misconfigured → conditional."""
        assert assessment["per_flight"]["alpha"]["airworthiness"] == "conditional"

    def test_required_actions(self, assessment):
        assert assessment["per_flight"]["alpha"]["required_actions"] == ["parameter_update"]


class TestBravoForensics:
    """Bravo: vibration-first failure with cascading EKF divergence via IMU saturation."""

    def test_fault_chain_length(self, assessment):
        assert len(assessment["per_flight"]["bravo"]["fault_chain"]) == 2

    def test_fault_chain_primary_vibration(self, assessment):
        """Primary cause: mechanical vibration exceeds 30 m/s/s threshold at t=98s."""
        chain = assessment["per_flight"]["bravo"]["fault_chain"]
        assert chain[0]["event"] == "mechanical_vibration"
        assert chain[0]["time_sec"] == 98
        assert chain[0]["category"] == "primary"

    def test_fault_chain_secondary_ekf(self, assessment):
        """Secondary: vibration saturates IMU accelerometers → EKF variance exceeds
        FS_EKF_THRESH at t=117s. Known causal pathway: mechanical_vibration→ekf_divergence."""
        chain = assessment["per_flight"]["bravo"]["fault_chain"]
        assert chain[1]["event"] == "ekf_divergence"
        assert chain[1]["time_sec"] == 117
        assert chain[1]["category"] == "secondary"

    def test_failsafe_response_delay(self, assessment):
        """Failsafe LAND (mode 9, reason=4) at t=110s, first anomaly at t=98s → 12s delay."""
        assert assessment["per_flight"]["bravo"]["failsafe_response_sec"] == 12

    def test_failsafe_assessment_delayed(self, assessment):
        """12 seconds exceeds 10-second timeliness threshold → delayed response."""
        assert assessment["per_flight"]["bravo"]["failsafe_assessment"] == "delayed"

    def test_airworthiness_grounded(self, assessment):
        assert assessment["per_flight"]["bravo"]["airworthiness"] == "grounded"

    def test_required_actions(self, assessment):
        """Vibration as primary fault → mechanical_inspection; misconfigured params → parameter_update."""
        expected = ["mechanical_inspection", "parameter_update"]
        assert assessment["per_flight"]["bravo"]["required_actions"] == expected


class TestCharlieForensics:
    """Charlie: GPS-first failure with cascading EKF divergence and independent vibration."""

    def test_fault_chain_length(self, assessment):
        assert len(assessment["per_flight"]["charlie"]["fault_chain"]) == 3

    def test_fault_chain_primary_gps(self, assessment):
        """Primary cause: GPS status drops to 1 (below 2 threshold) at t=120s."""
        chain = assessment["per_flight"]["charlie"]["fault_chain"]
        assert chain[0]["event"] == "gps_glitch"
        assert chain[0]["time_sec"] == 120
        assert chain[0]["category"] == "primary"

    def test_fault_chain_secondary_ekf(self, assessment):
        """Secondary: GPS loss removes EKF's primary position observation source →
        variance exceeds FS_EKF_THRESH at t=136s. Known causal pathway: gps_glitch→ekf_divergence."""
        chain = assessment["per_flight"]["charlie"]["fault_chain"]
        assert chain[1]["event"] == "ekf_divergence"
        assert chain[1]["time_sec"] == 136
        assert chain[1]["category"] == "secondary"

    def test_fault_chain_independent_vibration(self, assessment):
        """Independent: vibration at t=164s has no causal link from GPS or EKF failures.
        No defined causal pathway exists from gps_glitch or ekf_divergence to mechanical_vibration."""
        chain = assessment["per_flight"]["charlie"]["fault_chain"]
        assert chain[2]["event"] == "mechanical_vibration"
        assert chain[2]["time_sec"] == 164
        assert chain[2]["category"] == "independent"

    def test_failsafe_response_delay(self, assessment):
        """Failsafe LAND (mode 9, reason=4) at t=142s, first anomaly at t=120s → 22s delay."""
        assert assessment["per_flight"]["charlie"]["failsafe_response_sec"] == 22

    def test_failsafe_assessment_delayed(self, assessment):
        """22 seconds exceeds 10-second timeliness threshold → delayed response."""
        assert assessment["per_flight"]["charlie"]["failsafe_assessment"] == "delayed"

    def test_airworthiness_grounded(self, assessment):
        assert assessment["per_flight"]["charlie"]["airworthiness"] == "grounded"

    def test_required_actions(self, assessment):
        """GPS primary → gps_inspection; vibration independent → mechanical_inspection;
        misconfigured params → parameter_update. All sorted alphabetically."""
        expected = ["gps_inspection", "mechanical_inspection", "parameter_update"]
        assert assessment["per_flight"]["charlie"]["required_actions"] == expected


class TestFleetRecommendation:
    """Fleet-level operational readiness assessment."""

    def test_airworthy_count(self, assessment):
        assert assessment["fleet_airworthy_count"] == 0

    def test_conditional_count(self, assessment):
        assert assessment["fleet_conditional_count"] == 1

    def test_grounded_count(self, assessment):
        assert assessment["fleet_grounded_count"] == 2

    def test_fleet_action_is_review(self, assessment):
        """2 grounded vehicles + systemic INS_ACCEL_FILTER issue across all 3 flights
        → fleet_review (not partial_ground, because systemic issues elevate severity)."""
        assert assessment["recommended_fleet_action"] == "fleet_review"

    def test_not_partial_ground(self, assessment):
        """Systemic issues distinguish fleet_review from partial_ground."""
        assert assessment["recommended_fleet_action"] != "partial_ground"
