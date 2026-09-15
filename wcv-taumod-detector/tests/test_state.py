"""
Tests for WCV_taumod conflict detector output.
Verifies the agent's implementation against known-correct values
computed from the PVS formal specifications.

"""
import json
import math
import os
import pytest

RESULTS_PATH = "/app/output/results.json"

# Expected results computed from the PVS WCV_taumod specification.
# Scenarios use relative coordinates; configs define WCV thresholds.
EXPECTED = [
    {
        "scenario": "head_on", "config": "standard_dwc",
        "has_violation": True,
        "first_step": 24, "last_step": 67,
        "entry_time": 23.29, "exit_time": 67.92,
        "tcpa": 60.0, "dcpa": 0.0,
        "num_violation_steps": 44,
    },
    {
        "scenario": "head_on", "config": "buffered_dwc",
        "has_violation": True,
        "first_step": 22, "last_step": 72,
        "entry_time": 21.28, "exit_time": 72.0,
        "tcpa": 60.0, "dcpa": 0.0,
        "num_violation_steps": 51,
    },
    {
        "scenario": "crossing", "config": "standard_dwc",
        "has_violation": True,
        "first_step": 20, "last_step": 52,
        "entry_time": 20.0, "exit_time": 52.10,
        "tcpa": 46.15, "dcpa": 0.555,
        "num_violation_steps": 33,
    },
    {
        "scenario": "crossing", "config": "buffered_dwc",
        "has_violation": True,
        "first_step": 7, "last_step": 60,
        "entry_time": 6.34, "exit_time": 60.0,
        "tcpa": 46.15, "dcpa": 0.555,
        "num_violation_steps": 54,
    },
    {
        "scenario": "overtake", "config": "standard_dwc",
        "has_violation": True,
        "first_step": 28, "last_step": 93,
        "entry_time": 27.04, "exit_time": 93.16,
        "tcpa": 72.0, "dcpa": 0.3,
        "num_violation_steps": 66,
    },
    {
        "scenario": "overtake", "config": "buffered_dwc",
        "has_violation": True,
        "first_step": 16, "last_step": 106,
        "entry_time": 15.96, "exit_time": 106.34,
        "tcpa": 72.0, "dcpa": 0.3,
        "num_violation_steps": 91,
    },
    {
        "scenario": "diverging", "config": "standard_dwc",
        "has_violation": False,
        "tcpa": 0.0, "dcpa": 3.0,
    },
    {
        "scenario": "diverging", "config": "buffered_dwc",
        "has_violation": False,
        "tcpa": 0.0, "dcpa": 3.0,
    },
]


@pytest.fixture(scope="module")
def results():
    """Load the agent's output results."""
    assert os.path.exists(RESULTS_PATH), (
        f"Output file {RESULTS_PATH} does not exist. "
        "The agent must write results to /app/output/results.json."
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert "analyses" in data, "results.json must contain an 'analyses' key"
    return data["analyses"]


def find_analysis(results, scenario, config):
    """Find analysis entry by scenario and config name."""
    for a in results:
        if a.get("scenario") == scenario and a.get("config") == config:
            return a
    return None


class TestOutputStructure:
    """Verify the output has the correct structure."""

    def test_correct_number_of_analyses(self, results):
        assert len(results) == 8, (
            f"Expected 8 analyses (4 scenarios x 2 configs), got {len(results)}"
        )

    def test_all_pairs_present(self, results):
        for exp in EXPECTED:
            a = find_analysis(results, exp["scenario"], exp["config"])
            assert a is not None, (
                f"Missing analysis for {exp['scenario']} x {exp['config']}"
            )

    def test_required_fields(self, results):
        required = ["scenario", "config", "has_violation"]
        for a in results:
            for field in required:
                assert field in a, (
                    f"Missing field '{field}' in analysis for "
                    f"{a.get('scenario', '?')} x {a.get('config', '?')}"
                )


class TestDivergingScenario:
    """Diverging scenario must have no violations."""

    @pytest.mark.parametrize("config", ["standard_dwc", "buffered_dwc"])
    def test_no_violation(self, results, config):
        a = find_analysis(results, "diverging", config)
        assert a is not None, f"Missing diverging x {config}"
        assert a["has_violation"] is False, (
            f"Diverging scenario with {config} should have no violation"
        )


class TestHeadOnScenario:
    """Head-on encounter: both aircraft on collision course, same altitude."""

    @pytest.mark.parametrize("config_idx", [0, 1])
    def test_has_violation(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert a is not None
        assert a["has_violation"] is True

    @pytest.mark.parametrize("config_idx", [0, 1])
    def test_first_last_step(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert a["first_violation_step"] == exp["first_step"], (
            f"head_on x {exp['config']}: expected first_step={exp['first_step']}, "
            f"got {a['first_violation_step']}"
        )
        assert a["last_violation_step"] == exp["last_step"], (
            f"head_on x {exp['config']}: expected last_step={exp['last_step']}, "
            f"got {a['last_violation_step']}"
        )

    @pytest.mark.parametrize("config_idx", [0, 1])
    def test_violation_interval(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert abs(a["violation_entry_time"] - exp["entry_time"]) < 0.5, (
            f"head_on x {exp['config']}: entry_time off. "
            f"Expected ~{exp['entry_time']}, got {a['violation_entry_time']}"
        )
        assert abs(a["violation_exit_time"] - exp["exit_time"]) < 0.5, (
            f"head_on x {exp['config']}: exit_time off. "
            f"Expected ~{exp['exit_time']}, got {a['violation_exit_time']}"
        )

    @pytest.mark.parametrize("config_idx", [0, 1])
    def test_tcpa_dcpa(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert abs(a["tcpa"] - exp["tcpa"]) < 1.0, (
            f"head_on TCPA: expected ~{exp['tcpa']}, got {a['tcpa']}"
        )
        assert abs(a["dcpa"] - exp["dcpa"]) < 0.05, (
            f"head_on DCPA: expected ~{exp['dcpa']}, got {a['dcpa']}"
        )

    @pytest.mark.parametrize("config_idx", [0, 1])
    def test_violation_steps_count(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        steps = a.get("violation_steps", [])
        assert len(steps) == exp["num_violation_steps"], (
            f"head_on x {exp['config']}: expected {exp['num_violation_steps']} "
            f"violation steps, got {len(steps)}"
        )

    @pytest.mark.parametrize("config_idx", [0, 1])
    def test_violation_steps_contiguous(self, results, config_idx):
        """WCV_taumod is locally convex — violation steps must be contiguous."""
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        steps = sorted(a.get("violation_steps", []))
        if len(steps) > 1:
            for i in range(1, len(steps)):
                assert steps[i] == steps[i-1] + 1, (
                    f"Violation steps not contiguous at index {i}: "
                    f"{steps[i-1]} -> {steps[i]}"
                )


class TestCrossingScenario:
    """Crossing encounter with vertical offset — tests vertical constraint."""

    @pytest.mark.parametrize("config_idx", [2, 3])
    def test_has_violation(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert a is not None
        assert a["has_violation"] is True

    def test_standard_vertical_constraint(self, results):
        """With standard config (ZTHR=450ft, TCOA=0), the vertical separation
        of 550ft means vertical WCV doesn't activate until t=20s when
        |550 - 5*20| = 450ft. This must shift the WCV entry from the
        horizontal-only entry (~10.2s) to t=20.0."""
        a = find_analysis(results, "crossing", "standard_dwc")
        assert a is not None
        # Entry should be at or very near 20.0 (vertical constraint)
        assert abs(a["violation_entry_time"] - 20.0) < 0.5, (
            f"crossing x standard: entry should be ~20.0 (vertical constraint), "
            f"got {a['violation_entry_time']}"
        )
        assert a["first_violation_step"] == 20, (
            f"crossing x standard: first step should be 20, "
            f"got {a['first_violation_step']}"
        )

    def test_buffered_no_vertical_constraint(self, results):
        """With buffered config (ZTHR=750ft), the 550ft offset is within ZTHR
        from the start. Entry should be earlier (~6.3s), driven purely by
        the horizontal taumod constraint."""
        a = find_analysis(results, "crossing", "buffered_dwc")
        assert a is not None
        assert a["violation_entry_time"] < 10.0, (
            f"crossing x buffered: entry should be <10s (no vertical constraint), "
            f"got {a['violation_entry_time']}"
        )
        assert a["first_violation_step"] == 7, (
            f"crossing x buffered: first step should be 7, "
            f"got {a['first_violation_step']}"
        )

    @pytest.mark.parametrize("config_idx", [2, 3])
    def test_last_step(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert a["last_violation_step"] == exp["last_step"], (
            f"crossing x {exp['config']}: last_step expected {exp['last_step']}, "
            f"got {a['last_violation_step']}"
        )

    @pytest.mark.parametrize("config_idx", [2, 3])
    def test_tcpa_dcpa(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert abs(a["tcpa"] - exp["tcpa"]) < 1.0
        assert abs(a["dcpa"] - exp["dcpa"]) < 0.05


class TestOvertakeScenario:
    """Overtake encounter: slow closure from behind with lateral offset."""

    @pytest.mark.parametrize("config_idx", [4, 5])
    def test_has_violation(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert a is not None
        assert a["has_violation"] is True

    @pytest.mark.parametrize("config_idx", [4, 5])
    def test_first_last_step(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert a["first_violation_step"] == exp["first_step"], (
            f"overtake x {exp['config']}: first_step expected {exp['first_step']}, "
            f"got {a['first_violation_step']}"
        )
        assert a["last_violation_step"] == exp["last_step"], (
            f"overtake x {exp['config']}: last_step expected {exp['last_step']}, "
            f"got {a['last_violation_step']}"
        )

    @pytest.mark.parametrize("config_idx", [4, 5])
    def test_violation_interval(self, results, config_idx):
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert abs(a["violation_entry_time"] - exp["entry_time"]) < 0.5
        assert abs(a["violation_exit_time"] - exp["exit_time"]) < 0.5

    @pytest.mark.parametrize("config_idx", [4, 5])
    def test_dcpa_is_lateral_offset(self, results, config_idx):
        """DCPA should equal the lateral offset (0.3 nmi) since both
        aircraft travel along the same track (North)."""
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert abs(a["dcpa"] - 0.3) < 0.05, (
            f"overtake DCPA should be ~0.3 nmi (lateral offset), got {a['dcpa']}"
        )

    @pytest.mark.parametrize("config_idx", [4, 5])
    def test_tcpa(self, results, config_idx):
        """TCPA should be 72.0s for both configs (depends only on geometry)."""
        exp = EXPECTED[config_idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        assert abs(a["tcpa"] - 72.0) < 1.0


class TestViolationStepsConsistency:
    """Cross-check violation_steps against first/last step and interval."""

    @pytest.mark.parametrize("idx", range(6))
    def test_steps_match_first_last(self, results, idx):
        exp = EXPECTED[idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        if not a["has_violation"]:
            return
        steps = a.get("violation_steps", [])
        assert len(steps) > 0, "has_violation=True but no violation_steps"
        assert steps[0] == a["first_violation_step"]
        assert steps[-1] == a["last_violation_step"]

    @pytest.mark.parametrize("idx", range(6))
    def test_steps_contiguous(self, results, idx):
        """WCV_taumod local convexity: violation is a single contiguous interval."""
        exp = EXPECTED[idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        steps = sorted(a.get("violation_steps", []))
        if len(steps) <= 1:
            return
        expected_range = list(range(steps[0], steps[-1] + 1))
        assert steps == expected_range, (
            f"{exp['scenario']} x {exp['config']}: violation steps not contiguous"
        )

    @pytest.mark.parametrize("idx", range(6))
    def test_num_steps(self, results, idx):
        exp = EXPECTED[idx]
        a = find_analysis(results, exp["scenario"], exp["config"])
        steps = a.get("violation_steps", [])
        assert len(steps) == exp["num_violation_steps"], (
            f"{exp['scenario']} x {exp['config']}: expected "
            f"{exp['num_violation_steps']} violation steps, got {len(steps)}"
        )


class TestBufferedWiderThanStandard:
    """Buffered config has wider thresholds, so violations should be
    longer (more steps, earlier entry, later exit) for every violating scenario."""

    @pytest.mark.parametrize("scenario", ["head_on", "crossing", "overtake"])
    def test_buffered_starts_earlier(self, results, scenario):
        std = find_analysis(results, scenario, "standard_dwc")
        buf = find_analysis(results, scenario, "buffered_dwc")
        assert std and buf
        assert buf["first_violation_step"] <= std["first_violation_step"], (
            f"{scenario}: buffered first step ({buf['first_violation_step']}) "
            f"should be <= standard ({std['first_violation_step']})"
        )

    @pytest.mark.parametrize("scenario", ["head_on", "crossing", "overtake"])
    def test_buffered_ends_later(self, results, scenario):
        std = find_analysis(results, scenario, "standard_dwc")
        buf = find_analysis(results, scenario, "buffered_dwc")
        assert std and buf
        assert buf["last_violation_step"] >= std["last_violation_step"], (
            f"{scenario}: buffered last step ({buf['last_violation_step']}) "
            f"should be >= standard ({std['last_violation_step']})"
        )

    @pytest.mark.parametrize("scenario", ["head_on", "crossing", "overtake"])
    def test_buffered_more_steps(self, results, scenario):
        std = find_analysis(results, scenario, "standard_dwc")
        buf = find_analysis(results, scenario, "buffered_dwc")
        assert std and buf
        std_steps = len(std.get("violation_steps", []))
        buf_steps = len(buf.get("violation_steps", []))
        assert buf_steps >= std_steps, (
            f"{scenario}: buffered should have >= steps ({buf_steps} vs {std_steps})"
        )
