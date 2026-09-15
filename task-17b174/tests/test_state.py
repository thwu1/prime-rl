
import csv
import copy
import json
import os
import subprocess
import pytest

TOLERANCE = 0.002

SCORER_CMD = [
    "python3", "/app/scorer.py",
    "--reference", "/app/data/reference.json",
    "--system-output", "/app/data/system_output.json",
    "--activity-index", "/app/data/activity_index.json",
    "--file-index", "/app/data/file_index.json",
    "--scoring-parameters", "/app/data/scoring_parameters.json",
    "--output-dir", "/app/output",
]

BY_ACTIVITY_PATH = "/app/output/scores_by_activity.csv"
AGGREGATED_PATH = "/app/output/scores_aggregated.csv"
EXPECTED_BY_ACTIVITY_PATH = "/app/expected/scores_by_activity.csv"
EXPECTED_AGGREGATED_PATH = "/app/expected/scores_aggregated.csv"

# ---- Expected values (collar=50) ----

EXPECTED_ACTIVITY_METRICS = {
    "PersonRuns": {
        "num_ref": 4, "num_sys": 6, "num_correct": 4,
        "num_missed": 0, "num_false_alarm": 2,
        "p_miss_at_rfa_0.03": 0.25, "p_miss_at_rfa_0.1": 0.0,
        "p_miss_at_rfa_0.2": 0.0, "p_miss_at_rfa_0.5": 0.0,
        "naudc_at_rfa_0.1": 0.25, "naudc_at_rfa_0.2": 0.125,
        "naudc_at_rfa_0.5": 0.05, "n_mide": 0.21054,
    },
    "VehicleTurnsRight": {
        "num_ref": 2, "num_sys": 4, "num_correct": 2,
        "num_missed": 0, "num_false_alarm": 2,
        "p_miss_at_rfa_0.03": 0.0, "p_miss_at_rfa_0.1": 0.0,
        "p_miss_at_rfa_0.2": 0.0, "p_miss_at_rfa_0.5": 0.0,
        "naudc_at_rfa_0.1": 0.0, "naudc_at_rfa_0.2": 0.0,
        "naudc_at_rfa_0.5": 0.0, "n_mide": 0.04834,
    },
    "Loitering": {
        "num_ref": 2, "num_sys": 2, "num_correct": 1,
        "num_missed": 1, "num_false_alarm": 1,
        "p_miss_at_rfa_0.03": 0.5, "p_miss_at_rfa_0.1": 0.5,
        "p_miss_at_rfa_0.2": 0.5, "p_miss_at_rfa_0.5": 0.5,
        "naudc_at_rfa_0.1": 0.25, "naudc_at_rfa_0.2": 0.125,
        "naudc_at_rfa_0.5": 0.05, "n_mide": 0.50888,
    },
}

EXPECTED_AGGREGATED = {
    "p_miss_at_rfa_0.5": 0.16667,
    "p_miss_at_rfa_0.2": 0.16667,
    "p_miss_at_rfa_0.1": 0.16667,
    "p_miss_at_rfa_0.03": 0.25,
    "naudc_at_rfa_0.5": 0.03333,
    "naudc_at_rfa_0.2": 0.08333,
    "naudc_at_rfa_0.1": 0.16667,
    "n_mide": 0.25592,
}

INT_FIELDS = {"num_ref", "num_sys", "num_correct", "num_missed", "num_false_alarm"}


def _run_scorer(extra_args=None):
    """Run the scorer and return the subprocess result."""
    cmd = list(SCORER_CMD)
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, cwd="/app",
    )
    return result


def _parse_by_activity_csv(path):
    """Parse scores_by_activity.csv into a dict of {activity: {metric: value}}."""
    data = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            activity = row["activity"]
            metrics = {}
            for key, val in row.items():
                if key == "activity":
                    continue
                if key in INT_FIELDS:
                    metrics[key] = int(val)
                else:
                    metrics[key] = float(val)
            data[activity] = metrics
    return data


def _parse_aggregated_csv(path):
    """Parse scores_aggregated.csv into a dict of {metric: value}."""
    data = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row["metric"]] = float(row["value"])
    return data


class TestScorerExecution:
    """Verify the scorer runs and produces output files."""

    def test_scorer_exists(self):
        assert os.path.exists("/app/scorer.py"), "scorer.py not found"

    def test_scorer_runs_successfully(self):
        result = _run_scorer()
        assert result.returncode == 0, (
            f"Scorer failed with code {result.returncode}:\n"
            f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
        )

    def test_by_activity_csv_created(self):
        _run_scorer()
        assert os.path.exists(BY_ACTIVITY_PATH), (
            "scores_by_activity.csv not produced"
        )

    def test_aggregated_csv_created(self):
        _run_scorer()
        assert os.path.exists(AGGREGATED_PATH), (
            "scores_aggregated.csv not produced"
        )


class TestCSVStructure:
    """Verify CSV files have correct structure."""

    @pytest.fixture(autouse=True)
    def run_scorer(self):
        _run_scorer()

    def test_by_activity_has_header(self):
        with open(BY_ACTIVITY_PATH) as f:
            reader = csv.reader(f)
            header = next(reader)
        assert "activity" in header
        assert "n_mide" in header

    def test_by_activity_has_all_activities(self):
        data = _parse_by_activity_csv(BY_ACTIVITY_PATH)
        for act in ["PersonRuns", "VehicleTurnsRight", "Loitering"]:
            assert act in data, f"Activity {act} missing from CSV"

    def test_by_activity_sorted_alphabetically(self):
        with open(BY_ACTIVITY_PATH) as f:
            reader = csv.DictReader(f)
            activities = [row["activity"] for row in reader]
        assert activities == sorted(activities), (
            f"Activities not alphabetically sorted: {activities}"
        )

    def test_aggregated_has_all_metrics(self):
        data = _parse_aggregated_csv(AGGREGATED_PATH)
        for metric in EXPECTED_AGGREGATED:
            assert metric in data, f"Metric {metric} missing from aggregated CSV"

    def test_aggregated_sorted_alphabetically(self):
        with open(AGGREGATED_PATH) as f:
            reader = csv.DictReader(f)
            metrics = [row["metric"] for row in reader]
        assert metrics == sorted(metrics), (
            f"Metrics not alphabetically sorted: {metrics}"
        )


class TestInstanceCounts:
    """Verify instance counts per activity."""

    @pytest.fixture(autouse=True)
    def run_scorer(self):
        _run_scorer()

    @pytest.mark.parametrize("activity", ["PersonRuns", "VehicleTurnsRight", "Loitering"])
    def test_instance_counts(self, activity):
        data = _parse_by_activity_csv(BY_ACTIVITY_PATH)
        actual = data[activity]
        expected = EXPECTED_ACTIVITY_METRICS[activity]
        for field in INT_FIELDS:
            assert actual[field] == expected[field], (
                f"{activity}/{field}: expected {expected[field]}, got {actual[field]}"
            )


class TestPmissAtRfa:
    """Verify P_miss@RFA values per activity and aggregated."""

    @pytest.fixture(autouse=True)
    def run_scorer(self):
        _run_scorer()

    @pytest.mark.parametrize("activity", ["PersonRuns", "VehicleTurnsRight", "Loitering"])
    @pytest.mark.parametrize("target", ["0.5", "0.2", "0.1", "0.03"])
    def test_pmiss_per_activity(self, activity, target):
        data = _parse_by_activity_csv(BY_ACTIVITY_PATH)
        key = f"p_miss_at_rfa_{target}"
        actual = data[activity][key]
        expected = EXPECTED_ACTIVITY_METRICS[activity][key]
        assert abs(actual - expected) < TOLERANCE, (
            f"{activity}/{key}: expected {expected}, got {actual}"
        )

    @pytest.mark.parametrize("target", ["0.5", "0.2", "0.1", "0.03"])
    def test_pmiss_aggregated(self, target):
        data = _parse_aggregated_csv(AGGREGATED_PATH)
        key = f"p_miss_at_rfa_{target}"
        assert abs(data[key] - EXPECTED_AGGREGATED[key]) < TOLERANCE, (
            f"aggregated/{key}: expected {EXPECTED_AGGREGATED[key]}, got {data[key]}"
        )


class TestNaudc:
    """Verify nAUDC values per activity and aggregated."""

    @pytest.fixture(autouse=True)
    def run_scorer(self):
        _run_scorer()

    @pytest.mark.parametrize("activity", ["PersonRuns", "VehicleTurnsRight", "Loitering"])
    @pytest.mark.parametrize("target", ["0.5", "0.2", "0.1"])
    def test_naudc_per_activity(self, activity, target):
        data = _parse_by_activity_csv(BY_ACTIVITY_PATH)
        key = f"naudc_at_rfa_{target}"
        actual = data[activity][key]
        expected = EXPECTED_ACTIVITY_METRICS[activity][key]
        assert abs(actual - expected) < TOLERANCE, (
            f"{activity}/{key}: expected {expected}, got {actual}"
        )

    @pytest.mark.parametrize("target", ["0.5", "0.2", "0.1"])
    def test_naudc_aggregated(self, target):
        data = _parse_aggregated_csv(AGGREGATED_PATH)
        key = f"naudc_at_rfa_{target}"
        assert abs(data[key] - EXPECTED_AGGREGATED[key]) < TOLERANCE, (
            f"aggregated/{key}: expected {EXPECTED_AGGREGATED[key]}, got {data[key]}"
        )


class TestNmide:
    """Verify N-MIDE values (with collar=50) per activity and aggregated."""

    @pytest.fixture(autouse=True)
    def run_scorer(self):
        _run_scorer()

    @pytest.mark.parametrize("activity", ["PersonRuns", "VehicleTurnsRight", "Loitering"])
    def test_nmide_per_activity(self, activity):
        data = _parse_by_activity_csv(BY_ACTIVITY_PATH)
        actual = data[activity]["n_mide"]
        expected = EXPECTED_ACTIVITY_METRICS[activity]["n_mide"]
        assert abs(actual - expected) < TOLERANCE, (
            f"{activity}/n_mide: expected {expected}, got {actual}"
        )

    def test_nmide_aggregated(self):
        data = _parse_aggregated_csv(AGGREGATED_PATH)
        assert abs(data["n_mide"] - EXPECTED_AGGREGATED["n_mide"]) < TOLERANCE, (
            f"aggregated/n_mide: expected {EXPECTED_AGGREGATED['n_mide']}, "
            f"got {data['n_mide']}"
        )


class TestMatchesExpectedCSV:
    """Verify output matches the expected CSV files exactly (within tolerance)."""

    @pytest.fixture(autouse=True)
    def run_scorer(self):
        _run_scorer()

    def test_by_activity_matches_expected(self):
        actual = _parse_by_activity_csv(BY_ACTIVITY_PATH)
        expected = _parse_by_activity_csv(EXPECTED_BY_ACTIVITY_PATH)
        assert set(actual.keys()) == set(expected.keys()), (
            f"Activity sets differ: {set(actual.keys())} vs {set(expected.keys())}"
        )
        for act in expected:
            for key in expected[act]:
                if key in INT_FIELDS:
                    assert actual[act][key] == expected[act][key], (
                        f"{act}/{key}: expected {expected[act][key]}, "
                        f"got {actual[act][key]}"
                    )
                else:
                    assert abs(actual[act][key] - expected[act][key]) < TOLERANCE, (
                        f"{act}/{key}: expected {expected[act][key]}, "
                        f"got {actual[act][key]}"
                    )

    def test_aggregated_matches_expected(self):
        actual = _parse_aggregated_csv(AGGREGATED_PATH)
        expected = _parse_aggregated_csv(EXPECTED_AGGREGATED_PATH)
        assert set(actual.keys()) == set(expected.keys()), (
            f"Metric sets differ: {set(actual.keys())} vs {set(expected.keys())}"
        )
        for metric in expected:
            assert abs(actual[metric] - expected[metric]) < TOLERANCE, (
                f"{metric}: expected {expected[metric]}, got {actual[metric]}"
            )


class TestAntiCheat:
    """Modify input data and verify output changes correctly."""

    def test_modified_input_produces_different_output(self):
        """Remove a detection and verify the scorer recomputes correctly."""
        sys_path = "/app/data/system_output.json"
        with open(sys_path) as f:
            original = json.load(f)

        # Remove PersonRuns detection with conf=0.25 (matches R4)
        modified = copy.deepcopy(original)
        modified["activities"] = [
            a for a in modified["activities"]
            if not (a["activity"] == "PersonRuns" and a["presenceConf"] == 0.25)
        ]

        try:
            with open(sys_path, "w") as f:
                json.dump(modified, f)

            # Clear previous output
            for fname in [BY_ACTIVITY_PATH, AGGREGATED_PATH]:
                if os.path.exists(fname):
                    os.remove(fname)

            result = _run_scorer()
            assert result.returncode == 0, (
                f"Scorer failed on modified data: {result.stderr}"
            )
            assert os.path.exists(BY_ACTIVITY_PATH), (
                "No by_activity CSV after modified run"
            )

            data = _parse_by_activity_csv(BY_ACTIVITY_PATH)
            pr = data["PersonRuns"]

            # With S6 removed, R4 is always missed
            assert pr["num_correct"] == 3, (
                f"Modified: expected num_correct=3, got {pr['num_correct']}"
            )
            assert pr["num_missed"] == 1, (
                f"Modified: expected num_missed=1, got {pr['num_missed']}"
            )
            # p_miss@rfa_0.1 should now be 0.25 (was 0.0)
            assert abs(pr["p_miss_at_rfa_0.1"] - 0.25) < TOLERANCE, (
                f"Modified: expected p_miss@0.1=0.25, "
                f"got {pr['p_miss_at_rfa_0.1']}"
            )
            # N-MIDE should change to ~0.13258 (was 0.21054)
            assert abs(pr["n_mide"] - 0.13258) < TOLERANCE, (
                f"Modified: expected n_mide~0.13258, got {pr['n_mide']}"
            )
        finally:
            with open(sys_path, "w") as f:
                json.dump(original, f)

    def test_collar_zero_produces_different_nmide(self):
        """Run with collar=0 and verify N-MIDE changes."""
        params_path = "/app/data/scoring_parameters.json"
        with open(params_path) as f:
            original_params = json.load(f)

        modified_params = copy.deepcopy(original_params)
        modified_params["nmide_collar_size"] = 0

        try:
            with open(params_path, "w") as f:
                json.dump(modified_params, f)

            for fname in [BY_ACTIVITY_PATH, AGGREGATED_PATH]:
                if os.path.exists(fname):
                    os.remove(fname)

            result = _run_scorer()
            assert result.returncode == 0, (
                f"Scorer failed with collar=0: {result.stderr}"
            )

            data = _parse_by_activity_csv(BY_ACTIVITY_PATH)

            # With collar=0, PersonRuns N-MIDE should be ~0.30556 (vs 0.21054)
            assert abs(data["PersonRuns"]["n_mide"] - 0.30556) < TOLERANCE, (
                f"collar=0 PersonRuns n_mide: expected ~0.30556, "
                f"got {data['PersonRuns']['n_mide']}"
            )
            # VehicleTurnsRight N-MIDE should be ~0.08908 (vs 0.04834)
            assert abs(data["VehicleTurnsRight"]["n_mide"] - 0.08908) < TOLERANCE, (
                f"collar=0 VTR n_mide: expected ~0.08908, "
                f"got {data['VehicleTurnsRight']['n_mide']}"
            )
        finally:
            with open(params_path, "w") as f:
                json.dump(original_params, f)

    def test_iou_threshold_affects_alignment(self):
        """Raise IoU threshold and verify alignment changes."""
        params_path = "/app/data/scoring_parameters.json"
        with open(params_path) as f:
            original_params = json.load(f)

        modified_params = copy.deepcopy(original_params)
        modified_params["iou_threshold"] = 0.5

        try:
            with open(params_path, "w") as f:
                json.dump(modified_params, f)

            for fname in [BY_ACTIVITY_PATH, AGGREGATED_PATH]:
                if os.path.exists(fname):
                    os.remove(fname)

            result = _run_scorer()
            assert result.returncode == 0, (
                f"Scorer failed with IoU threshold 0.5: {result.stderr}"
            )

            data = _parse_by_activity_csv(BY_ACTIVITY_PATH)

            # PersonRuns: R4-S6 IoU=0.500 exactly, not strictly > 0.5
            assert data["PersonRuns"]["num_correct"] == 3, (
                f"IoU=0.5: PersonRuns num_correct expected 3, "
                f"got {data['PersonRuns']['num_correct']}"
            )
            assert data["PersonRuns"]["num_missed"] == 1, (
                f"IoU=0.5: PersonRuns num_missed expected 1, "
                f"got {data['PersonRuns']['num_missed']}"
            )

            # Loitering: R7-S11 IoU~0.417 < 0.5, alignment drops entirely
            assert data["Loitering"]["num_correct"] == 0, (
                f"IoU=0.5: Loitering num_correct expected 0, "
                f"got {data['Loitering']['num_correct']}"
            )
            assert data["Loitering"]["num_missed"] == 2, (
                f"IoU=0.5: Loitering num_missed expected 2, "
                f"got {data['Loitering']['num_missed']}"
            )

            # With zero Loitering matches, p_miss must be 1.0 at all targets
            assert abs(data["Loitering"]["p_miss_at_rfa_0.5"] - 1.0) < TOLERANCE, (
                f"IoU=0.5: Loitering p_miss@0.5 expected 1.0, "
                f"got {data['Loitering']['p_miss_at_rfa_0.5']}"
            )

            # N-MIDE should be 0.0 when no pairs are matched
            assert abs(data["Loitering"]["n_mide"] - 0.0) < TOLERANCE, (
                f"IoU=0.5: Loitering n_mide expected 0.0, "
                f"got {data['Loitering']['n_mide']}"
            )

            # VehicleTurnsRight should be unchanged (both IoUs > 0.5)
            assert data["VehicleTurnsRight"]["num_correct"] == 2, (
                f"IoU=0.5: VTR num_correct expected 2, "
                f"got {data['VehicleTurnsRight']['num_correct']}"
            )
        finally:
            with open(params_path, "w") as f:
                json.dump(original_params, f)
