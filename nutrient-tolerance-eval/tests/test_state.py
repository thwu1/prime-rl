"""
Independent verification of the nutrient compliance evaluation pipeline.

"""

import json
import math
import os

import pytest

NUTRIENTS = ['energy', 'fat', 'saturates', 'sugars', 'protein', 'salt']
FSA_NUTRIENTS = ['fat', 'saturates', 'sugars', 'salt']
FSA_CLASSES = ['green', 'amber', 'red']
DATA_DIR = '/app/data'
OUTPUT_PATH = '/app/output/results.json'


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ---- Independent reference implementations ----

def ref_check_tolerance(predicted, actual, nutrient, tolerance_rules):
    """Reference tolerance check: first matching tier based on actual value."""
    rules = tolerance_rules[nutrient]
    for rule in rules:
        max_val = rule.get("max_actual")
        if max_val is None or actual <= max_val:
            if rule["tolerance_type"] == "absolute":
                return abs(predicted - actual) <= rule["tolerance_value"]
            else:
                if actual == 0:
                    return abs(predicted) <= 1e-9
                return abs(predicted - actual) <= abs(actual) * rule["tolerance_value"]
    return False


def ref_tolerance_bound(actual, nutrient, tolerance_rules):
    """Reference tolerance bound computation."""
    rules = tolerance_rules[nutrient]
    for rule in rules:
        max_val = rule.get("max_actual")
        if max_val is None or actual <= max_val:
            if rule["tolerance_type"] == "absolute":
                return rule["tolerance_value"]
            else:
                if actual == 0:
                    return 1e-9
                return abs(actual) * rule["tolerance_value"]
    return 0.0


def ref_fsa_label(value, nutrient, fsa_thresholds):
    """Reference FSA classification."""
    t = fsa_thresholds[nutrient]
    if value <= t["low"]:
        return "green"
    elif value <= t["high"]:
        return "amber"
    else:
        return "red"


def ref_f1_for_class(pred_labels, true_labels, cls):
    """Reference per-class F1."""
    tp = sum(1 for p, t in zip(pred_labels, true_labels) if p == cls and t == cls)
    fp = sum(1 for p, t in zip(pred_labels, true_labels) if p == cls and t != cls)
    fn = sum(1 for p, t in zip(pred_labels, true_labels) if p != cls and t == cls)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def ref_macro_f1(pred_labels, true_labels):
    """Reference macro F1 over all 3 FSA classes."""
    f1s = [ref_f1_for_class(pred_labels, true_labels, c) for c in FSA_CLASSES]
    return sum(f1s) / len(f1s)


# ---- Fixtures ----

@pytest.fixture(scope="module")
def data():
    """Load all input data."""
    gt = load_json(os.path.join(DATA_DIR, 'ground_truth.json'))
    tol = load_json(os.path.join(DATA_DIR, 'tolerance_rules.json'))
    fsa = load_json(os.path.join(DATA_DIR, 'fsa_thresholds.json'))
    cfg = load_json(os.path.join(DATA_DIR, 'evaluation_config.json'))
    preds = {}
    pred_dir = os.path.join(DATA_DIR, 'predictions')
    for fname in sorted(os.listdir(pred_dir)):
        if fname.endswith('.json'):
            sysname = fname.replace('.json', '')
            preds[sysname] = load_json(os.path.join(pred_dir, fname))
    return gt, tol, fsa, cfg, preds


@pytest.fixture(scope="module")
def results():
    """Load the agent's output."""
    assert os.path.exists(OUTPUT_PATH), f"Output file not found: {OUTPUT_PATH}"
    return load_json(OUTPUT_PATH)


@pytest.fixture(scope="module")
def expected(data):
    """Independently compute all expected results."""
    gt, tol_rules, fsa_thresh, cfg, predictions = data
    recipe_ids = sorted(gt.keys())
    system_names = sorted(predictions.keys())
    rd = cfg["round_digits"]
    tol_w = cfg["composite_weights"]["tolerance"]
    fsa_w = cfg["composite_weights"]["fsa"]

    # Tolerance accuracy
    tolerance_accuracy = {}
    tolerance_per_recipe = {}

    for sysname in system_names:
        per_nutrient_hits = {n: [] for n in NUTRIENTS}
        per_recipe_hits = {r: 0 for r in recipe_ids}

        for rid in recipe_ids:
            g = gt[rid]
            p = predictions[sysname][rid]
            for nut in NUTRIENTS:
                within = ref_check_tolerance(p[nut], g[nut], nut, tol_rules)
                per_nutrient_hits[nut].append(1 if within else 0)
                if within:
                    per_recipe_hits[rid] += 1

        per_nutrient_acc = {n: round(sum(v) / len(v), rd)
                           for n, v in per_nutrient_hits.items()}
        all_hits = [x for v in per_nutrient_hits.values() for x in v]
        overall = round(sum(all_hits) / len(all_hits), rd)

        tolerance_accuracy[sysname] = {
            "overall": overall, "per_nutrient": per_nutrient_acc}
        tolerance_per_recipe[sysname] = {
            r: per_recipe_hits[r] / len(NUTRIENTS) for r in recipe_ids}

    # FSA evaluation
    fsa_evaluation = {}
    fsa_per_recipe = {}

    for sysname in system_names:
        per_nutrient_f1 = {}
        per_recipe_correct = {r: 0 for r in recipe_ids}

        for nut in FSA_NUTRIENTS:
            pred_labels = []
            true_labels = []
            for rid in recipe_ids:
                gt_label = ref_fsa_label(gt[rid][nut], nut, fsa_thresh)
                pred_label = ref_fsa_label(
                    predictions[sysname][rid][nut], nut, fsa_thresh)
                true_labels.append(gt_label)
                pred_labels.append(pred_label)
                if gt_label == pred_label:
                    per_recipe_correct[rid] += 1

            f1 = ref_macro_f1(pred_labels, true_labels)
            per_nutrient_f1[nut] = round(f1, rd)

        macro_f1 = round(
            sum(per_nutrient_f1.values()) / len(per_nutrient_f1), rd)
        fsa_evaluation[sysname] = {
            "macro_f1": macro_f1, "per_nutrient_f1": per_nutrient_f1}
        fsa_per_recipe[sysname] = {
            r: per_recipe_correct[r] / len(FSA_NUTRIENTS) for r in recipe_ids}

    # Composite scores
    composite_per_recipe = {}
    composite_scores = {}

    for sysname in system_names:
        per_recipe = {}
        for rid in recipe_ids:
            t_score = tolerance_per_recipe[sysname][rid]
            f_score = fsa_per_recipe[sysname][rid]
            per_recipe[rid] = tol_w * t_score + fsa_w * f_score
        composite_per_recipe[sysname] = per_recipe
        composite_scores[sysname] = round(
            sum(per_recipe.values()) / len(per_recipe), rd)

    # System ranking
    system_ranking = sorted(
        system_names, key=lambda s: composite_scores[s], reverse=True)

    # Error analysis
    error_analysis = {}
    for sysname in system_names:
        per_nutrient = {}
        for nut in NUTRIENTS:
            errors = []
            abs_errors = []
            sq_errors = []
            margins = []
            for rid in recipe_ids:
                predicted = predictions[sysname][rid][nut]
                actual = gt[rid][nut]
                err = predicted - actual
                abs_err = abs(err)
                errors.append(err)
                abs_errors.append(abs_err)
                sq_errors.append(err ** 2)
                bound = ref_tolerance_bound(actual, nut, tol_rules)
                margin = (bound - abs_err) / bound if bound > 0 else 0.0
                margins.append(margin)
            bias = round(sum(errors) / len(errors), rd)
            mae = round(sum(abs_errors) / len(abs_errors), rd)
            rmse = round(math.sqrt(sum(sq_errors) / len(sq_errors)), rd)
            tol_margin = round(sum(margins) / len(margins), rd)
            per_nutrient[nut] = {
                "bias": bias, "mae": mae, "rmse": rmse,
                "tolerance_margin": tol_margin
            }
        overall_mae = round(
            sum(per_nutrient[n]["mae"] for n in NUTRIENTS) / len(NUTRIENTS), rd)
        overall_rmse = round(
            sum(per_nutrient[n]["rmse"] for n in NUTRIENTS) / len(NUTRIENTS), rd)
        mean_tol_margin = round(
            sum(per_nutrient[n]["tolerance_margin"] for n in NUTRIENTS) / len(NUTRIENTS), rd)
        error_analysis[sysname] = {
            "per_nutrient": per_nutrient,
            "overall_mae": overall_mae,
            "overall_rmse": overall_rmse,
            "mean_tolerance_margin": mean_tol_margin
        }

    return {
        "tolerance_accuracy": tolerance_accuracy,
        "fsa_evaluation": fsa_evaluation,
        "composite_scores": composite_scores,
        "system_ranking": system_ranking,
        "composite_per_recipe": composite_per_recipe,
        "error_analysis": error_analysis,
    }


# ---- Tests ----

class TestOutputStructure:
    """Verify the output file exists and has required structure."""

    def test_output_file_exists(self):
        assert os.path.exists(OUTPUT_PATH), \
            "Output file /app/output/results.json not found"

    def test_output_is_valid_json(self, results):
        assert isinstance(results, dict)

    def test_top_level_keys(self, results):
        required = {"tolerance_accuracy", "fsa_evaluation",
                     "error_analysis", "composite_scores",
                     "system_ranking", "bootstrap_significance"}
        assert required.issubset(set(results.keys())), \
            f"Missing keys: {required - set(results.keys())}"

    def test_all_systems_present(self, results, data):
        _, _, _, _, preds = data
        system_names = sorted(preds.keys())
        for section in ["tolerance_accuracy", "fsa_evaluation",
                        "composite_scores", "error_analysis"]:
            for sysname in system_names:
                assert sysname in results[section], \
                    f"System {sysname} missing from {section}"

    def test_tolerance_structure(self, results, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            entry = results["tolerance_accuracy"][sysname]
            assert "overall" in entry
            assert "per_nutrient" in entry
            for nut in NUTRIENTS:
                assert nut in entry["per_nutrient"], \
                    f"{nut} missing from tolerance_accuracy/{sysname}"

    def test_fsa_structure(self, results, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            entry = results["fsa_evaluation"][sysname]
            assert "macro_f1" in entry
            assert "per_nutrient_f1" in entry
            for nut in FSA_NUTRIENTS:
                assert nut in entry["per_nutrient_f1"], \
                    f"{nut} missing from fsa_evaluation/{sysname}"

    def test_error_analysis_structure(self, results, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            entry = results["error_analysis"][sysname]
            assert "per_nutrient" in entry
            assert "overall_mae" in entry
            assert "overall_rmse" in entry
            assert "mean_tolerance_margin" in entry
            for nut in NUTRIENTS:
                assert nut in entry["per_nutrient"], \
                    f"{nut} missing from error_analysis/{sysname}"
                nut_entry = entry["per_nutrient"][nut]
                assert "bias" in nut_entry
                assert "mae" in nut_entry
                assert "rmse" in nut_entry
                assert "tolerance_margin" in nut_entry

    def test_ranking_is_list(self, results):
        assert isinstance(results["system_ranking"], list)

    def test_bootstrap_structure(self, results):
        bs = results["bootstrap_significance"]
        assert isinstance(bs, dict)
        for key, val in bs.items():
            assert "p_value" in val
            assert "significant_at_0.05" in val


class TestToleranceAccuracy:
    """Verify tolerance accuracy values against reference."""

    def test_overall_tolerance_accuracy(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            actual = results["tolerance_accuracy"][sysname]["overall"]
            exp = expected["tolerance_accuracy"][sysname]["overall"]
            assert abs(actual - exp) < 1e-3, \
                f"Tolerance overall for {sysname}: {actual} vs {exp}"

    def test_per_nutrient_tolerance_accuracy(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            for nut in NUTRIENTS:
                actual = results["tolerance_accuracy"][sysname][
                    "per_nutrient"][nut]
                exp = expected["tolerance_accuracy"][sysname][
                    "per_nutrient"][nut]
                assert abs(actual - exp) < 1e-3, \
                    f"Tolerance {sysname}/{nut}: {actual} vs {exp}"

    def test_per_nutrient_accuracy_not_uniform(self, results):
        """Per-nutrient values must vary — catches missing GROUP BY."""
        for sysname in ["sys_C", "sys_D"]:
            if sysname not in results["tolerance_accuracy"]:
                continue
            vals = list(
                results["tolerance_accuracy"][sysname][
                    "per_nutrient"].values())
            assert len(set(round(v, 4) for v in vals)) > 1, \
                (f"All per-nutrient tolerance accuracies are identical "
                 f"for {sysname} — likely a SQL aggregation bug")

    def test_sys_a_best_tolerance(self, results, expected):
        systems = results["tolerance_accuracy"]
        sys_a_val = systems["sys_A"]["overall"]
        for sysname, entry in systems.items():
            if sysname != "sys_A":
                assert sys_a_val >= entry["overall"], \
                    f"sys_A ({sys_a_val}) should have highest tolerance " \
                    f"accuracy but {sysname} has {entry['overall']}"


class TestFSAEvaluation:
    """Verify FSA macro-F1 values against reference."""

    def test_overall_fsa_macro_f1(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            actual = results["fsa_evaluation"][sysname]["macro_f1"]
            exp = expected["fsa_evaluation"][sysname]["macro_f1"]
            assert abs(actual - exp) < 1e-3, \
                f"FSA macro_f1 for {sysname}: {actual} vs {exp}"

    def test_per_nutrient_fsa_f1(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            for nut in FSA_NUTRIENTS:
                actual = results["fsa_evaluation"][sysname][
                    "per_nutrient_f1"][nut]
                exp = expected["fsa_evaluation"][sysname][
                    "per_nutrient_f1"][nut]
                assert abs(actual - exp) < 1e-3, \
                    f"FSA F1 {sysname}/{nut}: {actual} vs {exp}"

    def test_fsa_values_in_valid_range(self, results, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            f1 = results["fsa_evaluation"][sysname]["macro_f1"]
            assert 0.0 <= f1 <= 1.0, \
                f"FSA F1 for {sysname} out of range: {f1}"
            for nut in FSA_NUTRIENTS:
                f1_nut = results["fsa_evaluation"][sysname][
                    "per_nutrient_f1"][nut]
                assert 0.0 <= f1_nut <= 1.0, \
                    f"FSA F1 {sysname}/{nut} out of range: {f1_nut}"


class TestErrorAnalysis:
    """Verify error analysis metrics against reference."""

    def test_error_analysis_populated(self, results, data):
        """Error analysis should have actual data, not None/empty."""
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            entry = results["error_analysis"][sysname]
            assert entry["overall_mae"] is not None, \
                f"Error analysis overall_mae is None for {sysname} — " \
                f"module may not have run"
            assert len(entry["per_nutrient"]) == len(NUTRIENTS), \
                f"Error analysis per_nutrient incomplete for {sysname}"

    def test_bias_values(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            for nut in NUTRIENTS:
                actual = results["error_analysis"][sysname][
                    "per_nutrient"][nut]["bias"]
                exp = expected["error_analysis"][sysname][
                    "per_nutrient"][nut]["bias"]
                assert abs(actual - exp) < 1e-3, \
                    f"Bias {sysname}/{nut}: {actual} vs {exp}"

    def test_mae_values(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            for nut in NUTRIENTS:
                actual = results["error_analysis"][sysname][
                    "per_nutrient"][nut]["mae"]
                exp = expected["error_analysis"][sysname][
                    "per_nutrient"][nut]["mae"]
                assert abs(actual - exp) < 1e-3, \
                    f"MAE {sysname}/{nut}: {actual} vs {exp}"

    def test_rmse_values(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            for nut in NUTRIENTS:
                actual = results["error_analysis"][sysname][
                    "per_nutrient"][nut]["rmse"]
                exp = expected["error_analysis"][sysname][
                    "per_nutrient"][nut]["rmse"]
                assert abs(actual - exp) < 1e-3, \
                    f"RMSE {sysname}/{nut}: {actual} vs {exp}"

    def test_tolerance_margin_values(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            for nut in NUTRIENTS:
                actual = results["error_analysis"][sysname][
                    "per_nutrient"][nut]["tolerance_margin"]
                exp = expected["error_analysis"][sysname][
                    "per_nutrient"][nut]["tolerance_margin"]
                assert abs(actual - exp) < 1e-3, \
                    f"Tolerance margin {sysname}/{nut}: {actual} vs {exp}"

    def test_overall_mae_values(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            actual = results["error_analysis"][sysname]["overall_mae"]
            exp = expected["error_analysis"][sysname]["overall_mae"]
            assert abs(actual - exp) < 1e-3, \
                f"Overall MAE for {sysname}: {actual} vs {exp}"

    def test_overall_rmse_values(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            actual = results["error_analysis"][sysname]["overall_rmse"]
            exp = expected["error_analysis"][sysname]["overall_rmse"]
            assert abs(actual - exp) < 1e-3, \
                f"Overall RMSE for {sysname}: {actual} vs {exp}"

    def test_mean_tolerance_margin_values(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            actual = results["error_analysis"][sysname][
                "mean_tolerance_margin"]
            exp = expected["error_analysis"][sysname][
                "mean_tolerance_margin"]
            assert abs(actual - exp) < 1e-3, \
                f"Mean tolerance margin for {sysname}: {actual} vs {exp}"

    def test_mae_non_negative(self, results, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            for nut in NUTRIENTS:
                mae = results["error_analysis"][sysname][
                    "per_nutrient"][nut]["mae"]
                assert mae >= 0, \
                    f"MAE must be non-negative: {sysname}/{nut} = {mae}"

    def test_rmse_gte_mae(self, results, data):
        """RMSE should always be >= MAE."""
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            for nut in NUTRIENTS:
                mae = results["error_analysis"][sysname][
                    "per_nutrient"][nut]["mae"]
                rmse = results["error_analysis"][sysname][
                    "per_nutrient"][nut]["rmse"]
                assert rmse >= mae - 1e-6, \
                    f"RMSE ({rmse}) should be >= MAE ({mae}) " \
                    f"for {sysname}/{nut}"

    def test_sys_a_best_tolerance_margin(self, results):
        """sys_A (lowest noise) should have best tolerance margin."""
        sys_a_margin = results["error_analysis"]["sys_A"][
            "mean_tolerance_margin"]
        for sysname in ["sys_B", "sys_C", "sys_D"]:
            other_margin = results["error_analysis"][sysname][
                "mean_tolerance_margin"]
            assert sys_a_margin >= other_margin, \
                f"sys_A margin ({sys_a_margin}) should be >= " \
                f"{sysname} margin ({other_margin})"


class TestCompositeScores:
    """Verify composite scores and ranking."""

    def test_composite_score_values(self, results, expected, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            actual = results["composite_scores"][sysname]
            exp = expected["composite_scores"][sysname]
            assert abs(actual - exp) < 1e-3, \
                f"Composite for {sysname}: {actual} vs {exp}"

    def test_composite_in_valid_range(self, results, data):
        _, _, _, _, preds = data
        for sysname in sorted(preds.keys()):
            score = results["composite_scores"][sysname]
            assert 0.0 <= score <= 1.0, \
                f"Composite for {sysname} out of range: {score}"

    def test_system_ranking_order(self, results, expected):
        actual_ranking = results["system_ranking"]
        expected_ranking = expected["system_ranking"]
        assert actual_ranking == expected_ranking, \
            f"Ranking: got {actual_ranking}, expected {expected_ranking}"

    def test_ranking_consistent_with_scores(self, results):
        ranking = results["system_ranking"]
        scores = results["composite_scores"]
        for i in range(len(ranking) - 1):
            assert scores[ranking[i]] >= scores[ranking[i + 1]], \
                f"Ranking inconsistent: {ranking[i]} " \
                f"({scores[ranking[i]]}) should be >= " \
                f"{ranking[i + 1]} ({scores[ranking[i + 1]]})"


class TestBootstrapSignificance:
    """Verify bootstrap significance results."""

    def test_adjacent_pairs_present(self, results):
        ranking = results["system_ranking"]
        bs = results["bootstrap_significance"]
        for i in range(len(ranking) - 1):
            key = f"{ranking[i]}_vs_{ranking[i + 1]}"
            assert key in bs, f"Missing bootstrap entry: {key}"

    def test_p_values_in_valid_range(self, results):
        bs = results["bootstrap_significance"]
        for key, val in bs.items():
            p = val["p_value"]
            assert 0.0 <= p <= 1.0, \
                f"p-value for {key} out of range: {p}"

    def test_significance_consistency(self, results, data):
        _, _, _, cfg, _ = data
        alpha = cfg["significance_level"]
        bs = results["bootstrap_significance"]
        for key, val in bs.items():
            expected_sig = val["p_value"] < alpha
            assert val["significant_at_0.05"] == expected_sig, \
                f"Significance flag for {key}: p={val['p_value']}, " \
                f"got {val['significant_at_0.05']}, expected {expected_sig}"

    def test_top_pair_significant(self, results):
        ranking = results["system_ranking"]
        key = f"{ranking[0]}_vs_{ranking[1]}"
        bs = results["bootstrap_significance"]
        assert bs[key]["significant_at_0.05"], \
            f"Top pair {key} should be significant " \
            f"but p={bs[key]['p_value']}"

    def test_close_pair_not_significant(self, results):
        ranking = results["system_ranking"]
        key = f"{ranking[-2]}_vs_{ranking[-1]}"
        bs = results["bootstrap_significance"]
        assert not bs[key]["significant_at_0.05"], \
            f"Bottom pair {key} should not be significant " \
            f"but p={bs[key]['p_value']}"


class TestEdgeCases:
    """Verify correct handling of edge cases."""

    def test_zero_actual_tolerance(self, data):
        gt, tol_rules, _, _, preds = data
        for sysname in sorted(preds.keys()):
            pred_val = preds[sysname]["R05"]["sugars"]
            within = ref_check_tolerance(pred_val, 0.0, "sugars", tol_rules)
            if pred_val <= 1.5:
                assert within, \
                    f"R05 sugars pred={pred_val} should be within " \
                    f"tolerance of actual=0"

    def test_boundary_fsa_classification(self, data):
        _, _, fsa_thresh, _, _ = data
        label = ref_fsa_label(5.0, "saturates", fsa_thresh)
        assert label == "amber", \
            f"saturates=5.0 should be 'amber', got '{label}'"
        label = ref_fsa_label(0.3, "salt", fsa_thresh)
        assert label == "green", \
            f"salt=0.3 should be 'green', got '{label}'"

    def test_tier_boundary_tolerance(self, data):
        gt, tol_rules, _, _, _ = data
        assert ref_check_tolerance(10.4 + 2.0, 10.4, "fat", tol_rules)
        assert not ref_check_tolerance(10.4 + 2.1, 10.4, "fat", tol_rules)

    def test_tolerance_bound_absolute(self, data):
        _, tol_rules, _, _, _ = data
        bound = ref_tolerance_bound(5.0, "fat", tol_rules)
        assert abs(bound - 1.5) < 1e-9, \
            f"fat bound for actual=5.0 should be 1.5, got {bound}"

    def test_tolerance_bound_relative(self, data):
        _, tol_rules, _, _, _ = data
        bound = ref_tolerance_bound(14.0, "fat", tol_rules)
        assert abs(bound - 2.8) < 1e-9, \
            f"fat bound for actual=14.0 should be 2.8, got {bound}"

    def test_all_recipes_accounted(self, results, data):
        gt, _, _, _, _ = data
        n_recipes = len(gt)
        assert n_recipes == 20, f"Expected 20 recipes, got {n_recipes}"
        sys_a = results["tolerance_accuracy"]["sys_A"]
        per_nut = sys_a["per_nutrient"]
        expected_overall = sum(per_nut[n] for n in NUTRIENTS) / len(NUTRIENTS)
        assert abs(sys_a["overall"] - expected_overall) < 1e-3, \
            f"Overall ({sys_a['overall']}) inconsistent with " \
            f"per-nutrient mean ({expected_overall})"
