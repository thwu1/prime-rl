
import pytest
import json
import sqlite3
import math
import os

import numpy as np

MODELS = ["groot_n15", "pi0", "pi0_fast"]  # sorted alphabetically
NUM_PERTURBATIONS = 16
NUM_NON_DEFAULT = 15
NUM_TASKS = 10
TOTAL_ROLLOUTS = 25
Z_95 = 1.959963984540054

PERTURBATION_NAMES = [
    "v_aug", "v_view", "v_sc", "v_light",
    "s_prop", "s_lang", "s_mo", "s_aff", "s_int",
    "b_hobj", "sb_noun", "sb_vrb", "vb_pose", "vb_mobj", "vsb_nobj"
]

DB_PATH = "/app/data/benchmark.db"


def load_from_db(model):
    """Load data for a model from SQLite: (p_id, t_id) -> successes."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT perturbation_id, task_id, successes FROM results WHERE model = ?",
        (model,)
    )
    data = {}
    for row in cursor:
        data[(row[0], row[1])] = row[2]
    conn.close()
    return data


def wilson_ci(successes, total):
    """Compute Wilson score 95% CI."""
    n = total
    p_hat = successes / n
    z = Z_95
    denom = 1 + z ** 2 / n
    center = p_hat + z ** 2 / (2 * n)
    spread = z * math.sqrt(p_hat * (1 - p_hat) / n + z ** 2 / (4 * n ** 2))
    lower = (center - spread) / denom
    upper = (center + spread) / denom
    return lower, upper


def compute_effect(raw_data, model, p_id):
    """Compute E[m,p] = mean_t(rate[m,p,t] - rate[m,default,t])."""
    effects = []
    for t in range(NUM_TASKS):
        rate_p = raw_data[model][(p_id, t)] / TOTAL_ROLLOUTS
        rate_d = raw_data[model][(0, t)] / TOTAL_ROLLOUTS
        effects.append(rate_p - rate_d)
    return sum(effects) / len(effects)


def build_effect_matrix(raw_data):
    """Build the 3x15 effect matrix E."""
    E = np.zeros((len(MODELS), NUM_NON_DEFAULT))
    for m_idx, model in enumerate(MODELS):
        for p_idx in range(NUM_NON_DEFAULT):
            E[m_idx, p_idx] = compute_effect(raw_data, model, p_idx + 1)
    return E


def find_pair(pairs, m1, m2):
    """Find the pair key for m1 and m2 regardless of order."""
    key1 = f"{m1}_vs_{m2}"
    key2 = f"{m2}_vs_{m1}"
    if key1 in pairs:
        return key1
    if key2 in pairs:
        return key2
    return None


@pytest.fixture
def report():
    with open("/app/output/report.json") as f:
        return json.load(f)


@pytest.fixture
def raw_data():
    return {model: load_from_db(model) for model in MODELS}


@pytest.fixture
def taxonomy():
    with open("/app/config/taxonomy.json") as f:
        return json.load(f)


# -- Structure Tests -----------------------------------------------------------

class TestOutputStructure:
    def test_report_exists(self):
        assert os.path.exists("/app/output/report.json"), "report.json not found"

    def test_required_keys(self, report):
        required = [
            "wilson_intervals", "effect_matrix", "eigendecomposition",
            "category_robustness", "interaction_strength",
            "model_ranking", "pairwise_tests"
        ]
        for key in required:
            assert key in report, f"Missing top-level key: {key}"

    def test_all_models_in_sections(self, report):
        for section in ["wilson_intervals", "effect_matrix", "category_robustness"]:
            for model in MODELS:
                assert model in report[section], \
                    f"Model {model} missing from {section}"


# -- Wilson Interval Tests -----------------------------------------------------

class TestWilsonIntervals:
    def test_cell_pi0_p0_t0(self, report, raw_data):
        """Verify Wilson CI for pi0, perturbation 0, task 0."""
        s = raw_data["pi0"][(0, 0)]
        rate = s / TOTAL_ROLLOUTS
        lo, hi = wilson_ci(s, TOTAL_ROLLOUTS)
        cell = report["wilson_intervals"]["pi0"]["0"]["0"]
        assert abs(cell["rate"] - rate) < 1e-6
        assert abs(cell["ci_lower"] - lo) < 1e-3
        assert abs(cell["ci_upper"] - hi) < 1e-3

    def test_cell_pi0fast_p5_t3(self, report, raw_data):
        """Verify Wilson CI for pi0_fast, perturbation 5, task 3."""
        s = raw_data["pi0_fast"][(5, 3)]
        rate = s / TOTAL_ROLLOUTS
        lo, hi = wilson_ci(s, TOTAL_ROLLOUTS)
        cell = report["wilson_intervals"]["pi0_fast"]["5"]["3"]
        assert abs(cell["rate"] - rate) < 1e-6
        assert abs(cell["ci_lower"] - lo) < 1e-3
        assert abs(cell["ci_upper"] - hi) < 1e-3

    def test_cell_groot_p15_t6(self, report, raw_data):
        """Verify Wilson CI for groot_n15, perturbation 15, task 6."""
        s = raw_data["groot_n15"][(15, 6)]
        rate = s / TOTAL_ROLLOUTS
        lo, hi = wilson_ci(s, TOTAL_ROLLOUTS)
        cell = report["wilson_intervals"]["groot_n15"]["15"]["6"]
        assert abs(cell["rate"] - rate) < 1e-6
        assert abs(cell["ci_lower"] - lo) < 1e-3
        assert abs(cell["ci_upper"] - hi) < 1e-3

    def test_ci_validity(self, report):
        """All CIs should satisfy 0 <= lower <= rate <= upper <= 1."""
        for model in MODELS:
            for p_id in report["wilson_intervals"][model]:
                for t_id in report["wilson_intervals"][model][p_id]:
                    cell = report["wilson_intervals"][model][p_id][t_id]
                    assert 0 <= cell["ci_lower"] <= cell["rate"] + 1e-9
                    assert cell["rate"] - 1e-9 <= cell["ci_upper"] <= 1.0


# -- Effect Matrix Tests -------------------------------------------------------

class TestEffectMatrix:
    def test_default_excluded(self, report):
        for model in MODELS:
            assert "default" not in report["effect_matrix"][model]

    def test_effect_count(self, report):
        for model in MODELS:
            assert len(report["effect_matrix"][model]) == NUM_NON_DEFAULT

    def test_specific_effect_pi0_vaug(self, report, raw_data):
        expected = compute_effect(raw_data, "pi0", 1)
        actual = report["effect_matrix"]["pi0"]["v_aug"]
        assert abs(actual - expected) < 1e-6

    def test_full_effect_matrix_pi0(self, report, raw_data):
        """Verify all 15 effects for pi0."""
        for p_idx, p_name in enumerate(PERTURBATION_NAMES):
            expected = compute_effect(raw_data, "pi0", p_idx + 1)
            actual = report["effect_matrix"]["pi0"][p_name]
            assert abs(actual - expected) < 1e-6, \
                f"Effect mismatch for pi0/{p_name}: {actual} != {expected}"

    def test_full_effect_matrix_groot(self, report, raw_data):
        """Verify all 15 effects for groot_n15."""
        for p_idx, p_name in enumerate(PERTURBATION_NAMES):
            expected = compute_effect(raw_data, "groot_n15", p_idx + 1)
            actual = report["effect_matrix"]["groot_n15"][p_name]
            assert abs(actual - expected) < 1e-6, \
                f"Effect mismatch for groot_n15/{p_name}: {actual} != {expected}"


# -- Eigendecomposition Tests --------------------------------------------------

class TestEigendecomposition:
    def test_eigenvalue_count(self, report):
        assert len(report["eigendecomposition"]["eigenvalues"]) == 2

    def test_eigenvector_count(self, report):
        assert len(report["eigendecomposition"]["eigenvectors"]) == 2

    def test_eigenvalues_descending(self, report):
        evals = report["eigendecomposition"]["eigenvalues"]
        assert evals[0] >= evals[1] - 1e-10

    def test_eigenvalues_nonnegative(self, report):
        for ev in report["eigendecomposition"]["eigenvalues"]:
            assert ev >= -1e-10

    def test_eigenvector_dimension(self, report):
        for evec in report["eigendecomposition"]["eigenvectors"]:
            assert len(evec) == NUM_NON_DEFAULT

    def test_eigenvectors_unit_norm(self, report):
        for evec in report["eigendecomposition"]["eigenvectors"]:
            norm = math.sqrt(sum(x ** 2 for x in evec))
            assert abs(norm - 1.0) < 1e-5

    def test_eigenvectors_orthogonal(self, report):
        evecs = report["eigendecomposition"]["eigenvectors"]
        dot = sum(a * b for a, b in zip(evecs[0], evecs[1]))
        assert abs(dot) < 1e-5

    def test_eigenvalues_correct(self, report, raw_data):
        """Independently compute eigenvalues and compare."""
        E = build_effect_matrix(raw_data)
        EtE = E.T @ E
        eigenvalues = sorted(np.linalg.eigvalsh(EtE), reverse=True)
        reported = report["eigendecomposition"]["eigenvalues"]
        for i in range(2):
            assert abs(reported[i] - eigenvalues[i]) < 1e-5, \
                f"Eigenvalue {i}: {reported[i]} != {eigenvalues[i]}"

    def test_eigenvectors_are_valid(self, report, raw_data):
        """Verify A @ v = lambda * v for reported eigenvectors."""
        E = build_effect_matrix(raw_data)
        EtE = E.T @ E
        evals = report["eigendecomposition"]["eigenvalues"]
        evecs = report["eigendecomposition"]["eigenvectors"]
        for i in range(len(evals)):
            v = np.array(evecs[i])
            Av = EtE @ v
            lv = evals[i] * v
            assert np.allclose(Av, lv, atol=1e-5), \
                f"Eigenvector {i} is not a valid eigenvector of E^T @ E"


# -- Category Robustness Tests -------------------------------------------------

class TestCategoryRobustness:
    def test_all_categories_present(self, report):
        expected = {"visual", "semantic", "behavioral",
                    "semantic_behavioral", "visual_behavioral",
                    "visual_semantic_behavioral"}
        for model in MODELS:
            assert set(report["category_robustness"][model].keys()) == expected

    def test_crs_range(self, report):
        for model in MODELS:
            for cat, crs in report["category_robustness"][model].items():
                assert crs <= 1.0 + 1e-9, f"CRS > 1 for {model}/{cat}"

    def test_crs_pi0_visual(self, report, raw_data):
        """Verify CRS for pi0, visual category."""
        visual_p_ids = [1, 2, 3, 4]
        effects_sq = []
        for p_id in visual_p_ids:
            e = compute_effect(raw_data, "pi0", p_id)
            effects_sq.append(e ** 2)
        expected = 1 - math.sqrt(sum(effects_sq) / len(effects_sq))
        actual = report["category_robustness"]["pi0"]["visual"]
        assert abs(actual - expected) < 1e-6

    def test_crs_pi0fast_behavioral(self, report, raw_data):
        """Verify CRS for pi0_fast, behavioral category."""
        e = compute_effect(raw_data, "pi0_fast", 10)
        expected = 1 - math.sqrt(e ** 2)
        actual = report["category_robustness"]["pi0_fast"]["behavioral"]
        assert abs(actual - expected) < 1e-6

    def test_crs_groot_semantic_behavioral(self, report, raw_data):
        """Verify CRS for groot_n15, semantic_behavioral."""
        p_ids = [11, 12]
        effects_sq = []
        for p_id in p_ids:
            e = compute_effect(raw_data, "groot_n15", p_id)
            effects_sq.append(e ** 2)
        expected = 1 - math.sqrt(sum(effects_sq) / len(effects_sq))
        actual = report["category_robustness"]["groot_n15"]["semantic_behavioral"]
        assert abs(actual - expected) < 1e-6


# -- Interaction Strength Tests ------------------------------------------------

class TestInteractionStrength:
    def test_all_compound_categories(self, report):
        expected = {"semantic_behavioral", "visual_behavioral",
                    "visual_semantic_behavioral"}
        assert set(report["interaction_strength"].keys()) == expected

    def test_pis_visual_behavioral(self, report, raw_data):
        """Verify PIS for visual_behavioral."""
        pis_per_model = []
        for model in MODELS:
            compound_abs = []
            for p_id in [13, 14]:
                compound_abs.append(abs(compute_effect(raw_data, model, p_id)))
            mean_compound = sum(compound_abs) / len(compound_abs)

            visual_abs = []
            for p_id in [1, 2, 3, 4]:
                visual_abs.append(abs(compute_effect(raw_data, model, p_id)))
            mean_visual = sum(visual_abs) / len(visual_abs)

            mean_behavioral = abs(compute_effect(raw_data, model, 10))

            pis_per_model.append(mean_compound - (mean_visual + mean_behavioral))

        expected = sum(pis_per_model) / len(pis_per_model)
        actual = report["interaction_strength"]["visual_behavioral"]
        assert abs(actual - expected) < 1e-6

    def test_pis_vsb(self, report, raw_data):
        """Verify PIS for visual_semantic_behavioral."""
        pis_per_model = []
        for model in MODELS:
            mean_compound = abs(compute_effect(raw_data, model, 15))

            v = [abs(compute_effect(raw_data, model, i)) for i in [1, 2, 3, 4]]
            mean_v = sum(v) / len(v)

            s = [abs(compute_effect(raw_data, model, i)) for i in [5, 6, 7, 8, 9]]
            mean_s = sum(s) / len(s)

            mean_b = abs(compute_effect(raw_data, model, 10))

            pis_per_model.append(mean_compound - (mean_v + mean_s + mean_b))

        expected = sum(pis_per_model) / len(pis_per_model)
        actual = report["interaction_strength"]["visual_semantic_behavioral"]
        assert abs(actual - expected) < 1e-6


# -- Model Ranking Tests -------------------------------------------------------

class TestModelRanking:
    def test_ranking_format(self, report):
        ranking = report["model_ranking"]
        assert isinstance(ranking, list)
        assert len(ranking) == len(MODELS)
        for entry in ranking:
            assert "model" in entry
            assert "score" in entry

    def test_ranking_descending(self, report):
        ranking = report["model_ranking"]
        for i in range(len(ranking) - 1):
            assert ranking[i]["score"] >= ranking[i + 1]["score"] - 1e-9

    def test_ranking_scores_correct(self, report, raw_data, taxonomy):
        """Verify ranking scores via independent harmonic mean computation."""
        all_categories = {}
        for cat, perts in taxonomy["categories"].items():
            all_categories[cat] = perts
        for cat, info in taxonomy["compound_categories"].items():
            all_categories[cat] = info["perturbations"]

        p_name_to_id = {name: idx + 1 for idx, name in enumerate(PERTURBATION_NAMES)}

        for model in MODELS:
            crs_vals = []
            for cat, perts in all_categories.items():
                e_sq = []
                for p_name in perts:
                    e = compute_effect(raw_data, model, p_name_to_id[p_name])
                    e_sq.append(e ** 2)
                crs = 1 - math.sqrt(sum(e_sq) / len(e_sq))
                crs_vals.append(crs)

            n = len(crs_vals)
            h_mean = n / sum(1 / c for c in crs_vals)

            found = False
            for entry in report["model_ranking"]:
                if entry["model"] == model:
                    assert abs(entry["score"] - h_mean) < 1e-5, \
                        f"Ranking score mismatch for {model}: {entry['score']} != {h_mean}"
                    found = True
                    break
            assert found, f"Model {model} not found in ranking"


# -- Pairwise Tests ------------------------------------------------------------

class TestPairwiseTests:
    def test_all_pairs_present(self, report):
        pairs = report["pairwise_tests"]
        for i in range(len(MODELS)):
            for j in range(i + 1, len(MODELS)):
                key = find_pair(pairs, MODELS[i], MODELS[j])
                assert key is not None, \
                    f"Missing pair for {MODELS[i]} vs {MODELS[j]}"

    def test_pvalue_range(self, report):
        for pair, result in report["pairwise_tests"].items():
            assert 0 <= result["p_value"] <= 1, \
                f"p-value out of range for {pair}: {result['p_value']}"

    def test_statistic_is_numeric(self, report):
        for pair, result in report["pairwise_tests"].items():
            assert isinstance(result["statistic"], (int, float))
            assert isinstance(result["p_value"], (int, float))

    def test_statistic_pi0_vs_pi0fast(self, report, raw_data):
        """Verify the test statistic for pi0 vs pi0_fast."""
        d = []
        for p_idx in range(NUM_NON_DEFAULT):
            p_id = p_idx + 1
            for t in range(NUM_TASKS):
                eff_pi0 = (raw_data["pi0"][(p_id, t)] - raw_data["pi0"][(0, t)]) / TOTAL_ROLLOUTS
                eff_fast = (raw_data["pi0_fast"][(p_id, t)] - raw_data["pi0_fast"][(0, t)]) / TOTAL_ROLLOUTS
                d.append(eff_pi0 - eff_fast)
        T_obs = sum(d) / len(d)

        key = find_pair(report["pairwise_tests"], "pi0", "pi0_fast")
        reported_T = report["pairwise_tests"][key]["statistic"]
        assert abs(abs(reported_T) - abs(T_obs)) < 1e-6, \
            f"Statistic mismatch: |{reported_T}| != |{T_obs}|"

    def test_groot_vs_pi0fast_significant(self, report):
        """groot_n15 vs pi0_fast should show significant difference."""
        key = find_pair(report["pairwise_tests"], "groot_n15", "pi0_fast")
        assert key is not None
        assert report["pairwise_tests"][key]["p_value"] < 0.05
