"""
Tests for the semi-supervised Hidden Markov Model implementation.

Verifies forward algorithm correctness, forward-backward marginal posteriors,
Viterbi and marginal decoding against brute-force enumeration, decoder
comparison evaluation, and MCMC convergence with parameter recovery.

"""

import itertools
import sys
sys.path.insert(0, '/app')

import jax.numpy as jnp
from jax import random
from jax.scipy.special import logsumexp
import numpyro.distributions as dist
import numpy as np
import pytest

from model import (forward_one_step, forward_log_prob,
                   simulate_data, run_inference, viterbi_decode,
                   forward_backward, marginal_decode, evaluate_decoders)


# ---------------------------------------------------------------------------
# Helper: brute-force marginal posteriors for small HMMs
# ---------------------------------------------------------------------------

def _brute_force_marginals(words, transition_prob, emission_prob):
    """Compute exact marginal posteriors by enumerating all state sequences."""
    C = transition_prob.shape[0]
    T = len(words)
    marginals = np.zeros((T, C))
    for seq in itertools.product(range(C), repeat=T):
        p = 1.0 / C * float(emission_prob[seq[0], words[0]])
        for t in range(1, T):
            p *= float(transition_prob[seq[t - 1], seq[t]])
            p *= float(emission_prob[seq[t], words[t]])
        for t in range(T):
            marginals[t, seq[t]] += p
    for t in range(T):
        marginals[t] /= marginals[t].sum()
    return marginals


# ===========================================================================
# Forward algorithm tests
# ===========================================================================

class TestForwardAlgorithm:
    """Test the forward algorithm against brute-force enumeration."""

    def test_forward_one_step_output_shape(self):
        """Output of forward_one_step must have shape (num_categories,)."""
        num_categories = 3
        num_words = 5
        prev_log_prob = jnp.log(jnp.array([0.2, 0.5, 0.3]))
        transition_log_prob = jnp.log(jnp.array([
            [0.7, 0.2, 0.1],
            [0.1, 0.6, 0.3],
            [0.3, 0.3, 0.4],
        ]))
        emission_log_prob = jnp.log(
            jnp.ones((num_categories, num_words)) / num_words
        )
        result = forward_one_step(
            prev_log_prob, 0, transition_log_prob, emission_log_prob
        )
        assert result.shape == (num_categories,), (
            f"Expected shape ({num_categories},), got {result.shape}"
        )

    def test_forward_one_step_correctness(self):
        """Test forward_one_step against manual computation.

        For prev_prob = [0.6, 0.4], word = 1:
          alpha_new[j] = sum_i prev_prob[i] * T[i,j] * E[j, word]
          alpha_new[0] = 0.6*0.7*0.3 + 0.4*0.4*0.3 = 0.174
          alpha_new[1] = 0.6*0.3*0.4 + 0.4*0.6*0.4 = 0.168
        """
        transition_prob = jnp.array([[0.7, 0.3], [0.4, 0.6]])
        emission_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.1, 0.4, 0.5],
        ])
        prev_prob = jnp.array([0.6, 0.4])
        curr_word = 1

        expected = jnp.array([
            0.6 * 0.7 * 0.3 + 0.4 * 0.4 * 0.3,
            0.6 * 0.3 * 0.4 + 0.4 * 0.6 * 0.4,
        ])

        result = forward_one_step(
            jnp.log(prev_prob), curr_word,
            jnp.log(transition_prob), jnp.log(emission_prob),
        )
        np.testing.assert_allclose(
            np.array(jnp.exp(result)), np.array(expected), atol=1e-6,
            err_msg="forward_one_step produced incorrect values",
        )

    def test_forward_log_prob_matches_brute_force(self):
        """Compare forward algorithm to brute-force enumeration.

        Uses a 2-category, 3-word model with sequence [0, 2, 1].
        Enumerates all 2^3 = 8 state sequences.
        """
        transition_prob = jnp.array([[0.7, 0.3], [0.4, 0.6]])
        emission_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.1, 0.4, 0.5],
        ])
        words = jnp.array([0, 2, 1])
        num_categories = 2

        per_state = np.zeros(num_categories)
        for s0 in range(num_categories):
            for s1 in range(num_categories):
                for s2 in range(num_categories):
                    p = (0.5
                         * float(emission_prob[s0, words[0]])
                         * float(transition_prob[s0, s1])
                         * float(emission_prob[s1, words[1]])
                         * float(transition_prob[s1, s2])
                         * float(emission_prob[s2, words[2]]))
                    per_state[s2] += p

        brute_force_total = np.log(np.sum(per_state))
        brute_force_per_state = np.log(per_state)

        transition_log_prob = jnp.log(transition_prob)
        emission_log_prob = jnp.log(emission_prob)
        init_log_prob = (
            jnp.log(jnp.array([0.5, 0.5]))
            + emission_log_prob[:, words[0]]
        )
        result = forward_log_prob(
            init_log_prob, words[1:], transition_log_prob, emission_log_prob,
        )
        forward_total = float(logsumexp(result))

        np.testing.assert_allclose(
            forward_total, brute_force_total, atol=1e-5,
            err_msg="Forward algorithm total log-prob does not match brute force",
        )
        np.testing.assert_allclose(
            np.array(result), brute_force_per_state, atol=1e-5,
            err_msg="Forward algorithm per-state log-probs do not match brute force",
        )

    def test_forward_log_prob_longer_sequence(self):
        """Test forward algorithm on a longer sequence with 3 categories.

        Uses 3 categories, 5 words, sequence of length 5. Compares to
        brute-force enumeration over all 3^5 = 243 state sequences.
        """
        transition_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.2, 0.5, 0.3],
            [0.1, 0.3, 0.6],
        ])
        emission_prob = jnp.array([
            [0.4, 0.3, 0.1, 0.1, 0.1],
            [0.1, 0.1, 0.4, 0.3, 0.1],
            [0.1, 0.1, 0.1, 0.3, 0.4],
        ])
        words = jnp.array([0, 3, 2, 4, 1])
        num_categories = 3

        per_state = np.zeros(num_categories)
        for s0 in range(num_categories):
            for s1 in range(num_categories):
                for s2 in range(num_categories):
                    for s3 in range(num_categories):
                        for s4 in range(num_categories):
                            states = [s0, s1, s2, s3, s4]
                            p = 1.0 / num_categories
                            p *= float(emission_prob[s0, words[0]])
                            for t in range(1, 5):
                                p *= float(transition_prob[states[t-1], states[t]])
                                p *= float(emission_prob[states[t], words[t]])
                            per_state[s4] += p

        brute_force_per_state = np.log(per_state)

        transition_log_prob = jnp.log(transition_prob)
        emission_log_prob = jnp.log(emission_prob)
        init_log_prob = (
            jnp.log(jnp.ones(num_categories) / num_categories)
            + emission_log_prob[:, words[0]]
        )
        result = forward_log_prob(
            init_log_prob, words[1:], transition_log_prob, emission_log_prob,
        )

        np.testing.assert_allclose(
            np.array(result), brute_force_per_state, atol=1e-5,
            err_msg="Forward algorithm failed on 3-category, 5-step sequence",
        )

    def test_forward_no_nan(self):
        """Forward algorithm must not produce NaN for valid random inputs."""
        num_categories = 3
        num_words = 10
        k1, k2 = random.split(random.key(99))

        transition_prob = dist.Dirichlet(jnp.ones(num_categories)).sample(
            key=k1, sample_shape=(num_categories,),
        )
        emission_prob = dist.Dirichlet(jnp.ones(num_words) * 0.1).sample(
            key=k2, sample_shape=(num_categories,),
        )

        words = jnp.array([0, 5, 3, 7, 2, 9, 1, 4, 8, 6])

        transition_log_prob = jnp.log(transition_prob)
        emission_log_prob = jnp.log(emission_prob)
        init_log_prob = emission_log_prob[:, words[0]]

        result = forward_log_prob(
            init_log_prob, words[1:], transition_log_prob, emission_log_prob,
        )
        assert not jnp.any(jnp.isnan(result)), "Forward algorithm produced NaN"
        assert not jnp.any(jnp.isinf(result)), "Forward algorithm produced Inf"


# ===========================================================================
# Forward-backward algorithm tests
# ===========================================================================

class TestForwardBackward:
    """Test forward-backward marginal posteriors against brute-force."""

    def test_posteriors_brute_force_2cat(self):
        """Compare forward-backward to brute-force marginals for 2 categories.

        Enumerates all 2^3 = 8 state sequences, computes exact marginal
        P(s_t = c | words) at each position, and checks agreement.
        """
        transition_prob = jnp.array([[0.7, 0.3], [0.4, 0.6]])
        emission_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.1, 0.4, 0.5],
        ])
        words = jnp.array([0, 2, 1])

        expected = _brute_force_marginals(words, transition_prob, emission_prob)
        result = forward_backward(words, transition_prob, emission_prob)

        assert result.shape == (3, 2), f"Expected shape (3, 2), got {result.shape}"
        np.testing.assert_allclose(
            np.array(result), expected, atol=1e-5,
            err_msg="Forward-backward posteriors do not match brute-force (2 categories)",
        )

    def test_posteriors_brute_force_3cat(self):
        """Compare forward-backward to brute-force marginals for 3 categories.

        Enumerates all 3^4 = 81 state sequences for a length-4 observation.
        """
        transition_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.2, 0.5, 0.3],
            [0.1, 0.3, 0.6],
        ])
        emission_prob = jnp.array([
            [0.4, 0.3, 0.1, 0.1, 0.1],
            [0.1, 0.1, 0.4, 0.3, 0.1],
            [0.1, 0.1, 0.1, 0.3, 0.4],
        ])
        words = jnp.array([0, 3, 2, 4])

        expected = _brute_force_marginals(words, transition_prob, emission_prob)
        result = forward_backward(words, transition_prob, emission_prob)

        assert result.shape == (4, 3), f"Expected shape (4, 3), got {result.shape}"
        np.testing.assert_allclose(
            np.array(result), expected, atol=1e-5,
            err_msg="Forward-backward posteriors do not match brute-force (3 categories)",
        )

    def test_posteriors_sum_to_one(self):
        """Each row of forward-backward output must sum to 1."""
        C, W = 3, 10
        k1, k2 = random.split(random.key(77))
        transition_prob = dist.Dirichlet(jnp.ones(C)).sample(
            key=k1, sample_shape=(C,),
        )
        emission_prob = dist.Dirichlet(jnp.ones(W) * 0.1).sample(
            key=k2, sample_shape=(C,),
        )
        words = jnp.array([0, 5, 3, 7, 2, 9, 1, 4, 8, 6])

        result = forward_backward(words, transition_prob, emission_prob)
        assert result.shape == (len(words), C), (
            f"Expected shape ({len(words)}, {C}), got {result.shape}"
        )
        np.testing.assert_allclose(
            np.array(jnp.sum(result, axis=1)), np.ones(len(words)), atol=1e-5,
            err_msg="Forward-backward posterior rows do not sum to 1",
        )
        assert not jnp.any(jnp.isnan(result)), "Forward-backward produced NaN"
        assert jnp.all(result >= 0), "Forward-backward produced negative probabilities"


# ===========================================================================
# Marginal decode tests
# ===========================================================================

class TestMarginalDecode:
    """Test marginal decoding against forward-backward posteriors."""

    def test_matches_argmax_posteriors(self):
        """marginal_decode must return argmax of forward_backward posteriors."""
        transition_prob = jnp.array([[0.7, 0.3], [0.4, 0.6]])
        emission_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.1, 0.4, 0.5],
        ])
        words = jnp.array([0, 2, 1])

        posteriors = forward_backward(words, transition_prob, emission_prob)
        expected = jnp.argmax(posteriors, axis=1)
        result = marginal_decode(words, transition_prob, emission_prob)

        assert jnp.issubdtype(result.dtype, jnp.integer), (
            f"marginal_decode dtype should be integer, got {result.dtype}"
        )
        assert jnp.array_equal(result, expected), (
            f"marginal_decode {list(np.array(result))} != "
            f"argmax of posteriors {list(np.array(expected))}"
        )

    def test_matches_brute_force_3cat(self):
        """Marginal decode on 3-category model should match brute-force argmax."""
        transition_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.2, 0.5, 0.3],
            [0.1, 0.3, 0.6],
        ])
        emission_prob = jnp.array([
            [0.4, 0.3, 0.1, 0.1, 0.1],
            [0.1, 0.1, 0.4, 0.3, 0.1],
            [0.1, 0.1, 0.1, 0.3, 0.4],
        ])
        words = jnp.array([0, 3, 2, 4])

        bf_marginals = _brute_force_marginals(words, transition_prob, emission_prob)
        expected = np.argmax(bf_marginals, axis=1)
        result = marginal_decode(words, transition_prob, emission_prob)

        assert list(np.array(result)) == list(expected), (
            f"marginal_decode {list(np.array(result))} != brute-force {list(expected)}"
        )


# ===========================================================================
# Viterbi decode tests
# ===========================================================================

class TestViterbiDecode:
    """Test Viterbi decoding against brute-force enumeration."""

    def test_viterbi_2_categories(self):
        """Test Viterbi on 2-category, 3-word model against all 8 sequences."""
        transition_prob = jnp.array([[0.7, 0.3], [0.4, 0.6]])
        emission_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.1, 0.4, 0.5],
        ])
        words = jnp.array([0, 2, 1])
        num_categories = 2
        T = len(words)

        best_log_prob = -float('inf')
        best_seq = None
        for seq in itertools.product(range(num_categories), repeat=T):
            log_p = np.log(1.0 / num_categories)
            log_p += float(jnp.log(emission_prob[seq[0], words[0]]))
            for t in range(1, T):
                log_p += float(jnp.log(transition_prob[seq[t - 1], seq[t]]))
                log_p += float(jnp.log(emission_prob[seq[t], words[t]]))
            if log_p > best_log_prob:
                best_log_prob = log_p
                best_seq = list(seq)

        result = viterbi_decode(words, transition_prob, emission_prob)
        assert result.shape == (T,), f"Expected shape ({T},), got {result.shape}"
        assert list(np.array(result)) == best_seq, (
            f"Viterbi decoded {list(np.array(result))}, "
            f"expected {best_seq} (log prob {best_log_prob:.6f})"
        )

    def test_viterbi_3_categories(self):
        """Test Viterbi on 3-category, 4-step model against all 81 sequences."""
        transition_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.2, 0.5, 0.3],
            [0.1, 0.3, 0.6],
        ])
        emission_prob = jnp.array([
            [0.4, 0.3, 0.1, 0.1, 0.1],
            [0.1, 0.1, 0.4, 0.3, 0.1],
            [0.1, 0.1, 0.1, 0.3, 0.4],
        ])
        words = jnp.array([0, 3, 2, 4])
        num_categories = 3
        T = len(words)

        best_log_prob = -float('inf')
        best_seq = None
        for seq in itertools.product(range(num_categories), repeat=T):
            log_p = np.log(1.0 / num_categories)
            log_p += float(jnp.log(emission_prob[seq[0], words[0]]))
            for t in range(1, T):
                log_p += float(jnp.log(transition_prob[seq[t - 1], seq[t]]))
                log_p += float(jnp.log(emission_prob[seq[t], words[t]]))
            if log_p > best_log_prob:
                best_log_prob = log_p
                best_seq = list(seq)

        result = viterbi_decode(words, transition_prob, emission_prob)
        assert result.shape == (T,), f"Expected shape ({T},), got {result.shape}"
        assert list(np.array(result)) == best_seq, (
            f"Viterbi decoded {list(np.array(result))}, "
            f"expected {best_seq} (log prob {best_log_prob:.6f})"
        )

    def test_viterbi_single_word(self):
        """Viterbi with a single word should return the state with highest
        uniform_prior * emission probability."""
        transition_prob = jnp.array([[0.7, 0.3], [0.4, 0.6]])
        emission_prob = jnp.array([
            [0.2, 0.8],
            [0.9, 0.1],
        ])
        words = jnp.array([0])
        result = viterbi_decode(words, transition_prob, emission_prob)
        assert result.shape == (1,)
        assert int(result[0]) == 1, (
            f"Single-word Viterbi: expected state 1 (emission 0.9), got {int(result[0])}"
        )

    def test_viterbi_output_dtype(self):
        """Viterbi output must be integer-typed."""
        transition_prob = jnp.array([[0.7, 0.3], [0.4, 0.6]])
        emission_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.1, 0.4, 0.5],
        ])
        words = jnp.array([0, 1, 2])
        result = viterbi_decode(words, transition_prob, emission_prob)
        assert jnp.issubdtype(result.dtype, jnp.integer), (
            f"Viterbi output dtype should be integer, got {result.dtype}"
        )

    def test_viterbi_longer_sequence(self):
        """Test Viterbi on a longer 2-category sequence (length 6, 64 paths)."""
        transition_prob = jnp.array([[0.8, 0.2], [0.3, 0.7]])
        emission_prob = jnp.array([
            [0.6, 0.3, 0.1],
            [0.1, 0.2, 0.7],
        ])
        words = jnp.array([0, 2, 2, 0, 1, 2])
        num_categories = 2
        T = len(words)

        best_log_prob = -float('inf')
        best_seq = None
        for seq in itertools.product(range(num_categories), repeat=T):
            log_p = np.log(1.0 / num_categories)
            log_p += float(jnp.log(emission_prob[seq[0], words[0]]))
            for t in range(1, T):
                log_p += float(jnp.log(transition_prob[seq[t - 1], seq[t]]))
                log_p += float(jnp.log(emission_prob[seq[t], words[t]]))
            if log_p > best_log_prob:
                best_log_prob = log_p
                best_seq = list(seq)

        result = viterbi_decode(words, transition_prob, emission_prob)
        assert list(np.array(result)) == best_seq, (
            f"Viterbi on length-6 sequence: got {list(np.array(result))}, "
            f"expected {best_seq}"
        )


# ===========================================================================
# Decoder evaluation tests
# ===========================================================================

class TestEvaluateDecoders:
    """Test the decoder comparison function for correctness and theoretical properties."""

    @pytest.fixture(scope="class")
    def eval_result(self):
        """Run evaluate_decoders once with controlled parameters and cache."""
        transition_prob = jnp.array([
            [0.5, 0.3, 0.2],
            [0.2, 0.5, 0.3],
            [0.3, 0.2, 0.5],
        ])
        emission_prob = jnp.array([
            [0.35, 0.25, 0.15, 0.15, 0.10],
            [0.10, 0.35, 0.25, 0.15, 0.15],
            [0.15, 0.10, 0.15, 0.25, 0.35],
        ])
        return evaluate_decoders(
            random.key(42), transition_prob, emission_prob,
            num_sequences=100, sequence_length=25,
        )

    def test_return_keys(self, eval_result):
        """evaluate_decoders must return dict with all required keys."""
        required = {
            "viterbi_position_accuracy", "marginal_position_accuracy",
            "viterbi_sequence_accuracy", "marginal_sequence_accuracy",
            "per_position_winner",
        }
        assert required.issubset(set(eval_result.keys())), (
            f"Missing keys: {required - set(eval_result.keys())}"
        )

    def test_accuracies_valid_range(self, eval_result):
        """All accuracy values must be floats in [0, 1]."""
        for key in ["viterbi_position_accuracy", "marginal_position_accuracy",
                     "viterbi_sequence_accuracy", "marginal_sequence_accuracy"]:
            val = eval_result[key]
            assert isinstance(val, float), f"{key} must be float, got {type(val)}"
            assert 0.0 <= val <= 1.0, f"{key} = {val} not in [0, 1]"

    def test_accuracies_above_chance(self, eval_result):
        """With structured emissions and 3 categories, both decoders must
        substantially beat random chance (1/3)."""
        assert eval_result["viterbi_position_accuracy"] > 0.40, (
            f"Viterbi accuracy {eval_result['viterbi_position_accuracy']:.3f} "
            f"should be well above chance (0.333)"
        )
        assert eval_result["marginal_position_accuracy"] > 0.40, (
            f"Marginal accuracy {eval_result['marginal_position_accuracy']:.3f} "
            f"should be well above chance (0.333)"
        )

    def test_winner_consistent(self, eval_result):
        """per_position_winner must accurately reflect the accuracy comparison."""
        vpa = eval_result["viterbi_position_accuracy"]
        mpa = eval_result["marginal_position_accuracy"]
        winner = eval_result["per_position_winner"]
        assert winner in ("viterbi", "marginal", "tie"), (
            f"Invalid winner value: '{winner}'"
        )
        if mpa > vpa:
            assert winner == "marginal", (
                f"marginal ({mpa:.4f}) > viterbi ({vpa:.4f}) but winner = '{winner}'"
            )
        elif vpa > mpa:
            assert winner == "viterbi", (
                f"viterbi ({vpa:.4f}) > marginal ({mpa:.4f}) but winner = '{winner}'"
            )
        else:
            assert winner == "tie"

    def test_marginal_geq_viterbi_position(self, eval_result):
        """Marginal MAP decoding is Bayes-optimal for per-position 0-1 loss.

        Marginal decoding independently maximizes P(correct) at each position,
        while Viterbi maximizes the joint sequence probability. With sufficient
        evaluation data, marginal per-position accuracy should be >= Viterbi,
        reflecting this fundamental theoretical distinction."""
        mpa = eval_result["marginal_position_accuracy"]
        vpa = eval_result["viterbi_position_accuracy"]
        assert mpa >= vpa - 0.02, (
            f"Marginal accuracy ({mpa:.4f}) should be >= Viterbi ({vpa:.4f}) "
            f"for per-position decoding — marginal MAP is Bayes-optimal "
            f"for per-position 0-1 loss"
        )


# ===========================================================================
# Full model inference tests
# ===========================================================================

class TestModelInference:
    """Test full model inference: convergence and parameter recovery."""

    @pytest.fixture(scope="class")
    def inference_results(self):
        """Run MCMC inference once and cache for all tests in this class."""
        data = simulate_data(random.key(42))
        mcmc = run_inference(
            random.key(0), data, num_warmup=500, num_samples=300,
        )
        samples = mcmc.get_samples()
        extra_fields = mcmc.get_extra_fields()
        return {
            'mcmc': mcmc,
            'samples': samples,
            'extra_fields': extra_fields,
            'data': data,
        }

    def test_no_divergences(self, inference_results):
        """MCMC must produce a very low divergence rate (< 3%)."""
        diverging = inference_results['extra_fields']['diverging']
        num_divergences = int(jnp.sum(diverging))
        total_samples = len(diverging)
        divergence_rate = num_divergences / total_samples
        assert divergence_rate < 0.03, (
            f"Got {num_divergences} divergent transitions out of "
            f"{total_samples} total ({divergence_rate:.1%} divergence rate)"
        )

    def test_samples_finite(self, inference_results):
        """All MCMC samples must be finite (no NaN or Inf)."""
        for name, values in inference_results['samples'].items():
            assert not jnp.any(jnp.isnan(values)), (
                f"Parameter '{name}' contains NaN"
            )
            assert not jnp.any(jnp.isinf(values)), (
                f"Parameter '{name}' contains Inf"
            )

    def test_transition_prob_recovery(self, inference_results):
        """Posterior mean of transition probs must be close to ground truth."""
        samples = inference_results['samples']
        data = inference_results['data']

        posterior_mean = jnp.mean(samples['transition_prob'], axis=0)
        true_values = data['transition_prob']

        max_error = float(jnp.max(jnp.abs(posterior_mean - true_values)))
        assert max_error < 0.20, (
            f"Transition probability recovery failed: max error = {max_error:.4f}\n"
            f"True:\n{np.array(true_values)}\n"
            f"Posterior mean:\n{np.array(posterior_mean)}"
        )

    def test_emission_prob_recovery(self, inference_results):
        """Posterior mean of emission probs must be close to ground truth."""
        samples = inference_results['samples']
        data = inference_results['data']

        posterior_mean = jnp.mean(samples['emission_prob'], axis=0)
        true_values = data['emission_prob']

        max_error = float(jnp.max(jnp.abs(posterior_mean - true_values)))
        assert max_error < 0.20, (
            f"Emission probability recovery failed: max error = {max_error:.4f}"
        )

    def test_viterbi_with_posterior(self, inference_results):
        """Viterbi decoding with posterior means should produce reasonable accuracy."""
        samples = inference_results['samples']
        data = inference_results['data']

        transition_mean = jnp.mean(samples['transition_prob'], axis=0)
        emission_mean = jnp.mean(samples['emission_prob'], axis=0)

        decoded = viterbi_decode(
            data['supervised_words'], transition_mean, emission_mean,
        )

        assert decoded.shape == data['supervised_categories'].shape, (
            f"Decoded shape {decoded.shape} != expected {data['supervised_categories'].shape}"
        )

        accuracy = float(jnp.mean(decoded == data['supervised_categories']))
        assert accuracy > 0.4, (
            f"Viterbi accuracy on supervised data is {accuracy:.2%}, "
            f"expected > 40% for a well-fit model with 3 categories"
        )
