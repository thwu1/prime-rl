"""

Pytest tests for Eurobench gait analysis PI pipeline with reliability assessment.
Validates output correctness, internal consistency, gait event cleaning,
ICC reliability, and measurement quality classification.
"""

import os
import csv
import math
import yaml
import pytest
import statistics


EXPECTED = {
    (1, 1): dict(
        knee_rom_r=60.0, knee_rom_l=60.0,
        hip_rom_r=40.0, hip_rom_l=40.0,
        ankle_rom_r=30.0, ankle_rom_l=30.0,
        stride_time=1.10, cadence=109.09,
        sal_approx=0.88,
    ),
    (1, 2): dict(
        knee_rom_r=65.0, knee_rom_l=65.0,
        hip_rom_r=45.0, hip_rom_l=45.0,
        ankle_rom_r=35.0, ankle_rom_l=35.0,
        stride_time=1.25, cadence=96.0,
        sal_approx=0.84,
    ),
    (2, 1): dict(
        knee_rom_r=48.0, knee_rom_l=43.2,
        hip_rom_r=32.0, hip_rom_l=28.8,
        ankle_rom_r=22.0, ankle_rom_l=19.8,
        stride_time=1.35, cadence=88.89,
        sal_approx=0.67,
    ),
    (2, 2): dict(
        knee_rom_r=50.0, knee_rom_l=44.0,
        hip_rom_r=35.0, hip_rom_l=30.8,
        ankle_rom_r=25.0, ankle_rom_l=22.0,
        stride_time=1.50, cadence=80.0,
        sal_approx=0.62,
    ),
}


def load_pi(subj, cond, run):
    path = f"/app/output/subject_{subj}_cond_{cond}_run_{run}_pi.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 1. File existence
# ---------------------------------------------------------------------------

class TestOutputFileExistence:
    @pytest.mark.parametrize("subj,cond,run", [
        (s, c, r) for s in [1, 2] for c in [1, 2] for r in [1, 2, 3]
    ])
    def test_per_run_pi_files_exist(self, subj, cond, run):
        path = f"/app/output/subject_{subj}_cond_{cond}_run_{run}_pi.yaml"
        assert os.path.exists(path), f"Missing output file: {path}"

    def test_sal_scores_file_exists(self):
        assert os.path.exists("/app/output/sal_scores.csv")

    def test_condition_comparison_file_exists(self):
        assert os.path.exists("/app/output/condition_comparison.csv")

    def test_reliability_report_file_exists(self):
        assert os.path.exists("/app/output/reliability_report.csv")

    def test_quality_classification_file_exists(self):
        assert os.path.exists("/app/output/quality_classification.csv")

    def test_pipeline_entry_point_exists(self):
        assert os.path.exists("/app/run_pipeline.sh")


# ---------------------------------------------------------------------------
# 2. PI YAML format
# ---------------------------------------------------------------------------

class TestPIFormat:
    REQUIRED_KEYS = [
        "hip_rom_r", "hip_rom_l", "knee_rom_r", "knee_rom_l",
        "ankle_rom_r", "ankle_rom_l", "stride_time",
        "cadence", "stride_time_cv", "knee_rom_symmetry",
    ]
    ROM_KEYS = [
        "hip_rom_r", "hip_rom_l", "knee_rom_r", "knee_rom_l",
        "ankle_rom_r", "ankle_rom_l", "stride_time",
    ]

    def test_required_keys_present(self):
        pi = load_pi(1, 1, 1)
        for key in self.REQUIRED_KEYS:
            assert key in pi, f"Missing required key: {key}"

    def test_rom_keys_have_mean_std(self):
        pi = load_pi(1, 1, 1)
        for key in self.ROM_KEYS:
            assert isinstance(pi[key], dict), f"{key} should be dict with mean/std"
            assert "mean" in pi[key], f"{key} missing 'mean'"
            assert "std" in pi[key], f"{key} missing 'std'"


# ---------------------------------------------------------------------------
# 3. Gait event cleaning verification
# ---------------------------------------------------------------------------

class TestGaitEventCleaning:
    def test_stride_time_within_physiological_bounds(self):
        """Mean stride time must be plausible — catches uncleaned artifacts."""
        for subj in [1, 2]:
            for cond in [1, 2]:
                for run in [1, 2, 3]:
                    pi = load_pi(subj, cond, run)
                    mean_st = pi["stride_time"]["mean"]
                    assert 0.6 < mean_st < 2.5, (
                        f"S{subj}C{cond}R{run}: stride time {mean_st:.3f} "
                        f"out of physiological range"
                    )

    def test_stride_variability_not_inflated(self):
        """CV should be small — inflated values indicate uncleaned artifacts."""
        for subj in [1, 2]:
            for cond in [1, 2]:
                for run in [1, 2, 3]:
                    pi = load_pi(subj, cond, run)
                    cv = pi["stride_time_cv"]
                    assert cv < 0.15, (
                        f"S{subj}C{cond}R{run}: CV {cv:.4f} too high — "
                        f"possible uncleaned gait event artifacts"
                    )

    def test_run_consistency_knee_rom(self):
        """ROM across 3 runs of the same context should be consistent."""
        for subj in [1, 2]:
            for cond in [1, 2]:
                vals = [
                    load_pi(subj, cond, run)["knee_rom_r"]["mean"]
                    for run in [1, 2, 3]
                ]
                mean_v = statistics.mean(vals)
                std_v = statistics.stdev(vals)
                cv = std_v / mean_v if mean_v > 0 else 0
                assert cv < 0.12, (
                    f"S{subj}C{cond}: knee_rom_r CV across runs = {cv:.3f}, "
                    f"too variable — possible cleaning failure in some runs"
                )


# ---------------------------------------------------------------------------
# 4. ROM values — filtered ROM should be close to 2*amplitude
# ---------------------------------------------------------------------------

class TestROMValues:
    TOL = 0.08  # 8% relative tolerance

    @pytest.mark.parametrize("subj,cond", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_knee_rom_right(self, subj, cond):
        exp = EXPECTED[(subj, cond)]["knee_rom_r"]
        for run in [1, 2, 3]:
            val = load_pi(subj, cond, run)["knee_rom_r"]["mean"]
            assert abs(val - exp) / exp < self.TOL, (
                f"S{subj}C{cond}R{run} knee_rom_r: expected ~{exp:.1f}, got {val:.2f}"
            )

    @pytest.mark.parametrize("subj,cond", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_knee_rom_left(self, subj, cond):
        exp = EXPECTED[(subj, cond)]["knee_rom_l"]
        for run in [1, 2, 3]:
            val = load_pi(subj, cond, run)["knee_rom_l"]["mean"]
            assert abs(val - exp) / exp < self.TOL, (
                f"S{subj}C{cond}R{run} knee_rom_l: expected ~{exp:.1f}, got {val:.2f}"
            )

    @pytest.mark.parametrize("subj,cond", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_hip_rom_right(self, subj, cond):
        exp = EXPECTED[(subj, cond)]["hip_rom_r"]
        for run in [1, 2, 3]:
            val = load_pi(subj, cond, run)["hip_rom_r"]["mean"]
            assert abs(val - exp) / exp < self.TOL, (
                f"S{subj}C{cond}R{run} hip_rom_r: expected ~{exp:.1f}, got {val:.2f}"
            )

    @pytest.mark.parametrize("subj,cond", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_hip_rom_left(self, subj, cond):
        exp = EXPECTED[(subj, cond)]["hip_rom_l"]
        for run in [1, 2, 3]:
            val = load_pi(subj, cond, run)["hip_rom_l"]["mean"]
            assert abs(val - exp) / exp < self.TOL, (
                f"S{subj}C{cond}R{run} hip_rom_l: expected ~{exp:.1f}, got {val:.2f}"
            )

    @pytest.mark.parametrize("subj,cond", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_ankle_rom_right(self, subj, cond):
        exp = EXPECTED[(subj, cond)]["ankle_rom_r"]
        for run in [1, 2, 3]:
            val = load_pi(subj, cond, run)["ankle_rom_r"]["mean"]
            assert abs(val - exp) / exp < self.TOL, (
                f"S{subj}C{cond}R{run} ankle_rom_r: expected ~{exp:.1f}, got {val:.2f}"
            )

    @pytest.mark.parametrize("subj,cond", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_ankle_rom_left(self, subj, cond):
        exp = EXPECTED[(subj, cond)]["ankle_rom_l"]
        for run in [1, 2, 3]:
            val = load_pi(subj, cond, run)["ankle_rom_l"]["mean"]
            assert abs(val - exp) / exp < self.TOL, (
                f"S{subj}C{cond}R{run} ankle_rom_l: expected ~{exp:.1f}, got {val:.2f}"
            )


# ---------------------------------------------------------------------------
# 5. Stride time
# ---------------------------------------------------------------------------

class TestStrideTime:
    TOL = 0.10

    @pytest.mark.parametrize("subj,cond", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_mean_stride_time(self, subj, cond):
        exp = EXPECTED[(subj, cond)]["stride_time"]
        for run in [1, 2, 3]:
            val = load_pi(subj, cond, run)["stride_time"]["mean"]
            assert abs(val - exp) / exp < self.TOL, (
                f"S{subj}C{cond}R{run} stride_time: expected ~{exp:.2f}, got {val:.4f}"
            )


# ---------------------------------------------------------------------------
# 6. Cadence internal consistency
# ---------------------------------------------------------------------------

class TestCadenceConsistency:
    def test_cadence_equals_120_over_stride_time(self):
        for subj in [1, 2]:
            for cond in [1, 2]:
                for run in [1, 2, 3]:
                    pi = load_pi(subj, cond, run)
                    stride = pi["stride_time"]["mean"]
                    cadence = pi["cadence"]
                    expected = 120.0 / stride
                    assert abs(cadence - expected) / expected < 0.01, (
                        f"S{subj}C{cond}R{run}: cadence {cadence:.2f} "
                        f"!= 120/{stride:.3f} = {expected:.2f}"
                    )


# ---------------------------------------------------------------------------
# 7. Symmetry indices
# ---------------------------------------------------------------------------

class TestSymmetry:
    def test_subject1_symmetric_knee_rom(self):
        """Subject 1 has equal left/right amplitudes — symmetry < 5 %."""
        for cond in [1, 2]:
            for run in [1, 2, 3]:
                pi = load_pi(1, cond, run)
                assert pi["knee_rom_symmetry"] < 5.0, (
                    f"S1C{cond}R{run}: symmetry {pi['knee_rom_symmetry']:.2f} "
                    f"should be < 5"
                )

    def test_subject2_asymmetric_knee_rom(self):
        """Subject 2 has 10-12 % amplitude asymmetry — symmetry 5-25 %."""
        for cond in [1, 2]:
            for run in [1, 2, 3]:
                pi = load_pi(2, cond, run)
                sym = pi["knee_rom_symmetry"]
                assert 5.0 < sym < 25.0, (
                    f"S2C{cond}R{run}: symmetry {sym:.2f} not in (5, 25)"
                )


# ---------------------------------------------------------------------------
# 8. Stride time CV
# ---------------------------------------------------------------------------

class TestStrideTimeCV:
    def test_cv_plausible(self):
        for subj in [1, 2]:
            for cond in [1, 2]:
                for run in [1, 2, 3]:
                    cv = load_pi(subj, cond, run)["stride_time_cv"]
                    assert 0.005 < cv < 0.15, (
                        f"S{subj}C{cond}R{run}: CV {cv:.4f} out of range"
                    )

    def test_subject2_higher_variability(self):
        """Subject 2 has higher stride noise — CV should be larger."""
        for cond in [1, 2]:
            s1 = statistics.mean(
                load_pi(1, cond, r)["stride_time_cv"] for r in [1, 2, 3]
            )
            s2 = statistics.mean(
                load_pi(2, cond, r)["stride_time_cv"] for r in [1, 2, 3]
            )
            assert s2 > s1, (
                f"Cond {cond}: S2 CV ({s2:.4f}) should exceed S1 CV ({s1:.4f})"
            )


# ---------------------------------------------------------------------------
# 9. Stance ratio
# ---------------------------------------------------------------------------

class TestStanceRatio:
    def test_stance_ratio_range(self):
        for subj in [1, 2]:
            for cond in [1, 2]:
                for run in [1, 2, 3]:
                    pi = load_pi(subj, cond, run)
                    sr = pi["stance_ratio_r"]["mean"]
                    assert 55.0 < sr < 70.0, (
                        f"S{subj}C{cond}R{run}: stance ratio {sr:.1f} out of range"
                    )


# ---------------------------------------------------------------------------
# 10. SAL scores
# ---------------------------------------------------------------------------

class TestSALScores:
    def _load_sal(self):
        rows = []
        with open("/app/output/sal_scores.csv") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                rows.append({
                    "subject": int(row["subject"].strip()),
                    "condition": int(row["condition"].strip()),
                    "run": int(row["run"].strip()),
                    "sal_score": float(row["sal_score"].strip()),
                })
        return rows

    def test_correct_row_count(self):
        rows = self._load_sal()
        assert len(rows) == 12, f"Expected 12 SAL rows, got {len(rows)}"

    @pytest.mark.parametrize("subj,cond", [(1, 1), (1, 2), (2, 1), (2, 2)])
    def test_sal_value(self, subj, cond):
        expected = EXPECTED[(subj, cond)]["sal_approx"]
        for row in self._load_sal():
            if row["subject"] == subj and row["condition"] == cond:
                assert abs(row["sal_score"] - expected) < 0.15, (
                    f"S{subj}C{cond}R{row['run']}: SAL {row['sal_score']:.3f} "
                    f"expected ~{expected}"
                )

    def test_subject1_higher_than_subject2(self):
        sals = {}
        for row in self._load_sal():
            key = (row["subject"], row["condition"])
            sals.setdefault(key, []).append(row["sal_score"])
        for cond in [1, 2]:
            s1 = statistics.mean(sals[(1, cond)])
            s2 = statistics.mean(sals[(2, cond)])
            assert s1 > s2, (
                f"Cond {cond}: S1 SAL ({s1:.3f}) should exceed S2 ({s2:.3f})"
            )

    def test_sal_in_unit_range(self):
        for row in self._load_sal():
            assert 0.0 <= row["sal_score"] <= 1.0, (
                f"SAL {row['sal_score']} out of [0, 1]"
            )


# ---------------------------------------------------------------------------
# 11. Condition comparison
# ---------------------------------------------------------------------------

class TestConditionComparison:
    def _load_comparison(self):
        rows = []
        with open("/app/output/condition_comparison.csv") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                rows.append({k.strip(): v.strip() for k, v in row.items()})
        return rows

    def test_minimum_metrics(self):
        rows = self._load_comparison()
        assert len(rows) >= 4, f"Expected >= 4 comparison rows, got {len(rows)}"

    def test_required_columns(self):
        rows = self._load_comparison()
        for row in rows:
            for col in ["metric", "cond_1_mean", "cond_2_mean", "direction"]:
                assert col in row, f"Missing column: {col}"

    def test_cadence_decreased_on_slope(self):
        for row in self._load_comparison():
            if row["metric"] == "cadence":
                c1 = float(row["cond_1_mean"])
                c2 = float(row["cond_2_mean"])
                assert c1 > c2, (
                    f"Cadence should decrease on slope: {c1} -> {c2}"
                )
                assert row["direction"] == "decreased"
                return
        pytest.fail("cadence not found in condition comparison")

    def test_direction_values_valid(self):
        valid = {"increased", "decreased", "unchanged"}
        for row in self._load_comparison():
            assert row["direction"] in valid, (
                f"Invalid direction '{row['direction']}' for {row['metric']}"
            )


# ---------------------------------------------------------------------------
# 12. ROM ordering and consistency
# ---------------------------------------------------------------------------

class TestConsistencyWithInput:
    EXPECTED_STRIDE = {
        (1, 1): (0.9, 1.3),
        (1, 2): (1.0, 1.5),
        (2, 1): (1.1, 1.6),
        (2, 2): (1.2, 1.8),
    }

    def test_stride_time_in_expected_range(self):
        for subj in [1, 2]:
            for cond in [1, 2]:
                for run in [1, 2, 3]:
                    pi = load_pi(subj, cond, run)
                    mean_st = pi["stride_time"]["mean"]
                    lo, hi = self.EXPECTED_STRIDE[(subj, cond)]
                    assert lo < mean_st < hi, (
                        f"S{subj}C{cond}R{run}: stride time {mean_st:.3f} "
                        f"outside expected range ({lo}, {hi})"
                    )

    def test_rom_ordering_across_joints(self):
        """Knee ROM > hip ROM > ankle ROM."""
        for subj in [1, 2]:
            for cond in [1, 2]:
                for run in [1, 2, 3]:
                    pi = load_pi(subj, cond, run)
                    knee = pi["knee_rom_r"]["mean"]
                    hip = pi["hip_rom_r"]["mean"]
                    ankle = pi["ankle_rom_r"]["mean"]
                    assert knee > hip > ankle, (
                        f"S{subj}C{cond}R{run}: ROM ordering violated: "
                        f"knee={knee:.1f}, hip={hip:.1f}, ankle={ankle:.1f}"
                    )


# ---------------------------------------------------------------------------
# 13. Reliability analysis (ICC, SEM, MDC)
# ---------------------------------------------------------------------------

class TestReliability:
    def _load_reliability(self):
        rows = []
        with open("/app/output/reliability_report.csv") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                rows.append({k.strip(): v.strip() for k, v in row.items()})
        return rows

    def _get_metric(self, metric_name):
        for row in self._load_reliability():
            if row["metric"] == metric_name:
                return row
        return None

    def test_required_columns(self):
        rows = self._load_reliability()
        assert len(rows) >= 8, f"Expected >= 8 reliability rows, got {len(rows)}"
        for row in rows:
            for col in ["metric", "icc", "sem", "mdc95"]:
                assert col in row, f"Missing column: {col}"

    def test_icc_values_in_valid_range(self):
        for row in self._load_reliability():
            icc = float(row["icc"])
            assert 0.0 <= icc <= 1.0, (
                f"{row['metric']}: ICC {icc} outside [0, 1]"
            )

    def test_icc_knee_rom_high(self):
        """Knee ROM should have excellent reliability with controlled data."""
        row = self._get_metric("knee_rom_r")
        assert row is not None, "knee_rom_r not in reliability report"
        icc = float(row["icc"])
        assert icc > 0.90, f"knee_rom_r ICC {icc:.4f} should be > 0.90"

    def test_icc_hip_rom_high(self):
        row = self._get_metric("hip_rom_r")
        assert row is not None, "hip_rom_r not in reliability report"
        icc = float(row["icc"])
        assert icc > 0.90, f"hip_rom_r ICC {icc:.4f} should be > 0.90"

    def test_icc_stride_time_high(self):
        row = self._get_metric("stride_time")
        assert row is not None, "stride_time not in reliability report"
        icc = float(row["icc"])
        assert icc > 0.85, f"stride_time ICC {icc:.4f} should be > 0.85"

    def test_icc_cadence_high(self):
        row = self._get_metric("cadence")
        assert row is not None, "cadence not in reliability report"
        icc = float(row["icc"])
        assert icc > 0.85, f"cadence ICC {icc:.4f} should be > 0.85"

    def test_sem_positive(self):
        for row in self._load_reliability():
            sem = float(row["sem"])
            assert sem >= 0, f"SEM should be non-negative for {row['metric']}"

    def test_mdc_greater_than_sem(self):
        for row in self._load_reliability():
            sem = float(row["sem"])
            mdc = float(row["mdc95"])
            if sem > 0:
                ratio = mdc / sem
                assert 2.5 < ratio < 3.1, (
                    f"{row['metric']}: MDC/SEM ratio {ratio:.3f} "
                    f"should be ~2.77 (= 1.96*sqrt(2))"
                )

    def test_rom_sem_smaller_than_expected_range(self):
        """SEM for ROM should be small relative to measurement range."""
        row = self._get_metric("knee_rom_r")
        assert row is not None
        sem = float(row["sem"])
        assert sem < 5.0, (
            f"knee_rom_r SEM {sem:.2f} too large — "
            f"should be small with controlled data"
        )


# ---------------------------------------------------------------------------
# 14. Quality classification
# ---------------------------------------------------------------------------

class TestQualityClassification:
    def _load_quality(self):
        rows = []
        with open("/app/output/quality_classification.csv") as f:
            reader = csv.DictReader(f, delimiter=";")
            for row in reader:
                rows.append({k.strip(): v.strip() for k, v in row.items()})
        return rows

    def test_valid_quality_levels(self):
        valid = {"excellent", "good", "moderate", "poor"}
        for row in self._load_quality():
            assert row["quality_level"] in valid, (
                f"Invalid quality level '{row['quality_level']}' "
                f"for {row['metric']}"
            )

    def test_quality_consistent_with_icc(self):
        """Quality level must be consistent with ICC thresholds."""
        for row in self._load_quality():
            icc = float(row["icc"])
            level = row["quality_level"]
            if icc >= 0.90:
                assert level == "excellent", (
                    f"{row['metric']}: ICC {icc:.3f} >= 0.90 but level "
                    f"is '{level}', expected 'excellent'"
                )
            elif icc >= 0.75:
                assert level == "good", (
                    f"{row['metric']}: ICC {icc:.3f} in [0.75, 0.90) but "
                    f"level is '{level}', expected 'good'"
                )
            elif icc >= 0.50:
                assert level == "moderate", (
                    f"{row['metric']}: ICC {icc:.3f} in [0.50, 0.75) but "
                    f"level is '{level}', expected 'moderate'"
                )
            else:
                assert level == "poor", (
                    f"{row['metric']}: ICC {icc:.3f} < 0.50 but "
                    f"level is '{level}', expected 'poor'"
                )

    def test_majority_excellent_or_good(self):
        """With controlled synthetic data, most PIs should be reliable."""
        rows = self._load_quality()
        good_or_better = sum(
            1 for r in rows
            if r["quality_level"] in ("excellent", "good")
        )
        assert good_or_better >= 6, (
            f"Expected >= 6 excellent/good PIs, got {good_or_better}"
        )

    def test_required_metrics_present(self):
        metrics = {r["metric"] for r in self._load_quality()}
        for required in ["knee_rom_r", "hip_rom_r", "stride_time", "cadence"]:
            assert required in metrics, (
                f"Missing metric '{required}' in quality classification"
            )
