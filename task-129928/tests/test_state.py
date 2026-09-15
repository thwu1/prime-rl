
import pytest
import subprocess
import csv
import json
import os
import numpy as np


@pytest.fixture(scope="session", autouse=True)
def run_pipeline():
    """Run the pipeline before all tests."""
    result = subprocess.run(
        ["python3", "/app/pipeline.py"],
        capture_output=True, text=True, timeout=120,
        cwd="/app"
    )
    assert result.returncode == 0, (
        f"Pipeline failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout[:2000]}\nstderr: {result.stderr[:2000]}"
    )


# ---------- helpers ----------

def _load_cohort():
    cohort = {}
    with open("/app/output/cohort.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cohort[row["PatientID"].strip()] = int(row["Group"])
    return cohort


def _load_scores():
    with open("/app/output/scores.json") as f:
        return json.load(f)


# Expected group assignments for all 30 patients
EXPECTED_GROUPS = {
    # Group 1 (CI positive)
    "P001": 1, "P002": 1, "P003": 1, "P004": 1, "P005": 1,
    "P006": 1, "P007": 1, "P008": 1, "P009": 1, "P010": 1,
    # Group 2 (CI negative)
    "P011": 2, "P012": 2, "P013": 2, "P014": 2, "P015": 2,
    "P016": 2, "P017": 2, "P018": 2, "P019": 2, "P020": 2,
    # Group 3 (excluded)
    "P021": 3, "P022": 3, "P023": 3, "P024": 3, "P025": 3,
    "P026": 3, "P027": 3, "P028": 3, "P029": 3, "P030": 3,
}

# Patient sites for scored patients
PATIENT_SITES = {
    "P001": "S0001", "P002": "S0001", "P003": "I0006", "P004": "S0001",
    "P005": "I0002", "P006": "S0001", "P007": "S0001", "P008": "S0001",
    "P009": "I0004", "P010": "S0001",
    "P011": "S0001", "P012": "S0001", "P013": "S0001", "P014": "S0001",
    "P015": "I0002", "P016": "S0001", "P017": "I0006", "P018": "I0004",
    "P019": "S0001", "P020": "I0002",
}


def _get_scored_data():
    """Build labels, probs, binary, sites for scored patients."""
    scored_groups = {pid: g for pid, g in EXPECTED_GROUPS.items() if g in (1, 2)}

    preds = {}
    with open("/app/data/model_output.jsonl") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            preds[rec["patient_id"]] = {
                "prob": float(rec["confidence"]),
                "binary": int(rec["prediction"]),
            }

    scored_pids = sorted(scored_groups.keys())
    labels = np.array([1 if scored_groups[p] == 1 else 0 for p in scored_pids])
    probs = np.array([preds[p]["prob"] for p in scored_pids])
    binary = np.array([preds[p]["binary"] for p in scored_pids])
    sites = np.array([PATIENT_SITES[p] for p in scored_pids])
    return labels, probs, binary, sites, scored_pids


def _compute_challenge_score(labels, outputs, fraction_capacity, num_permutations=10000, seed=12345):
    """Reference implementation of the capacity-constrained TPR."""
    n = len(labels)
    capacity = int(fraction_capacity * n)
    labels = np.asarray(labels, dtype=np.float64)
    outputs = np.asarray(outputs, dtype=np.float64)

    tp = np.zeros(num_permutations)
    fn = np.zeros(num_permutations)

    np.random.seed(seed)
    for i in range(num_permutations):
        perm = np.random.permutation(np.arange(n))
        p_labels = labels[perm]
        p_outputs = outputs[perm]
        order = np.argsort(p_outputs, stable=True)[::-1]
        o_labels = p_labels[order]
        tp[i] = np.sum(o_labels[:capacity] == 1)
        fn[i] = np.sum(o_labels[capacity:] == 1)

    tp_m = np.mean(tp)
    fn_m = np.mean(fn)
    if tp_m + fn_m > 0:
        return tp_m / (tp_m + fn_m)
    return float("nan")


def _compute_bootstrap_ci(labels, probs, binary, sites, n_boot=1000, seed=42, alpha=0.05):
    """Independently compute bootstrap CIs with site stratification."""
    from sklearn.metrics import roc_auc_score, average_precision_score, accuracy_score, f1_score
    rng = np.random.RandomState(seed)
    unique_sites = np.unique(sites)

    metrics = {"auroc": [], "auprc": [], "accuracy": [], "f1": []}

    for _ in range(n_boot):
        indices = []
        for s in unique_sites:
            site_idx = np.where(sites == s)[0]
            boot_idx = rng.choice(site_idx, size=len(site_idx), replace=True)
            indices.extend(boot_idx)
        indices = np.array(indices)

        b_labels = labels[indices]
        b_probs = probs[indices]
        b_binary = binary[indices]

        if len(np.unique(b_labels)) < 2:
            continue

        metrics["auroc"].append(roc_auc_score(b_labels, b_probs))
        metrics["auprc"].append(average_precision_score(b_labels, b_probs))
        metrics["accuracy"].append(accuracy_score(b_labels, b_binary))
        metrics["f1"].append(f1_score(b_labels, b_binary, pos_label=1))

    ci = {}
    for metric, values in metrics.items():
        ci[metric] = {
            "lower": float(np.percentile(values, 100 * alpha / 2)),
            "upper": float(np.percentile(values, 100 * (1 - alpha / 2))),
        }
    return ci


# ---------- cohort tests ----------

class TestCohortFiles:
    def test_cohort_file_exists(self):
        assert os.path.exists("/app/output/cohort.csv")

    def test_scores_file_exists(self):
        assert os.path.exists("/app/output/scores.json")

    def test_all_patients_assigned(self):
        cohort = _load_cohort()
        assert len(cohort) == 30, f"Expected 30 patients, got {len(cohort)}"


class TestCohortGroup1:
    """Group 1: CI-positive patients."""

    def test_standard_ehr_only_p001(self):
        """P001: 2 qualifying EHR codes in temporal window."""
        assert _load_cohort()["P001"] == 1

    def test_cross_source_ehr_claims_p002(self):
        """P002: 1 EHR (ICD-9 331.83) + 1 claims (G3184) — requires cross-source integration."""
        assert _load_cohort()["P002"] == 1

    def test_standard_ehr_only_p003(self):
        """P003 (I0006): 2 qualifying EHR codes, 17-day gap."""
        assert _load_cohort()["P003"] == 1

    def test_mixed_icd9_icd10_dotted_p004(self):
        """P004: ICD-9 290.0 + ICD-10 F03.90 — mixed code systems with dots."""
        assert _load_cohort()["P004"] == 1

    def test_cross_source_i0002_p005(self):
        """P005 (I0002): 1 EHR (G31.84) + 1 claims (F0390) — cross-source."""
        assert _load_cohort()["P005"] == 1

    def test_early_plus_window_p006(self):
        """P006: 3 qualifying codes, first at 1.4yr (early), later two in [3,7] window."""
        assert _load_cohort()["P006"] == 1

    def test_standard_ehr_only_p007(self):
        """P007: 2 qualifying EHR codes in window."""
        assert _load_cohort()["P007"] == 1

    def test_cross_source_icd9_claims_p008(self):
        """P008: 1 EHR (G31.84) + 1 claims (33183 ICD-9 undotted) — cross-source."""
        assert _load_cohort()["P008"] == 1

    def test_standard_ehr_only_p009(self):
        """P009 (I0004): 2 qualifying EHR codes (G31.83, G31.84)."""
        assert _load_cohort()["P009"] == 1

    def test_dedup_then_extra_claims_p010(self):
        """P010: EHR G31.84 + claims G3184 same date (dedup!) + claims G309 later.
        After dedup: 2 unique events -> Group 1."""
        assert _load_cohort()["P010"] == 1


class TestCohortGroup2:
    """Group 2: CI-negative patients."""

    def test_nonqualifying_cad_p011(self):
        """P011: I25.10 (CAD) non-qualifying, 9.5yr follow-up."""
        assert _load_cohort()["P011"] == 2

    def test_nonqualifying_lipid_p012(self):
        """P012: E78.5 (hyperlipidemia) non-qualifying."""
        assert _load_cohort()["P012"] == 2

    def test_multiple_nonqualifying_p013(self):
        """P013: J45.9, E11.9, I10 — all non-qualifying."""
        assert _load_cohort()["P013"] == 2

    def test_nonqualifying_osa_p014(self):
        """P014: G47.33 (OSA) non-qualifying."""
        assert _load_cohort()["P014"] == 2

    def test_i0002_6yr_threshold_p015(self):
        """P015 (I0002): 6.58yr follow-up >= 6yr site threshold."""
        assert _load_cohort()["P015"] == 2

    def test_claims_only_nonqualifying_p016(self):
        """P016: claims-only J441 (COPD) non-qualifying. No EHR diagnoses."""
        assert _load_cohort()["P016"] == 2

    def test_no_diagnoses_i0006_p017(self):
        """P017 (I0006): no diagnoses, 8.4yr > 7yr threshold."""
        assert _load_cohort()["P017"] == 2

    def test_nonqualifying_i0004_p018(self):
        """P018 (I0004): M54.5 non-qualifying, 8yr > 7yr."""
        assert _load_cohort()["P018"] == 2

    def test_no_diagnoses_p019(self):
        """P019: no diagnoses, 8.3yr follow-up."""
        assert _load_cohort()["P019"] == 2

    def test_i0002_6yr_threshold_p020(self):
        """P020 (I0002): no diagnoses, 6.4yr >= 6yr site threshold."""
        assert _load_cohort()["P020"] == 2


class TestCohortGroup3:
    """Group 3: Excluded patients (edge cases)."""

    def test_single_qualifying_p021(self):
        """P021: only 1 qualifying diagnosis — not enough."""
        assert _load_cohort()["P021"] == 3

    def test_codes_before_window_p022(self):
        """P022: 2 qualifying codes at 1.4yr and 1.7yr — all before 3yr window."""
        assert _load_cohort()["P022"] == 3

    def test_insufficient_followup_p023(self):
        """P023: non-qualifying R51, 5.4yr < 7yr threshold."""
        assert _load_cohort()["P023"] == 3

    def test_codes_beyond_window_p024(self):
        """P024: 2 qualifying codes at 8.4yr and 9yr — all beyond 7yr window."""
        assert _load_cohort()["P024"] == 3

    def test_gap_too_small_p025(self):
        """P025: 2 qualifying codes in window but only 4 days apart."""
        assert _load_cohort()["P025"] == 3

    def test_i0002_insufficient_followup_p026(self):
        """P026 (I0002): non-qualifying, 5yr < 6yr site threshold."""
        assert _load_cohort()["P026"] == 3

    def test_dedup_reduces_to_one_p027(self):
        """P027: EHR G31.84 + claims G3184 same code+date -> dedup -> 1 event.
        Critical edge case: without dedup, appears as 2 diagnoses."""
        assert _load_cohort()["P027"] == 3

    def test_same_date_different_codes_p028(self):
        """P028: EHR G30.0 + claims G309 on SAME date -> 2 events, 0-day gap < 7.
        Tests that gap rule uses dates, not event count."""
        assert _load_cohort()["P028"] == 3

    def test_insufficient_followup_p029(self):
        """P029: no diagnoses, 6yr < 7yr threshold."""
        assert _load_cohort()["P029"] == 3

    def test_nonqualifying_insufficient_followup_p030(self):
        """P030 (I0004): non-qualifying G47.30, 5.5yr < 7yr."""
        assert _load_cohort()["P030"] == 3


# ---------- overall metric tests ----------

class TestOverallMetrics:
    def test_auroc(self):
        from sklearn.metrics import roc_auc_score
        scores = _load_scores()
        labels, probs, _, _, _ = _get_scored_data()
        expected = roc_auc_score(labels, probs)
        actual = scores["overall_metrics"]["auroc"]
        assert abs(actual - expected) < 1e-4, (
            f"AUROC: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_auprc(self):
        from sklearn.metrics import average_precision_score
        scores = _load_scores()
        labels, probs, _, _, _ = _get_scored_data()
        expected = average_precision_score(labels, probs)
        actual = scores["overall_metrics"]["auprc"]
        assert abs(actual - expected) < 1e-4, (
            f"AUPRC: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_accuracy(self):
        from sklearn.metrics import accuracy_score
        scores = _load_scores()
        labels, _, binary, _, _ = _get_scored_data()
        expected = accuracy_score(labels, binary)
        actual = scores["overall_metrics"]["accuracy"]
        assert abs(actual - expected) < 1e-4, (
            f"Accuracy: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_f1(self):
        from sklearn.metrics import f1_score
        scores = _load_scores()
        labels, _, binary, _, _ = _get_scored_data()
        expected = f1_score(labels, binary, pos_label=1)
        actual = scores["overall_metrics"]["f1"]
        assert abs(actual - expected) < 1e-4, (
            f"F1: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_challenge_score_005(self):
        scores = _load_scores()
        labels, probs, _, _, _ = _get_scored_data()
        expected = _compute_challenge_score(labels, probs, fraction_capacity=0.05)
        actual = scores["overall_metrics"]["challenge_score_005"]
        assert not np.isnan(actual), "challenge_score_005 should not be NaN"
        assert abs(actual - expected) < 1e-3, (
            f"Challenge score 0.05: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_challenge_score_020(self):
        scores = _load_scores()
        labels, probs, _, _, _ = _get_scored_data()
        expected = _compute_challenge_score(labels, probs, fraction_capacity=0.20)
        actual = scores["overall_metrics"]["challenge_score_020"]
        assert abs(actual - expected) < 1e-3, (
            f"Challenge score 0.20: expected {expected:.6f}, got {actual:.6f}"
        )

    def test_scores_json_structure(self):
        scores = _load_scores()
        required_keys = ["auroc", "auprc", "accuracy", "f1",
                         "challenge_score_005", "challenge_score_020"]
        for key in required_keys:
            assert key in scores["overall_metrics"], (
                f"Missing key '{key}' in overall_metrics"
            )
            val = scores["overall_metrics"][key]
            assert isinstance(val, (int, float)), (
                f"overall_metrics['{key}'] should be numeric, got {type(val)}"
            )


# ---------- confidence interval tests ----------

class TestConfidenceIntervals:
    def test_ci_structure(self):
        scores = _load_scores()
        assert "confidence_intervals" in scores, "Missing confidence_intervals"
        ci = scores["confidence_intervals"]
        for metric in ["auroc", "auprc", "accuracy", "f1"]:
            assert metric in ci, f"Missing CI for {metric}"
            assert "lower" in ci[metric], f"Missing lower bound for {metric}"
            assert "upper" in ci[metric], f"Missing upper bound for {metric}"

    def test_ci_bounds_valid(self):
        scores = _load_scores()
        ci = scores["confidence_intervals"]
        for metric in ["auroc", "auprc", "accuracy", "f1"]:
            lower = ci[metric]["lower"]
            upper = ci[metric]["upper"]
            assert isinstance(lower, (int, float)) and not np.isnan(lower), (
                f"CI lower for {metric} is not a valid number"
            )
            assert isinstance(upper, (int, float)) and not np.isnan(upper), (
                f"CI upper for {metric} is not a valid number"
            )
            assert lower <= upper, (
                f"CI for {metric}: lower ({lower}) > upper ({upper})"
            )
            assert 0 <= lower <= 1, f"CI lower for {metric} out of [0,1]: {lower}"
            assert 0 <= upper <= 1, f"CI upper for {metric} out of [0,1]: {upper}"

    def test_ci_nondegenerate(self):
        """CIs should have positive width (not all identical bootstrap samples)."""
        scores = _load_scores()
        ci = scores["confidence_intervals"]
        for metric in ["auroc", "auprc", "accuracy", "f1"]:
            width = ci[metric]["upper"] - ci[metric]["lower"]
            assert width > 0, f"CI for {metric} has zero width"

    def test_ci_values_match_independent(self):
        """Compare pipeline CIs against independently computed CIs."""
        scores = _load_scores()
        ci_pipeline = scores["confidence_intervals"]
        labels, probs, binary, sites, _ = _get_scored_data()
        ci_expected = _compute_bootstrap_ci(labels, probs, binary, sites)

        for metric in ["auroc", "auprc", "accuracy", "f1"]:
            assert abs(ci_pipeline[metric]["lower"] - ci_expected[metric]["lower"]) < 0.02, (
                f"CI lower for {metric}: expected ~{ci_expected[metric]['lower']:.4f}, "
                f"got {ci_pipeline[metric]['lower']:.4f}"
            )
            assert abs(ci_pipeline[metric]["upper"] - ci_expected[metric]["upper"]) < 0.02, (
                f"CI upper for {metric}: expected ~{ci_expected[metric]['upper']:.4f}, "
                f"got {ci_pipeline[metric]['upper']:.4f}"
            )


# ---------- site metric tests ----------

class TestSiteMetrics:
    def test_site_metrics_structure(self):
        scores = _load_scores()
        assert "site_metrics" in scores, "Missing site_metrics"
        sm = scores["site_metrics"]
        for site in ["S0001", "I0002", "I0004", "I0006"]:
            assert site in sm, f"Missing site {site} in site_metrics"
            assert "n_group1" in sm[site], f"Missing n_group1 for {site}"
            assert "n_group2" in sm[site], f"Missing n_group2 for {site}"
            assert "auroc" in sm[site], f"Missing auroc for {site}"

    def test_site_sample_sizes(self):
        scores = _load_scores()
        sm = scores["site_metrics"]
        # S0001: 7 G1, 6 G2
        assert sm["S0001"]["n_group1"] == 7
        assert sm["S0001"]["n_group2"] == 6
        # I0002: 1 G1, 2 G2
        assert sm["I0002"]["n_group1"] == 1
        assert sm["I0002"]["n_group2"] == 2
        # I0004: 1 G1, 1 G2
        assert sm["I0004"]["n_group1"] == 1
        assert sm["I0004"]["n_group2"] == 1
        # I0006: 1 G1, 1 G2
        assert sm["I0006"]["n_group1"] == 1
        assert sm["I0006"]["n_group2"] == 1

    def test_site_auroc_values(self):
        from sklearn.metrics import roc_auc_score
        scores = _load_scores()
        sm = scores["site_metrics"]
        labels, probs, _, sites, _ = _get_scored_data()

        for site in ["S0001", "I0002", "I0004", "I0006"]:
            mask = sites == site
            s_labels = labels[mask]
            s_probs = probs[mask]
            expected = roc_auc_score(s_labels, s_probs)
            actual = sm[site]["auroc"]
            assert abs(actual - expected) < 1e-4, (
                f"AUROC for {site}: expected {expected:.6f}, got {actual:.6f}"
            )


# ---------- cohort summary tests ----------

class TestCohortSummary:
    def test_cohort_summary_present(self):
        scores = _load_scores()
        assert "cohort_summary" in scores, "Missing cohort_summary"

    def test_cohort_summary_counts(self):
        scores = _load_scores()
        cs = scores["cohort_summary"]
        assert cs["group_1"] == 10, f"Expected 10 Group 1, got {cs['group_1']}"
        assert cs["group_2"] == 10, f"Expected 10 Group 2, got {cs['group_2']}"
        assert cs["group_3"] == 10, f"Expected 10 Group 3, got {cs['group_3']}"
