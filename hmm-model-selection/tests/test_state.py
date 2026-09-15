
import json
import numpy as np
import pytest


# Ground truth values embedded directly (not accessible to agent at runtime)
_TRUE_EMISSION_MEANS = [-2.0, 0.5, 3.0]
_TRUE_EMISSION_STDS = [0.4, 0.3, 0.6]
_TRUE_TRANSITION = [
    [0.75, 0.15, 0.10],
    [0.10, 0.75, 0.15],
    [0.15, 0.10, 0.75],
]
_TRUE_TEST_STATES_SEQ0 = [
    2, 2, 2, 2, 2, 2, 2, 1, 1, 2, 2, 2, 2, 2, 0, 0, 1, 1, 1, 1,
    1, 1, 2, 2, 2, 1, 1, 2, 2, 2, 2, 1, 0, 2, 2, 2, 2, 2, 2, 0,
]
_TRUE_TEST_STATES_SEQ1 = [
    1, 1, 1, 1, 2, 1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 0,
    0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 1, 2, 1, 0, 0, 0, 0, 0, 0, 1,
]
_REF_TOTAL_TEST_LOGLIK = -104.2417056537


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


class TestResultsFormat:
    def test_results_file_has_required_keys(self, results):
        required_keys = [
            "selected_K",
            "test_loglik_K2",
            "test_loglik_K3",
            "emission_means",
            "emission_stds",
            "transition_matrix",
            "decoded_states_seq0",
            "decoded_states_seq1",
            "num_divergences",
            "max_rhat",
        ]
        for key in required_keys:
            assert key in results, f"Missing required key: {key}"

    def test_emission_means_length(self, results):
        K = results["selected_K"]
        assert len(results["emission_means"]) == K

    def test_emission_stds_length(self, results):
        K = results["selected_K"]
        assert len(results["emission_stds"]) == K

    def test_transition_matrix_shape(self, results):
        K = results["selected_K"]
        trans = results["transition_matrix"]
        assert len(trans) == K
        for row in trans:
            assert len(row) == K

    def test_decoded_states_length(self, results):
        test_obs = np.load("/app/data/holdout/obs.npy")
        T_test = test_obs.shape[1]
        for seq_idx in range(2):
            states = results[f"decoded_states_seq{seq_idx}"]
            assert len(states) == T_test, (
                f"Sequence {seq_idx}: expected {T_test} states, got {len(states)}"
            )


class TestModelSelection:
    def test_selected_K_is_3(self, results):
        assert results["selected_K"] == 3, (
            f"Expected K=3 to be selected, got K={results['selected_K']}"
        )

    def test_K3_beats_K2(self, results):
        assert results["test_loglik_K3"] > results["test_loglik_K2"], (
            f"K=3 log-lik ({results['test_loglik_K3']:.2f}) should exceed "
            f"K=2 log-lik ({results['test_loglik_K2']:.2f})"
        )

    def test_test_loglik_K3_finite(self, results):
        assert np.isfinite(results["test_loglik_K3"]), "test_loglik_K3 is not finite"

    def test_test_loglik_K3_reasonable(self, results):
        est_total = results["test_loglik_K3"]
        assert est_total > -300, f"test_loglik_K3={est_total:.2f} seems far too low"
        assert abs(est_total - _REF_TOTAL_TEST_LOGLIK) < 25, (
            f"test_loglik_K3={est_total:.2f} differs from expected range by "
            f"more than 25 nats"
        )


class TestParameterRecovery:
    def test_emission_means_close_to_truth(self, results):
        estimated = np.array(results["emission_means"])
        true_vals = np.array(_TRUE_EMISSION_MEANS)
        for i in range(3):
            assert abs(estimated[i] - true_vals[i]) < 0.7, (
                f"mu[{i}]: estimated={estimated[i]:.3f}, expected within 0.7 "
                f"of {true_vals[i]:.3f}"
            )

    def test_emission_means_ordered(self, results):
        mu = results["emission_means"]
        for i in range(len(mu) - 1):
            assert mu[i] < mu[i + 1], (
                f"Emission means not ordered: mu[{i}]={mu[i]:.3f} >= "
                f"mu[{i+1}]={mu[i+1]:.3f}"
            )

    def test_emission_stds_close_to_truth(self, results):
        estimated = np.array(results["emission_stds"])
        true_vals = np.array(_TRUE_EMISSION_STDS)
        for i in range(3):
            assert abs(estimated[i] - true_vals[i]) < 0.4, (
                f"sigma[{i}]: estimated={estimated[i]:.3f}, expected within 0.4 "
                f"of {true_vals[i]:.3f}"
            )

    def test_emission_stds_positive(self, results):
        for i, s in enumerate(results["emission_stds"]):
            assert s > 0, f"sigma[{i}]={s} is not positive"

    def test_transition_rows_sum_to_one(self, results):
        trans = np.array(results["transition_matrix"])
        for i in range(trans.shape[0]):
            row_sum = np.sum(trans[i])
            assert abs(row_sum - 1.0) < 0.02, (
                f"Transition row {i} sums to {row_sum:.4f}, not ~1.0"
            )

    def test_transition_diagonal_dominant(self, results):
        trans = np.array(results["transition_matrix"])
        for i in range(trans.shape[0]):
            assert trans[i, i] > 0.4, (
                f"Transition[{i},{i}]={trans[i,i]:.3f} not dominant (< 0.4)"
            )

    def test_transition_close_to_truth(self, results):
        trans = np.array(results["transition_matrix"])
        true_trans = np.array(_TRUE_TRANSITION)
        max_diff = np.max(np.abs(trans - true_trans))
        assert max_diff < 0.25, (
            f"Transition matrix max elementwise error = {max_diff:.3f} > 0.25"
        )


class TestStateDecoding:
    def test_decoding_accuracy_seq0(self, results):
        estimated = np.array(results["decoded_states_seq0"])
        true_vals = np.array(_TRUE_TEST_STATES_SEQ0)
        accuracy = np.mean(estimated == true_vals)
        assert accuracy > 0.65, (
            f"Sequence 0 decoding accuracy = {accuracy:.3f} (need > 0.65)"
        )

    def test_decoding_accuracy_seq1(self, results):
        estimated = np.array(results["decoded_states_seq1"])
        true_vals = np.array(_TRUE_TEST_STATES_SEQ1)
        accuracy = np.mean(estimated == true_vals)
        assert accuracy > 0.65, (
            f"Sequence 1 decoding accuracy = {accuracy:.3f} (need > 0.65)"
        )

    def test_decoded_states_valid(self, results):
        K = results["selected_K"]
        for seq_idx in range(2):
            states = results[f"decoded_states_seq{seq_idx}"]
            for t, s in enumerate(states):
                assert 0 <= s < K, (
                    f"Seq {seq_idx}, t={t}: state {s} out of range [0, {K})"
                )


class TestMCMCDiagnostics:
    def test_no_divergences(self, results):
        assert results["num_divergences"] == 0, (
            f"Got {results['num_divergences']} divergent transitions"
        )

    def test_rhat_acceptable(self, results):
        assert results["max_rhat"] < 1.1, (
            f"max r_hat = {results['max_rhat']:.4f} (need < 1.1)"
        )
