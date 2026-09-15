
"""Tests for Physics Trajectory Forensics analysis tool."""

import json
import os
import subprocess

import pytest

TOOL_PATH = "/app/physinfer/analyze.py"
DATA_DIR = "/app/data"

SCENARIOS = [
    "freefall.h5",
    "elastic_1d.h5",
    "projectile.h5",
    "friction_slide.h5",
    "oblique_elastic.h5",
    "gravity_mismatch.h5",
    "energy_gain.h5",
    "momentum_change.h5",
]


def run_analysis(trajectory_file):
    result = subprocess.run(
        ["python3", TOOL_PATH, trajectory_file],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Tool failed on {trajectory_file}:\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        pytest.fail(
            f"Invalid JSON from {trajectory_file}: {e}\n"
            f"stdout: {result.stdout}"
        )


# ---------------------------------------------------------------------------
# Output schema validation
# ---------------------------------------------------------------------------

class TestOutputSchema:
    @pytest.fixture(params=SCENARIOS)
    def report(self, request):
        return run_analysis(os.path.join(DATA_DIR, request.param))

    def test_required_fields(self, report):
        for field in ("scenario_id", "classification", "inferred_parameters",
                      "anomalies", "plausibility_score"):
            assert field in report, f"Missing field: {field}"

    def test_classification_value(self, report):
        valid = {"physically_valid", "gravity_anomaly",
                 "energy_violation", "momentum_violation"}
        assert report["classification"] in valid

    def test_score_range(self, report):
        s = report["plausibility_score"]
        assert isinstance(s, (int, float))
        assert 0 <= s <= 100

    def test_anomalies_is_list(self, report):
        assert isinstance(report["anomalies"], list)

    def test_inferred_parameters_keys(self, report):
        ip = report["inferred_parameters"]
        assert isinstance(ip, dict)
        for k in ("gravity", "mass_ratios",
                   "coefficient_of_restitution", "friction_coefficient"):
            assert k in ip, f"Missing inferred_parameters.{k}"


# ---------------------------------------------------------------------------
# Free fall — physically valid, gravity inference
# ---------------------------------------------------------------------------

class TestFreeFall:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analysis(os.path.join(DATA_DIR, "freefall.h5"))

    def test_classification(self):
        assert self.r["classification"] == "physically_valid"

    def test_gravity(self):
        g = self.r["inferred_parameters"]["gravity"]
        assert g is not None, "Gravity should be inferred"
        assert abs(g - 9.81) < 0.15, f"Expected g~9.81, got {g}"

    def test_score(self):
        assert self.r["plausibility_score"] >= 90


# ---------------------------------------------------------------------------
# Elastic 1-D collision — physically valid, mass ratio + CoR
# ---------------------------------------------------------------------------

class TestElastic1D:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analysis(os.path.join(DATA_DIR, "elastic_1d.h5"))

    def test_classification(self):
        assert self.r["classification"] == "physically_valid"

    def test_cor(self):
        cor = self.r["inferred_parameters"]["coefficient_of_restitution"]
        assert cor is not None, "CoR should be inferred"
        assert abs(cor - 1.0) < 0.15, f"Expected CoR~1.0, got {cor}"

    def test_mass_ratio(self):
        ratios = self.r["inferred_parameters"]["mass_ratios"]
        assert ratios is not None, "Mass ratios should be inferred"
        ratio_val = None
        for key, val in ratios.items():
            if "ball_A" in key and "ball_B" in key:
                ratio_val = val
                break
        if ratio_val is None:
            ratio_val = list(ratios.values())[0]
        # m_A/m_B = 2/3 ~ 0.667 or m_B/m_A = 3/2 = 1.5
        assert (abs(ratio_val - 2.0 / 3.0) < 0.2
                or abs(ratio_val - 1.5) < 0.2), (
            f"Expected mass ratio ~0.667 or ~1.5, got {ratio_val}"
        )

    def test_score(self):
        assert self.r["plausibility_score"] >= 90


# ---------------------------------------------------------------------------
# Projectile — physically valid, gravity from parabolic trajectory
# ---------------------------------------------------------------------------

class TestProjectile:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analysis(os.path.join(DATA_DIR, "projectile.h5"))

    def test_classification(self):
        assert self.r["classification"] == "physically_valid"

    def test_gravity(self):
        g = self.r["inferred_parameters"]["gravity"]
        assert g is not None, "Gravity should be inferred"
        assert abs(g - 9.81) < 0.15, f"Expected g~9.81, got {g}"

    def test_score(self):
        assert self.r["plausibility_score"] >= 90


# ---------------------------------------------------------------------------
# Friction slide — physically valid, friction coefficient inference
# ---------------------------------------------------------------------------

class TestFrictionSlide:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analysis(os.path.join(DATA_DIR, "friction_slide.h5"))

    def test_classification(self):
        assert self.r["classification"] == "physically_valid"

    def test_friction(self):
        mu = self.r["inferred_parameters"]["friction_coefficient"]
        assert mu is not None, "Friction coefficient should be inferred"
        assert abs(mu - 0.3) < 0.06, f"Expected mu~0.3, got {mu}"

    def test_score(self):
        assert self.r["plausibility_score"] >= 90


# ---------------------------------------------------------------------------
# Oblique elastic collision — physically valid, 2-D collision handling
# ---------------------------------------------------------------------------

class TestObliqueElastic:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analysis(os.path.join(DATA_DIR, "oblique_elastic.h5"))

    def test_classification(self):
        assert self.r["classification"] == "physically_valid"

    def test_cor(self):
        cor = self.r["inferred_parameters"]["coefficient_of_restitution"]
        assert cor is not None, "CoR should be inferred from 2-D collision"
        assert abs(cor - 1.0) < 0.15, f"Expected CoR~1.0, got {cor}"

    def test_mass_ratio(self):
        ratios = self.r["inferred_parameters"]["mass_ratios"]
        assert ratios is not None, "Mass ratios should be inferred"
        ratio_val = list(ratios.values())[0]
        # m_A/m_B = 2.0 or m_B/m_A = 0.5
        assert (abs(ratio_val - 2.0) < 0.25
                or abs(ratio_val - 0.5) < 0.15), (
            f"Expected mass ratio ~2.0 or ~0.5, got {ratio_val}"
        )

    def test_score(self):
        assert self.r["plausibility_score"] >= 85


# ---------------------------------------------------------------------------
# Gravity mismatch — gravity anomaly detection
# ---------------------------------------------------------------------------

class TestGravityMismatch:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analysis(os.path.join(DATA_DIR, "gravity_mismatch.h5"))

    def test_classification(self):
        assert self.r["classification"] == "gravity_anomaly"

    def test_inferred_gravity(self):
        g = self.r["inferred_parameters"]["gravity"]
        assert g is not None, "Gravity should be inferred"
        assert abs(g - 5.0) < 0.2, f"Expected inferred g~5.0, got {g}"

    def test_score(self):
        s = self.r["plausibility_score"]
        assert 30 <= s <= 70, f"Expected score in [30,70], got {s}"

    def test_anomaly(self):
        types = [a["type"] for a in self.r["anomalies"]]
        assert "gravity_anomaly" in types


# ---------------------------------------------------------------------------
# Energy gain — energy violation at collision
# ---------------------------------------------------------------------------

class TestEnergyGain:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analysis(os.path.join(DATA_DIR, "energy_gain.h5"))

    def test_classification(self):
        assert self.r["classification"] == "energy_violation"

    def test_score(self):
        assert self.r["plausibility_score"] < 75

    def test_anomaly(self):
        types = [a["type"] for a in self.r["anomalies"]]
        assert "energy_violation" in types


# ---------------------------------------------------------------------------
# Momentum change — momentum violation at collision
# ---------------------------------------------------------------------------

class TestMomentumChange:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.r = run_analysis(os.path.join(DATA_DIR, "momentum_change.h5"))

    def test_classification(self):
        assert self.r["classification"] == "momentum_violation"

    def test_score(self):
        assert self.r["plausibility_score"] < 75

    def test_anomaly(self):
        types = [a["type"] for a in self.r["anomalies"]]
        assert "momentum_violation" in types

    def test_priority(self):
        """Momentum violation should take priority even if energy also changes."""
        assert self.r["classification"] == "momentum_violation"
