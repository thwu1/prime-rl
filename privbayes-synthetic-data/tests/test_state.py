
import json
import os

import numpy as np
import pandas as pd
import pytest
from scipy.stats import entropy, ks_2samp


DESC_PATH = "/app/output/description.json"
SYNTH_PATH = "/app/output/synthetic.csv"
DESC_PATH_2 = "/app/output/description_2.json"
SYNTH_PATH_2 = "/app/output/synthetic_2.csv"
DESC_PATH_LOW = "/app/output/description_low_eps.json"
SYNTH_PATH_LOW = "/app/output/synthetic_low_eps.csv"
REPORT_PATH = "/app/output/privacy_report.json"
REPORT_PATH_2 = "/app/output/privacy_report_2.json"
REPORT_PATH_LOW = "/app/output/privacy_report_low_eps.json"
INPUT_PATH = "/app/data/input.csv"

EXPECTED_COLUMNS = ["employee_id", "age", "department", "salary", "performance", "is_remote"]
EXPECTED_TYPES = {
    "employee_id": "Integer",
    "age": "Integer",
    "department": "String",
    "salary": "Float",
    "performance": "String",
    "is_remote": "String",
}
EXPECTED_CANDIDATE_KEYS = {"employee_id"}
EXPECTED_CATEGORICAL = {
    "employee_id": False,
    "age": False,
    "department": True,
    "salary": False,
    "performance": True,
    "is_remote": True,
}
EXPECTED_BN_ATTRS = {"age", "department", "salary", "performance", "is_remote"}


@pytest.fixture(scope="module")
def description():
    assert os.path.exists(DESC_PATH), f"Description file not found: {DESC_PATH}"
    with open(DESC_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def synthetic_df():
    assert os.path.exists(SYNTH_PATH), f"Synthetic CSV not found: {SYNTH_PATH}"
    return pd.read_csv(SYNTH_PATH)


@pytest.fixture(scope="module")
def input_df():
    return pd.read_csv(INPUT_PATH)


@pytest.fixture(scope="module")
def description_2():
    if not os.path.exists(DESC_PATH_2):
        pytest.skip("Second description file not found")
    with open(DESC_PATH_2) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def synthetic_df_2():
    if not os.path.exists(SYNTH_PATH_2):
        pytest.skip("Second synthetic CSV not found")
    return pd.read_csv(SYNTH_PATH_2)


@pytest.fixture(scope="module")
def description_low_eps():
    assert os.path.exists(DESC_PATH_LOW), f"Low-epsilon description not found: {DESC_PATH_LOW}"
    with open(DESC_PATH_LOW) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def synthetic_df_low_eps():
    assert os.path.exists(SYNTH_PATH_LOW), f"Low-epsilon synthetic CSV not found: {SYNTH_PATH_LOW}"
    return pd.read_csv(SYNTH_PATH_LOW)


@pytest.fixture(scope="module")
def privacy_report():
    assert os.path.exists(REPORT_PATH), f"Privacy report not found: {REPORT_PATH}"
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def privacy_report_2():
    if not os.path.exists(REPORT_PATH_2):
        pytest.skip("Second privacy report not found")
    with open(REPORT_PATH_2) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def privacy_report_low_eps():
    assert os.path.exists(REPORT_PATH_LOW), f"Low-eps privacy report not found: {REPORT_PATH_LOW}"
    with open(REPORT_PATH_LOW) as f:
        return json.load(f)


# ========== Structure Tests ==========

class TestOutputFilesExist:
    def test_description_json_exists(self):
        assert os.path.exists(DESC_PATH), "description.json must exist"

    def test_synthetic_csv_exists(self):
        assert os.path.exists(SYNTH_PATH), "synthetic.csv must exist"

    def test_low_eps_description_exists(self):
        assert os.path.exists(DESC_PATH_LOW), "low-epsilon description.json must exist"

    def test_low_eps_synthetic_exists(self):
        assert os.path.exists(SYNTH_PATH_LOW), "low-epsilon synthetic.csv must exist"

    def test_privacy_report_exists(self):
        assert os.path.exists(REPORT_PATH), "privacy_report.json must exist"

    def test_low_eps_privacy_report_exists(self):
        assert os.path.exists(REPORT_PATH_LOW), "low-epsilon privacy_report.json must exist"


class TestDescriptionStructure:
    def test_has_meta(self, description):
        assert "meta" in description, "description must have 'meta' key"

    def test_has_attribute_description(self, description):
        assert "attribute_description" in description

    def test_has_bayesian_network(self, description):
        assert "bayesian_network" in description

    def test_has_conditional_probabilities(self, description):
        assert "conditional_probabilities" in description


class TestMetaFields:
    def test_num_tuples(self, description):
        assert description["meta"]["num_tuples"] == 200

    def test_num_attributes(self, description):
        assert description["meta"]["num_attributes"] == 6

    def test_all_attributes(self, description):
        assert description["meta"]["all_attributes"] == EXPECTED_COLUMNS

    def test_candidate_keys(self, description):
        assert set(description["meta"]["candidate_keys"]) == EXPECTED_CANDIDATE_KEYS

    def test_attributes_in_bn(self, description):
        assert set(description["meta"]["attributes_in_BN"]) == EXPECTED_BN_ATTRS


# ========== Type Inference Tests ==========

class TestDataTypeInference:
    def test_employee_id_type(self, description):
        assert description["attribute_description"]["employee_id"]["data_type"] == "Integer"

    def test_age_type(self, description):
        assert description["attribute_description"]["age"]["data_type"] == "Integer"

    def test_department_type(self, description):
        assert description["attribute_description"]["department"]["data_type"] == "String"

    def test_salary_type(self, description):
        assert description["attribute_description"]["salary"]["data_type"] == "Float"

    def test_performance_type(self, description):
        assert description["attribute_description"]["performance"]["data_type"] == "String"

    def test_is_remote_type(self, description):
        assert description["attribute_description"]["is_remote"]["data_type"] == "String"


class TestCandidateKeyDetection:
    def test_employee_id_is_candidate_key(self, description):
        assert description["attribute_description"]["employee_id"]["is_candidate_key"] is True

    def test_age_not_candidate_key(self, description):
        assert description["attribute_description"]["age"]["is_candidate_key"] is False

    def test_department_not_candidate_key(self, description):
        assert description["attribute_description"]["department"]["is_candidate_key"] is False


class TestCategoricalDetection:
    def test_age_not_categorical(self, description):
        assert description["attribute_description"]["age"]["is_categorical"] is False

    def test_department_categorical(self, description):
        assert description["attribute_description"]["department"]["is_categorical"] is True

    def test_salary_not_categorical(self, description):
        assert description["attribute_description"]["salary"]["is_categorical"] is False

    def test_performance_categorical(self, description):
        assert description["attribute_description"]["performance"]["is_categorical"] is True

    def test_is_remote_categorical(self, description):
        assert description["attribute_description"]["is_remote"]["is_categorical"] is True


# ========== Attribute Description Tests ==========

class TestAttributeDescriptionFields:
    @pytest.mark.parametrize("attr", EXPECTED_COLUMNS)
    def test_required_fields_present(self, description, attr):
        ad = description["attribute_description"][attr]
        required = ["name", "data_type", "is_categorical", "is_candidate_key",
                     "min", "max", "missing_rate", "distribution_bins",
                     "distribution_probabilities"]
        for field in required:
            assert field in ad, f"Attribute {attr} missing field {field}"

    @pytest.mark.parametrize("attr", EXPECTED_COLUMNS)
    def test_name_matches_key(self, description, attr):
        assert description["attribute_description"][attr]["name"] == attr

    def test_missing_rate_salary(self, description):
        mr = description["attribute_description"]["salary"]["missing_rate"]
        assert 0.0 < mr < 0.15, f"salary missing_rate should be ~0.065, got {mr}"

    def test_missing_rate_performance(self, description):
        mr = description["attribute_description"]["performance"]["missing_rate"]
        assert 0.0 < mr < 0.10, f"performance missing_rate should be ~0.02, got {mr}"

    def test_missing_rate_age_zero(self, description):
        mr = description["attribute_description"]["age"]["missing_rate"]
        assert mr == 0.0, f"age should have no missing values, got {mr}"


# ========== Distribution Tests ==========

class TestDistributionNormalization:
    @pytest.mark.parametrize("attr", EXPECTED_COLUMNS)
    def test_probabilities_sum_to_one(self, description, attr):
        probs = description["attribute_description"][attr]["distribution_probabilities"]
        total = sum(probs)
        assert abs(total - 1.0) < 1e-6, f"{attr} probabilities sum to {total}, expected 1.0"

    @pytest.mark.parametrize("attr", EXPECTED_COLUMNS)
    def test_probabilities_non_negative(self, description, attr):
        probs = description["attribute_description"][attr]["distribution_probabilities"]
        for i, p in enumerate(probs):
            assert p >= 0, f"{attr} probability at index {i} is negative: {p}"

    def test_numerical_attr_has_20_bins(self, description):
        """Non-categorical numerical attributes should use 20 histogram bins."""
        age_bins = description["attribute_description"]["age"]["distribution_bins"]
        assert len(age_bins) == 20, f"age should have 20 bins, got {len(age_bins)}"

        salary_bins = description["attribute_description"]["salary"]["distribution_bins"]
        assert len(salary_bins) == 20, f"salary should have 20 bins, got {len(salary_bins)}"

    def test_categorical_bins_match_distinct_values(self, description):
        dept_bins = description["attribute_description"]["department"]["distribution_bins"]
        assert len(dept_bins) == 6, f"department should have 6 bins, got {len(dept_bins)}"

        remote_bins = description["attribute_description"]["is_remote"]["distribution_bins"]
        assert len(remote_bins) == 2, f"is_remote should have 2 bins, got {len(remote_bins)}"


# ========== Bayesian Network Tests ==========

class TestBayesianNetworkStructure:
    def test_bn_is_list(self, description):
        bn = description["bayesian_network"]
        assert isinstance(bn, list)

    def test_bn_entries_format(self, description):
        bn = description["bayesian_network"]
        for entry in bn:
            assert isinstance(entry, list) and len(entry) == 2, \
                f"BN entry must be [child, [parents]], got {entry}"
            child, parents = entry
            assert isinstance(child, str), f"child must be string, got {type(child)}"
            assert isinstance(parents, list), f"parents must be list, got {type(parents)}"
            assert len(parents) >= 1, "parents list must not be empty"

    def test_bn_children_are_bn_attrs(self, description):
        bn = description["bayesian_network"]
        bn_attrs = set(description["meta"]["attributes_in_BN"])
        children = {entry[0] for entry in bn}
        assert children.issubset(bn_attrs), \
            f"BN children {children} not subset of BN attrs {bn_attrs}"

    def test_bn_has_correct_number_of_entries(self, description):
        bn = description["bayesian_network"]
        bn_attrs = description["meta"]["attributes_in_BN"]
        assert len(bn) == len(bn_attrs) - 1, \
            f"BN should have {len(bn_attrs)-1} entries, got {len(bn)}"

    def test_bn_children_unique(self, description):
        bn = description["bayesian_network"]
        children = [entry[0] for entry in bn]
        assert len(children) == len(set(children)), "Each child must appear exactly once"

    def test_root_identifiable(self, description):
        """The root attribute appears as a parent but never as a child."""
        bn = description["bayesian_network"]
        bn_attrs = set(description["meta"]["attributes_in_BN"])
        children = {entry[0] for entry in bn}
        roots = bn_attrs - children
        assert len(roots) == 1, f"Expected exactly 1 root, found {roots}"
        root = roots.pop()
        assert root == bn[0][1][0], \
            f"Root {root} should be first parent of first BN entry, got {bn[0][1][0]}"

    def test_max_parents_respected(self, description):
        bn = description["bayesian_network"]
        for child, parents in bn:
            assert len(parents) <= 2, \
                f"Attribute {child} has {len(parents)} parents, max is 2"

    def test_parents_are_preceding_nodes(self, description):
        """Each node's parents must have been added before it (topological order)."""
        bn = description["bayesian_network"]
        root = bn[0][1][0]
        added = {root}
        for child, parents in bn:
            for p in parents:
                assert p in added, \
                    f"Parent {p} of {child} not yet added to network"
            added.add(child)


# ========== Conditional Probability Tests ==========

class TestConditionalProbabilities:
    def test_root_has_flat_list(self, description):
        bn = description["bayesian_network"]
        bn_attrs = set(description["meta"]["attributes_in_BN"])
        children = {entry[0] for entry in bn}
        root = (bn_attrs - children).pop()

        cp = description["conditional_probabilities"]
        assert root in cp, f"Root {root} missing from conditional_probabilities"
        assert isinstance(cp[root], list), f"Root distribution must be a flat list"

    def test_root_distribution_normalized(self, description):
        bn = description["bayesian_network"]
        bn_attrs = set(description["meta"]["attributes_in_BN"])
        children = {entry[0] for entry in bn}
        root = (bn_attrs - children).pop()

        dist = description["conditional_probabilities"][root]
        total = sum(dist)
        assert abs(total - 1.0) < 1e-6, f"Root distribution sums to {total}"
        for p in dist:
            assert p >= 0, f"Root distribution has negative value"

    def test_children_have_dicts(self, description):
        bn = description["bayesian_network"]
        cp = description["conditional_probabilities"]
        for child, parents in bn:
            assert child in cp, f"Child {child} missing from conditional_probabilities"
            assert isinstance(cp[child], dict), \
                f"Child {child} conditional probs must be a dict, got {type(cp[child])}"

    def test_conditional_distributions_normalized(self, description):
        bn = description["bayesian_network"]
        cp = description["conditional_probabilities"]
        for child, parents in bn:
            child_cp = cp[child]
            for key, dist in child_cp.items():
                total = sum(dist)
                assert abs(total - 1.0) < 1e-6, \
                    f"Conditional dist for {child}|{key} sums to {total}"
                for p in dist:
                    assert p >= 0, \
                        f"Conditional dist for {child}|{key} has negative value"

    def test_conditional_keys_are_stringified_lists(self, description):
        bn = description["bayesian_network"]
        cp = description["conditional_probabilities"]
        for child, parents in bn:
            child_cp = cp[child]
            for key in child_cp.keys():
                parsed = eval(key)
                assert isinstance(parsed, list), \
                    f"Conditional key {key} for {child} should parse to a list"

    def test_conditional_key_length_matches_parents(self, description):
        """Each conditional key must have as many elements as the node has parents."""
        bn = description["bayesian_network"]
        cp = description["conditional_probabilities"]
        for child, parents in bn:
            child_cp = cp[child]
            for key in child_cp.keys():
                parsed = eval(key)
                assert len(parsed) == len(parents), \
                    f"Key {key} for {child} has {len(parsed)} values but {len(parents)} parents"


# ========== Synthetic CSV Tests ==========

class TestSyntheticCSV:
    def test_column_names(self, synthetic_df):
        assert list(synthetic_df.columns) == EXPECTED_COLUMNS

    def test_row_count(self, synthetic_df):
        assert len(synthetic_df) == 500, f"Expected 500 rows, got {len(synthetic_df)}"

    def test_candidate_key_sequential(self, synthetic_df):
        """Candidate key should be sequential integers starting at 0."""
        ids = synthetic_df["employee_id"].tolist()
        assert ids == list(range(500)), "employee_id should be 0..499"

    def test_department_values_valid(self, synthetic_df, input_df):
        """Synthetic department values should be from the original domain."""
        original_depts = set(input_df["department"].dropna().unique())
        synthetic_depts = set(synthetic_df["department"].dropna().unique())
        assert synthetic_depts.issubset(original_depts), \
            f"Synthetic departments {synthetic_depts - original_depts} not in original"

    def test_is_remote_values_valid(self, synthetic_df):
        values = set(synthetic_df["is_remote"].dropna().unique())
        assert values.issubset({"Yes", "No"}), f"is_remote has invalid values: {values}"

    def test_age_is_integer(self, synthetic_df):
        ages = synthetic_df["age"].dropna()
        assert all(float(x).is_integer() for x in ages), "age values should be integers"

    def test_salary_is_numeric(self, synthetic_df):
        salaries = synthetic_df["salary"].dropna()
        assert pd.to_numeric(salaries, errors="coerce").notna().all(), \
            "salary values should be numeric"


# ========== Statistical Quality Tests ==========

def _kl_divergence(p, q):
    """KL divergence D(p || q) with smoothing."""
    p = np.array(p, dtype=float)
    q = np.array(q, dtype=float)
    eps = 1e-10
    p = p + eps
    q = q + eps
    p = p / p.sum()
    q = q / q.sum()
    return float(entropy(p, q))


class TestStatisticalQuality:
    def test_department_kl_divergence(self, input_df, synthetic_df):
        orig_dist = input_df["department"].value_counts(normalize=True).sort_index()
        synth_dist = synthetic_df["department"].value_counts(normalize=True).sort_index()
        all_vals = sorted(set(orig_dist.index) | set(synth_dist.index))
        p = [orig_dist.get(v, 0) for v in all_vals]
        q = [synth_dist.get(v, 0) for v in all_vals]
        kl = _kl_divergence(p, q)
        assert kl < 1.0, f"department KL divergence {kl:.4f} >= 1.0"

    def test_performance_kl_divergence(self, input_df, synthetic_df):
        orig_dist = input_df["performance"].dropna().value_counts(normalize=True).sort_index()
        synth_dist = synthetic_df["performance"].dropna().value_counts(normalize=True).sort_index()
        all_vals = sorted(set(orig_dist.index) | set(synth_dist.index))
        p = [orig_dist.get(v, 0) for v in all_vals]
        q = [synth_dist.get(v, 0) for v in all_vals]
        kl = _kl_divergence(p, q)
        assert kl < 1.0, f"performance KL divergence {kl:.4f} >= 1.0"

    def test_is_remote_kl_divergence(self, input_df, synthetic_df):
        orig_dist = input_df["is_remote"].value_counts(normalize=True).sort_index()
        synth_dist = synthetic_df["is_remote"].value_counts(normalize=True).sort_index()
        all_vals = sorted(set(orig_dist.index) | set(synth_dist.index))
        p = [orig_dist.get(v, 0) for v in all_vals]
        q = [synth_dist.get(v, 0) for v in all_vals]
        kl = _kl_divergence(p, q)
        assert kl < 1.0, f"is_remote KL divergence {kl:.4f} >= 1.0"

    def test_age_ks_statistic(self, input_df, synthetic_df):
        stat, _ = ks_2samp(input_df["age"].dropna(), synthetic_df["age"].dropna())
        assert stat < 0.4, f"age KS statistic {stat:.4f} >= 0.4"

    def test_salary_ks_statistic(self, input_df, synthetic_df):
        stat, _ = ks_2samp(input_df["salary"].dropna(), synthetic_df["salary"].dropna())
        assert stat < 0.4, f"salary KS statistic {stat:.4f} >= 0.4"


# ========== Determinism Test ==========

class TestDeterminism:
    def test_description_identical(self, description, description_2):
        assert description == description_2, \
            "Running with same seed must produce identical description.json"

    def test_synthetic_csv_identical(self, synthetic_df, synthetic_df_2):
        pd.testing.assert_frame_equal(synthetic_df, synthetic_df_2, check_dtype=False)

    def test_privacy_report_identical(self, privacy_report, privacy_report_2):
        assert privacy_report == privacy_report_2, \
            "Running with same seed must produce identical privacy report"


# ========== Privacy Budget Tests ==========

class TestPrivacyBudget:
    def test_noisy_marginals_differ_from_empirical(self, description, input_df):
        """With epsilon=1.0, marginal distributions should show evidence of noise injection."""
        dept_probs = description["attribute_description"]["department"]["distribution_probabilities"]
        dept_bins = description["attribute_description"]["department"]["distribution_bins"]
        empirical = input_df["department"].value_counts(normalize=True)

        diffs = []
        for i, b in enumerate(dept_bins):
            emp_p = empirical.get(b, 0)
            diffs.append(abs(dept_probs[i] - emp_p))

        max_diff = max(diffs)
        assert max_diff > 1e-10, \
            "Marginal distributions should show noise injection (max diff too small)"

    def test_bn_attributes_all_have_noisy_distributions(self, description):
        """All BN attributes should have valid noisy distributions."""
        bn_attrs = description["meta"]["attributes_in_BN"]
        for attr in bn_attrs:
            probs = description["attribute_description"][attr]["distribution_probabilities"]
            assert len(probs) > 0, f"Attribute {attr} has empty distribution"
            assert abs(sum(probs) - 1.0) < 1e-6, \
                f"Attribute {attr} distribution doesn't sum to 1"


# ========== Privacy Report Tests ==========

class TestPrivacyReport:
    def test_has_total_epsilon(self, privacy_report):
        assert "total_epsilon" in privacy_report
        assert privacy_report["total_epsilon"] == 1.0

    def test_has_budget_allocation(self, privacy_report):
        assert "budget_allocation" in privacy_report
        assert isinstance(privacy_report["budget_allocation"], dict)

    def test_budget_has_multiple_phases(self, privacy_report):
        assert len(privacy_report["budget_allocation"]) >= 2, \
            "Budget allocation must have at least 2 phases"

    def test_budget_allocation_sums_to_total(self, privacy_report):
        total_alloc = sum(
            v["epsilon"] for v in privacy_report["budget_allocation"].values()
        )
        assert abs(total_alloc - privacy_report["total_epsilon"]) < 1e-6, \
            f"Budget allocation sum {total_alloc} != total_epsilon {privacy_report['total_epsilon']}"

    def test_budget_allocation_phase_format(self, privacy_report):
        for phase_name, phase_data in privacy_report["budget_allocation"].items():
            assert isinstance(phase_name, str), "Phase name must be a string"
            assert "epsilon" in phase_data, f"Phase {phase_name} missing 'epsilon' key"
            assert isinstance(phase_data["epsilon"], (int, float)), \
                f"Phase {phase_name} epsilon must be numeric"
            assert phase_data["epsilon"] > 0, \
                f"Phase {phase_name} epsilon must be positive"

    def test_has_per_attribute_noise(self, privacy_report):
        assert "per_attribute_noise" in privacy_report
        assert isinstance(privacy_report["per_attribute_noise"], dict)

    def test_per_attribute_noise_covers_bn_attrs(self, privacy_report, description):
        bn_attrs = set(description["meta"]["attributes_in_BN"])
        noise_attrs = set(privacy_report["per_attribute_noise"].keys())
        assert bn_attrs == noise_attrs, \
            f"per_attribute_noise keys {noise_attrs} must match BN attrs {bn_attrs}"

    def test_per_attribute_noise_format(self, privacy_report):
        for attr, info in privacy_report["per_attribute_noise"].items():
            assert "noise_scale" in info, f"{attr} missing noise_scale"
            assert "epsilon_share" in info, f"{attr} missing epsilon_share"
            assert isinstance(info["noise_scale"], (int, float)), \
                f"{attr} noise_scale must be numeric"
            assert isinstance(info["epsilon_share"], (int, float)), \
                f"{attr} epsilon_share must be numeric"
            assert info["noise_scale"] > 0, f"{attr} noise_scale must be positive"
            assert info["epsilon_share"] > 0, f"{attr} epsilon_share must be positive"

    def test_different_epsilon_different_noise_scales(self, privacy_report, privacy_report_low_eps):
        """Different --epsilon must produce different noise scales."""
        any_differ = False
        for attr in privacy_report["per_attribute_noise"]:
            if attr in privacy_report_low_eps["per_attribute_noise"]:
                scale_high = privacy_report["per_attribute_noise"][attr]["noise_scale"]
                scale_low = privacy_report_low_eps["per_attribute_noise"][attr]["noise_scale"]
                if abs(scale_high - scale_low) > 1e-10:
                    any_differ = True
                    break
        assert any_differ, \
            "Different epsilon values must produce different noise scales"

    def test_low_eps_total_epsilon(self, privacy_report_low_eps):
        assert privacy_report_low_eps["total_epsilon"] == 0.5

    def test_low_eps_budget_sums(self, privacy_report_low_eps):
        total_alloc = sum(
            v["epsilon"] for v in privacy_report_low_eps["budget_allocation"].values()
        )
        assert abs(total_alloc - 0.5) < 1e-6, \
            f"Low-eps budget allocation sum {total_alloc} != 0.5"

    def test_low_eps_per_attribute_noise_positive(self, privacy_report_low_eps):
        for attr, info in privacy_report_low_eps["per_attribute_noise"].items():
            assert info["noise_scale"] > 0, \
                f"Low-eps {attr} noise_scale must be positive"
            assert info["epsilon_share"] > 0, \
                f"Low-eps {attr} epsilon_share must be positive"


# ========== Multi-Epsilon Validation Tests ==========

class TestMultiEpsilon:
    """Verify that varying --epsilon produces valid but different outputs."""

    def test_low_eps_valid_structure(self, description_low_eps):
        """Low-epsilon output must have all required top-level keys."""
        assert "meta" in description_low_eps
        assert "attribute_description" in description_low_eps
        assert "bayesian_network" in description_low_eps
        assert "conditional_probabilities" in description_low_eps

    def test_low_eps_meta_tuples(self, description_low_eps):
        """Meta should still reflect the input dataset, not the output size."""
        assert description_low_eps["meta"]["num_tuples"] == 200

    def test_low_eps_row_count(self, synthetic_df_low_eps):
        """Different --num-rows must produce the requested count."""
        assert len(synthetic_df_low_eps) == 300, \
            f"Expected 300 rows for low-eps run, got {len(synthetic_df_low_eps)}"

    def test_low_eps_columns(self, synthetic_df_low_eps):
        assert list(synthetic_df_low_eps.columns) == EXPECTED_COLUMNS

    def test_low_eps_candidate_key_sequential(self, synthetic_df_low_eps):
        """Candidate key should be sequential 0..num_rows-1."""
        ids = synthetic_df_low_eps["employee_id"].tolist()
        assert ids == list(range(300)), "employee_id should be 0..299"

    def test_low_eps_distributions_normalized(self, description_low_eps):
        """All probability distributions must be valid even with lower epsilon."""
        for attr in EXPECTED_COLUMNS:
            probs = description_low_eps["attribute_description"][attr]["distribution_probabilities"]
            total = sum(probs)
            assert abs(total - 1.0) < 1e-6, \
                f"{attr} probabilities sum to {total} in low-eps output"
            for i, p in enumerate(probs):
                assert p >= 0, \
                    f"{attr} probability at index {i} is negative in low-eps output"

    def test_low_eps_bn_valid(self, description_low_eps):
        """BN structure must be valid for low-epsilon output."""
        bn = description_low_eps["bayesian_network"]
        bn_attrs = set(description_low_eps["meta"]["attributes_in_BN"])
        children = {entry[0] for entry in bn}
        assert len(bn) == len(bn_attrs) - 1, \
            f"Low-eps BN should have {len(bn_attrs)-1} entries, got {len(bn)}"
        assert children.issubset(bn_attrs)
        root_candidates = bn_attrs - children
        assert len(root_candidates) == 1
        root = root_candidates.pop()
        added = {root}
        for child, parents in bn:
            for p in parents:
                assert p in added, \
                    f"Low-eps BN: parent {p} of {child} not yet added"
            added.add(child)

    def test_low_eps_conditional_probs_valid(self, description_low_eps):
        """Conditional distributions must be normalized for low-epsilon output."""
        bn = description_low_eps["bayesian_network"]
        cp = description_low_eps["conditional_probabilities"]
        bn_attrs = set(description_low_eps["meta"]["attributes_in_BN"])
        children = {entry[0] for entry in bn}
        root = (bn_attrs - children).pop()
        assert isinstance(cp[root], list)
        assert abs(sum(cp[root]) - 1.0) < 1e-6
        for child, parents in bn:
            assert isinstance(cp[child], dict)
            for key, dist in cp[child].items():
                assert abs(sum(dist) - 1.0) < 1e-6

    def test_epsilon_affects_distributions(self, description, description_low_eps):
        """Different epsilon values must produce numerically different distributions."""
        attrs_to_check = ["department", "is_remote", "performance"]
        any_differ = False
        for attr in attrs_to_check:
            probs_high = description["attribute_description"][attr]["distribution_probabilities"]
            probs_low = description_low_eps["attribute_description"][attr]["distribution_probabilities"]
            if probs_high != probs_low:
                any_differ = True
                break
        assert any_differ, \
            "Different epsilon values should produce different noisy distributions"

    def test_low_eps_department_values_valid(self, synthetic_df_low_eps, input_df):
        """Low-epsilon synthetic department values should still be from original domain."""
        original_depts = set(input_df["department"].dropna().unique())
        synthetic_depts = set(synthetic_df_low_eps["department"].dropna().unique())
        assert synthetic_depts.issubset(original_depts), \
            f"Low-eps synthetic departments {synthetic_depts - original_depts} not in original"

    def test_low_eps_statistical_quality(self, input_df, synthetic_df_low_eps):
        """Even with lower epsilon, categorical KL divergence should be bounded."""
        orig_dist = input_df["department"].value_counts(normalize=True).sort_index()
        synth_dist = synthetic_df_low_eps["department"].value_counts(normalize=True).sort_index()
        all_vals = sorted(set(orig_dist.index) | set(synth_dist.index))
        p = [orig_dist.get(v, 0) for v in all_vals]
        q = [synth_dist.get(v, 0) for v in all_vals]
        kl = _kl_divergence(p, q)
        assert kl < 2.0, f"Low-eps department KL divergence {kl:.4f} >= 2.0"
