
import json
import os
import pytest


REPORT_PATH = "/app/results/report.json"


class TestPipelineExecution:
    def test_nextflow_was_executed(self):
        """Verify the pipeline was run through Nextflow."""
        assert os.path.isfile("/app/.nextflow.log"), (
            "Nextflow log not found at /app/.nextflow.log. "
            "The pipeline must be executed through Nextflow."
        )

    def test_report_file_exists(self):
        assert os.path.isfile(REPORT_PATH), (
            f"Expected report at {REPORT_PATH} but file does not exist. "
            "The pipeline must be run successfully to produce this output."
        )

    def test_report_is_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list), "report.json root must be a JSON array"


class TestReportStructure:
    @pytest.fixture(autouse=True)
    def load_report(self):
        with open(REPORT_PATH) as f:
            self.data = json.load(f)
        self.data.sort(key=lambda x: x["experiment"])

    def test_experiment_count(self):
        assert len(self.data) == 3, (
            f"Expected exactly 3 experiment entries, got {len(self.data)}"
        )

    def test_experiment_names(self):
        names = [entry["experiment"] for entry in self.data]
        assert names == ["EXP_A", "EXP_B", "EXP_C"], (
            f"Expected experiments ['EXP_A', 'EXP_B', 'EXP_C'], got {names}"
        )

    def test_required_fields(self):
        required = {
            "experiment", "num_samples", "total_measurements",
            "grand_mean", "expected_mean", "deviation", "tolerance",
            "within_tolerance", "high_priority_count", "low_priority_count",
        }
        for entry in self.data:
            missing = required - set(entry.keys())
            assert not missing, (
                f"Experiment {entry.get('experiment', '?')} missing fields: {missing}"
            )

    def test_field_types(self):
        for entry in self.data:
            exp = entry["experiment"]
            assert isinstance(entry["num_samples"], int), (
                f"{exp}: num_samples should be int"
            )
            assert isinstance(entry["total_measurements"], int), (
                f"{exp}: total_measurements should be int"
            )
            assert isinstance(entry["grand_mean"], (int, float)), (
                f"{exp}: grand_mean should be numeric"
            )
            assert isinstance(entry["expected_mean"], (int, float)), (
                f"{exp}: expected_mean should be numeric"
            )
            assert isinstance(entry["deviation"], (int, float)), (
                f"{exp}: deviation should be numeric"
            )
            assert isinstance(entry["tolerance"], (int, float)), (
                f"{exp}: tolerance should be numeric"
            )
            assert isinstance(entry["within_tolerance"], bool), (
                f"{exp}: within_tolerance should be bool"
            )
            assert isinstance(entry["high_priority_count"], int), (
                f"{exp}: high_priority_count should be int"
            )
            assert isinstance(entry["low_priority_count"], int), (
                f"{exp}: low_priority_count should be int"
            )


class TestEXPA:
    """EXP_A: S001(high, weighted_mean=42.0829, count=3),
              S002(low, filtered_mean=43.5, count=1),
              S005(low, filtered_mean=44.0, count=1)
    Grand mean = (42.0829*3 + 43.5 + 44.0) / 5 = 42.75
    Deviation from reference 42.5 = 0.25, tolerance 0.2 -> false"""

    @pytest.fixture(autouse=True)
    def load_exp(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        data.sort(key=lambda x: x["experiment"])
        self.entry = data[0]
        assert self.entry["experiment"] == "EXP_A"

    def test_num_samples(self):
        assert self.entry["num_samples"] == 3

    def test_total_measurements(self):
        assert self.entry["total_measurements"] == 5

    def test_grand_mean(self):
        assert self.entry["grand_mean"] == pytest.approx(42.75, abs=0.05)

    def test_expected_mean(self):
        assert self.entry["expected_mean"] == pytest.approx(42.5, abs=0.01)

    def test_deviation(self):
        assert self.entry["deviation"] == pytest.approx(0.25, abs=0.05)

    def test_tolerance(self):
        assert self.entry["tolerance"] == pytest.approx(0.2, abs=0.01)

    def test_within_tolerance(self):
        assert self.entry["within_tolerance"] is False

    def test_high_priority_count(self):
        assert self.entry["high_priority_count"] == 1

    def test_low_priority_count(self):
        assert self.entry["low_priority_count"] == 2


class TestEXPB:
    """EXP_B: S003(high, weighted_mean=37.3839, count=4),
              S004(high, weighted_mean=38.7581, count=2),
              S008(low, filtered_mean=42.0, count=1)
    Grand mean = (37.3839*4 + 38.7581*2 + 42.0) / 7 = 38.44
    Deviation from reference 38.0 = 0.44, tolerance 3.0 -> true"""

    @pytest.fixture(autouse=True)
    def load_exp(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        data.sort(key=lambda x: x["experiment"])
        self.entry = data[1]
        assert self.entry["experiment"] == "EXP_B"

    def test_num_samples(self):
        assert self.entry["num_samples"] == 3

    def test_total_measurements(self):
        assert self.entry["total_measurements"] == 7

    def test_grand_mean(self):
        assert self.entry["grand_mean"] == pytest.approx(38.44, abs=0.05)

    def test_expected_mean(self):
        assert self.entry["expected_mean"] == pytest.approx(38.0, abs=0.01)

    def test_deviation(self):
        assert self.entry["deviation"] == pytest.approx(0.44, abs=0.05)

    def test_tolerance(self):
        assert self.entry["tolerance"] == pytest.approx(3.0, abs=0.01)

    def test_within_tolerance(self):
        assert self.entry["within_tolerance"] is True

    def test_high_priority_count(self):
        assert self.entry["high_priority_count"] == 2

    def test_low_priority_count(self):
        assert self.entry["low_priority_count"] == 1


class TestEXPC:
    """EXP_C: S006(high, weighted_mean=55.0683, count=5),
              S007(low, filtered_mean=53.5, count=2)
    Grand mean = (55.0683*5 + 53.5*2) / 7 = 54.62
    Deviation from reference 55.0 = 0.38, tolerance 8.0 -> true"""

    @pytest.fixture(autouse=True)
    def load_exp(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        data.sort(key=lambda x: x["experiment"])
        self.entry = data[2]
        assert self.entry["experiment"] == "EXP_C"

    def test_num_samples(self):
        assert self.entry["num_samples"] == 2

    def test_total_measurements(self):
        assert self.entry["total_measurements"] == 7

    def test_grand_mean(self):
        assert self.entry["grand_mean"] == pytest.approx(54.62, abs=0.05)

    def test_expected_mean(self):
        assert self.entry["expected_mean"] == pytest.approx(55.0, abs=0.01)

    def test_deviation(self):
        assert self.entry["deviation"] == pytest.approx(0.38, abs=0.05)

    def test_tolerance(self):
        assert self.entry["tolerance"] == pytest.approx(8.0, abs=0.01)

    def test_within_tolerance(self):
        assert self.entry["within_tolerance"] is True

    def test_high_priority_count(self):
        assert self.entry["high_priority_count"] == 1

    def test_low_priority_count(self):
        assert self.entry["low_priority_count"] == 1
