
import json
import os
import csv
import pytest

RESULTS_PATH = "/app/output/results.json"
VALIDATION_PATH = "/app/data/validation.csv"
EXPERIMENTS_PATH = "/app/data/experiments.json"
SUBMISSIONS_PATH = "/app/data/submissions.json"


@pytest.fixture
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


@pytest.fixture
def validation():
    rows = {}
    with open(VALIDATION_PATH) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows[row["submission_id"]] = row
    return rows


@pytest.fixture
def experiments():
    with open(EXPERIMENTS_PATH) as f:
        return json.load(f)


@pytest.fixture
def submissions():
    with open(SUBMISSIONS_PATH) as f:
        return json.load(f)


# ---- Structure tests ----

class TestStructure:
    def test_output_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found at /app/output/"

    def test_valid_json(self):
        with open(RESULTS_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_top_level_keys(self, results):
        for key in ("experiments", "evaluations", "summary"):
            assert key in results, f"Missing top-level key: {key}"

    def test_all_experiments_present(self, results, experiments):
        expected_ids = {e["experiment_id"] for e in experiments}
        assert set(results["experiments"].keys()) == expected_ids

    def test_all_submissions_present(self, results, submissions):
        expected_ids = {s["submission_id"] for s in submissions}
        assert set(results["evaluations"].keys()) == expected_ids
        assert set(results["summary"].keys()) == expected_ids

    def test_question_count_per_submission(self, results, experiments):
        total = sum(len(e["runs"][0]) for e in experiments)
        for sub_id, summary in results["summary"].items():
            assert summary["total_questions"] == total, \
                f"{sub_id}: expected {total} questions, got {summary['total_questions']}"


# ---- Aggregate score tests ----

class TestAggregateScores:
    def test_standard_correct_counts(self, results, validation):
        for sub_id, expected in validation.items():
            actual = results["summary"][sub_id]["standard_correct"]
            exp_val = int(expected["standard_correct"])
            assert actual == exp_val, \
                f"{sub_id}: standard_correct={actual}, expected={exp_val}"

    def test_robust_correct_counts(self, results, validation):
        for sub_id, expected in validation.items():
            actual = results["summary"][sub_id]["robust_correct"]
            exp_val = int(expected["robust_correct"])
            assert actual == exp_val, \
                f"{sub_id}: robust_correct={actual}, expected={exp_val}"

    def test_accuracy_values(self, results, validation):
        for sub_id, expected in validation.items():
            summary = results["summary"][sub_id]
            total = int(expected["total_questions"])
            exp_std_acc = int(expected["standard_correct"]) / total
            exp_rob_acc = int(expected["robust_correct"]) / total
            assert abs(summary["standard_accuracy"] - exp_std_acc) < 0.002, \
                f"{sub_id}: standard_accuracy mismatch"
            assert abs(summary["robust_accuracy"] - exp_rob_acc) < 0.002, \
                f"{sub_id}: robust_accuracy mismatch"


# ---- Outlier detection tests ----

class TestOutlierDetection:
    def test_experiments_with_outliers(self, results):
        outlier_exps = set()
        for exp_id, exp_data in results["experiments"].items():
            for key, q in exp_data.items():
                if q.get("outlier_detected") is True:
                    outlier_exps.add(exp_id)
        assert outlier_exps == {"crystal_growth", "spectral_emission"}, \
            f"Expected outliers in crystal_growth and spectral_emission, got {outlier_exps}"

    def test_crystal_growth_rate_has_outlier(self, results):
        q = results["experiments"]["crystal_growth"]["growth_rate"]
        assert q["outlier_detected"] is True

    def test_spectral_line_intensity_has_outlier(self, results):
        q = results["experiments"]["spectral_emission"]["line_intensity"]
        assert q["outlier_detected"] is True

    def test_no_false_outliers(self, results):
        no_outlier_checks = [
            ("thermal_conductivity", "conductivity"),
            ("reaction_kinetics", "rate_constant"),
            ("reaction_kinetics", "activation_energy"),
            ("crystal_growth", "lattice_constant"),
            ("spectral_emission", "peak_wavelength"),
            ("polymer_testing", "yield_strength"),
            ("polymer_testing", "elongation_pct"),
        ]
        for exp_id, key in no_outlier_checks:
            q = results["experiments"][exp_id][key]
            assert q.get("outlier_detected") is False, \
                f"{exp_id}.{key} should not have outlier detected"


# ---- Type classification tests ----

class TestTypeClassification:
    def test_numeric_types(self, results):
        numeric_keys = [
            ("thermal_conductivity", "conductivity"),
            ("reaction_kinetics", "rate_constant"),
            ("reaction_kinetics", "activation_energy"),
            ("crystal_growth", "growth_rate"),
            ("crystal_growth", "lattice_constant"),
            ("spectral_emission", "peak_wavelength"),
            ("spectral_emission", "line_intensity"),
            ("polymer_testing", "yield_strength"),
            ("polymer_testing", "elongation_pct"),
        ]
        for exp_id, key in numeric_keys:
            assert results["experiments"][exp_id][key]["type"] == "numeric", \
                f"{exp_id}.{key} should be numeric"

    def test_string_types(self, results):
        string_keys = [
            ("thermal_conductivity", "medium"),
            ("reaction_kinetics", "reaction_order"),
            ("crystal_growth", "crystal_system"),
            ("spectral_emission", "element"),
            ("polymer_testing", "failure_mode"),
        ]
        for exp_id, key in string_keys:
            assert results["experiments"][exp_id][key]["type"] == "string", \
                f"{exp_id}.{key} should be string"

    def test_list_types(self, results):
        list_keys = [
            ("reaction_kinetics", "products"),
            ("spectral_emission", "spectral_lines"),
            ("polymer_testing", "defect_types"),
        ]
        for exp_id, key in list_keys:
            assert results["experiments"][exp_id][key]["type"] == "list", \
                f"{exp_id}.{key} should be list"


# ---- Standard vs robust divergence tests ----

class TestDivergence:
    def test_noisy_divergence_count(self, results):
        count = 0
        for exp_id, exp_eval in results["evaluations"]["agent_noisy"].items():
            for key, q in exp_eval.items():
                if q["standard_correct"] is True and q["robust_correct"] is False:
                    count += 1
        assert count == 2, \
            f"agent_noisy should have exactly 2 standard-only correct, got {count}"

    def test_noisy_growth_rate_divergence(self, results):
        q = results["evaluations"]["agent_noisy"]["crystal_growth"]["growth_rate"]
        assert q["standard_correct"] is True, "growth_rate should be standard_correct"
        assert q["robust_correct"] is False, "growth_rate should not be robust_correct"

    def test_noisy_line_intensity_divergence(self, results):
        q = results["evaluations"]["agent_noisy"]["spectral_emission"]["line_intensity"]
        assert q["standard_correct"] is True, "line_intensity should be standard_correct"
        assert q["robust_correct"] is False, "line_intensity should not be robust_correct"

    def test_precise_no_divergence(self, results):
        for exp_id, exp_eval in results["evaluations"]["agent_precise"].items():
            for key, q in exp_eval.items():
                if q["standard_correct"]:
                    assert q["robust_correct"], \
                        f"agent_precise {exp_id}.{key}: standard=True but robust=False"

    def test_partial_equal_standard_robust(self, results):
        s = results["summary"]["agent_partial"]
        assert s["standard_correct"] == s["robust_correct"], \
            "agent_partial should have equal standard and robust counts"


# ---- Missing key handling tests ----

class TestMissingKeys:
    def test_partial_null_count(self, results):
        null_count = 0
        for exp_id, exp_eval in results["evaluations"]["agent_partial"].items():
            for key, q in exp_eval.items():
                if q["submitted"] is None:
                    null_count += 1
        assert null_count == 4, f"agent_partial should have 4 null submissions, got {null_count}"

    def test_partial_null_all_incorrect(self, results):
        for exp_id, exp_eval in results["evaluations"]["agent_partial"].items():
            for key, q in exp_eval.items():
                if q["submitted"] is None:
                    assert q["standard_correct"] is False, \
                        f"Null submission {exp_id}.{key} should be standard_correct=False"
                    assert q["robust_correct"] is False, \
                        f"Null submission {exp_id}.{key} should be robust_correct=False"


# ---- Case insensitivity tests ----

class TestCaseHandling:
    def test_precise_case_variant_strings(self, results):
        case_variant_keys = [
            ("thermal_conductivity", "medium"),
            ("reaction_kinetics", "reaction_order"),
            ("crystal_growth", "crystal_system"),
            ("spectral_emission", "element"),
            ("polymer_testing", "failure_mode"),
        ]
        for exp_id, key in case_variant_keys:
            q = results["evaluations"]["agent_precise"][exp_id][key]
            assert q["standard_correct"] is True, \
                f"agent_precise {exp_id}.{key} should match case-insensitively"
            assert q["robust_correct"] is True


# ---- Percentage coercion tests ----

class TestPercentageCoercion:
    def test_noisy_yield_strength_pct(self, results):
        q = results["evaluations"]["agent_noisy"]["polymer_testing"]["yield_strength"]
        assert q["submitted"] == "42.8%"
        assert q["standard_correct"] is True, "'42.8%' should be coerced and match"

    def test_noisy_activation_energy_pct(self, results):
        q = results["evaluations"]["agent_noisy"]["reaction_kinetics"]["activation_energy"]
        assert q["submitted"] == "45.5%"
        assert q["standard_correct"] is True, "'45.5%' should be coerced and match"


# ---- Robust interval consistency ----

class TestRobustConsistency:
    def test_no_outlier_means_equal_intervals(self, results):
        for sub_id in results["evaluations"]:
            for exp_id in results["evaluations"][sub_id]:
                for key, q in results["evaluations"][sub_id][exp_id].items():
                    exp_q = results["experiments"][exp_id][key]
                    if exp_q["type"] == "numeric" and not exp_q.get("outlier_detected"):
                        assert q["standard_correct"] == q["robust_correct"], \
                            f"{sub_id}/{exp_id}/{key}: no outlier but std!=robust"

    def test_robust_leq_standard(self, results):
        for sub_id, summary in results["summary"].items():
            assert summary["robust_correct"] <= summary["standard_correct"], \
                f"{sub_id}: robust_correct > standard_correct"
