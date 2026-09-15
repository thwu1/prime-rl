"""
Fix the buggy semi-supervised HMM model, add Viterbi and marginal decoding,
and implement a decoder evaluation comparison.

This script reads the buggy model, applies targeted fixes derived from
mathematical analysis, adds the decoding and evaluation functions, and
verifies correctness against brute-force enumeration.
"""



def apply_fixes():
    with open('/app/model.py', 'r') as f:
        code = f.read()

    # Fix 1: Wrong logsumexp axis in forward_one_step
    # axis=0 marginalizes over previous state (i) -> result indexed by current state j
    code = code.replace(
        'return logsumexp(log_prob, axis=1)',
        'return logsumexp(log_prob, axis=0)',
    )

    # Fix 2: Reversed supervised category conditioning
    # Should model P(cat[t+1] | cat[t]), not P(cat[t] | cat[t+1])
    code = code.replace(
        'dist.Categorical(transition_prob[supervised_categories[1:]])',
        'dist.Categorical(transition_prob[supervised_categories[:-1]])',
    )
    code = code.replace(
        'obs=supervised_categories[:-1],',
        'obs=supervised_categories[1:],',
    )

    # Fix 3: Wrong sign in numpyro.factor
    # Forward log-probability should be a positive density contribution
    code = code.replace(
        'numpyro.factor("forward_log_prob", -log_prob)',
        'numpyro.factor("forward_log_prob", log_prob)',
    )

    # Fix 4: Bad MCMC target_accept_prob
    # Dirichlet-constrained posteriors need higher acceptance probability
    code = code.replace(
        'NUTS(semi_supervised_hmm, target_accept_prob=0.55)',
        'NUTS(semi_supervised_hmm, target_accept_prob=0.99)',
    )

    # Optimization: convert for-loop to lax.scan for efficient JIT
    old_forward = (
        '    log_prob = init_log_prob\n'
        '    for word in words:\n'
        '        log_prob = forward_one_step(log_prob, word, transition_log_prob, emission_log_prob)\n'
        '    return log_prob'
    )
    new_forward = (
        '    def scan_fn(log_prob, word):\n'
        '        return forward_one_step(log_prob, word, transition_log_prob, emission_log_prob), None\n'
        '    log_prob, _ = lax.scan(scan_fn, init_log_prob, words)\n'
        '    return log_prob'
    )
    code = code.replace(old_forward, new_forward)

    # Add Viterbi decode, forward-backward, marginal decode, and evaluate_decoders
    new_functions = '''

def viterbi_decode(words, transition_prob, emission_prob):
    """Find the single most probable hidden state sequence (joint MAP).

    Uses dynamic programming in log space with backpointer tracking.
    Assumes uniform initial state distribution (1/num_categories).

    Args:
        words: jnp.array of shape (T,) - observed word indices
        transition_prob: jnp.array of shape (C, C) - transition_prob[i, j] = P(next=j | current=i)
        emission_prob: jnp.array of shape (C, W) - emission_prob[c, w] = P(word=w | state=c)

    Returns:
        jnp.array of shape (T,) - most probable state sequence (integer dtype)
    """
    num_categories = transition_prob.shape[0]
    T = words.shape[0]

    transition_log = jnp.log(transition_prob)
    emission_log = jnp.log(emission_prob)

    # Initialize: uniform prior over states, times emission for first word
    log_delta = (jnp.log(jnp.ones(num_categories) / num_categories)
                 + emission_log[:, words[0]])

    # Forward pass: track max log-probability and backpointers at each step
    psi_list = []
    for t in range(1, T):
        # scores[i, j] = log_delta[i] + log_transition[i, j]
        scores = log_delta[:, None] + transition_log
        # For each current state j, find best previous state i
        log_delta = jnp.max(scores, axis=0) + emission_log[:, words[t]]
        psi_list.append(jnp.argmax(scores, axis=0))

    # Backtrack from best final state
    states = [int(jnp.argmax(log_delta))]
    for t in range(T - 2, -1, -1):
        states.append(int(psi_list[t][states[-1]]))
    states.reverse()

    return jnp.array(states)


def forward_backward(words, transition_prob, emission_prob):
    """Compute marginal posterior P(state_t = c | all observations) via forward-backward.

    Uses the forward algorithm to compute alpha_t(c) and the backward algorithm
    to compute beta_t(c), then combines them to get normalized marginal posteriors.
    Assumes uniform initial state distribution (1/num_categories).

    Args:
        words: jnp.array of shape (T,) - observed word indices
        transition_prob: jnp.array of shape (C, C) - transition_prob[i, j] = P(next=j | current=i)
        emission_prob: jnp.array of shape (C, W) - emission_prob[c, w] = P(word=w | state=c)

    Returns:
        jnp.array of shape (T, C) - marginal posterior probabilities, each row sums to 1
    """
    num_categories = transition_prob.shape[0]
    T = words.shape[0]

    transition_log = jnp.log(transition_prob)
    emission_log = jnp.log(emission_prob)

    # Forward pass: compute log alpha_t(c) for each time step
    log_alpha_0 = (jnp.log(jnp.ones(num_categories) / num_categories)
                   + emission_log[:, words[0]])
    log_alphas = [log_alpha_0]
    for t in range(1, T):
        # alpha_t(j) = emission[j, w_t] * sum_i alpha_{t-1}(i) * transition[i, j]
        log_alpha_tmp = log_alphas[-1][:, None] + transition_log
        log_alpha_t = logsumexp(log_alpha_tmp, axis=0) + emission_log[:, words[t]]
        log_alphas.append(log_alpha_t)

    # Backward pass: compute log beta_t(c) for each time step
    log_betas = [None] * T
    log_betas[T - 1] = jnp.zeros(num_categories)  # beta_T = 1 -> log(1) = 0
    for t in range(T - 2, -1, -1):
        # beta_t(i) = sum_j transition[i,j] * emission[j, w_{t+1}] * beta_{t+1}(j)
        inner = transition_log + emission_log[:, words[t + 1]] + log_betas[t + 1]
        log_betas[t] = logsumexp(inner, axis=1)

    # Marginal posteriors: gamma_t(c) = alpha_t(c) * beta_t(c) / P(observations)
    log_gammas = []
    for t in range(T):
        lg = log_alphas[t] + log_betas[t]
        lg = lg - logsumexp(lg)  # normalize
        log_gammas.append(lg)

    return jnp.exp(jnp.stack(log_gammas))


def marginal_decode(words, transition_prob, emission_prob):
    """Find the marginally most probable state at each position (marginal MAP).

    At each time step independently, returns the state with highest marginal
    posterior probability P(state_t = c | all observations). This is Bayes-optimal
    for per-position 0-1 loss.

    Args:
        words: jnp.array of shape (T,) - observed word indices
        transition_prob: jnp.array of shape (C, C) - transition_prob[i, j] = P(next=j | current=i)
        emission_prob: jnp.array of shape (C, W) - emission_prob[c, w] = P(word=w | state=c)

    Returns:
        jnp.array of shape (T,) - marginally most probable states (integer dtype)
    """
    posteriors = forward_backward(words, transition_prob, emission_prob)
    return jnp.argmax(posteriors, axis=1)


def evaluate_decoders(rng_key, transition_prob, emission_prob,
                      num_sequences=50, sequence_length=20):
    """Compare Viterbi vs marginal decoding on synthetic HMM sequences.

    Generates sequences from the HMM defined by the given parameters,
    decodes each with both Viterbi (joint MAP) and marginal MAP methods
    using the true parameters, and computes accuracy metrics.

    Args:
        rng_key: JAX random key for reproducibility
        transition_prob: jnp.array of shape (C, C)
        emission_prob: jnp.array of shape (C, W)
        num_sequences: number of test sequences to generate
        sequence_length: length of each test sequence

    Returns:
        dict with keys:
            viterbi_position_accuracy: float
            marginal_position_accuracy: float
            viterbi_sequence_accuracy: float
            marginal_sequence_accuracy: float
            per_position_winner: "viterbi", "marginal", or "tie"
    """
    num_categories = transition_prob.shape[0]
    start_prob = jnp.ones(num_categories) / num_categories

    total_positions = 0
    viterbi_correct = 0
    marginal_correct = 0
    viterbi_seq_correct = 0
    marginal_seq_correct = 0

    for i in range(num_sequences):
        rng_key, seq_key = random.split(rng_key)

        # Generate one HMM sequence
        true_states = []
        words_list = []
        for t in range(sequence_length):
            seq_key, state_key, word_key = random.split(seq_key, 3)
            if t == 0:
                state = dist.Categorical(probs=start_prob).sample(key=state_key)
            else:
                state = dist.Categorical(probs=transition_prob[state]).sample(key=state_key)
            word = dist.Categorical(probs=emission_prob[state]).sample(key=word_key)
            true_states.append(state)
            words_list.append(word)

        true_states = jnp.stack(true_states)
        words_arr = jnp.stack(words_list)

        # Decode with both methods
        vit = viterbi_decode(words_arr, transition_prob, emission_prob)
        marg = marginal_decode(words_arr, transition_prob, emission_prob)

        # Accumulate accuracy metrics
        total_positions += sequence_length
        viterbi_correct += int(jnp.sum(vit == true_states))
        marginal_correct += int(jnp.sum(marg == true_states))
        viterbi_seq_correct += int(jnp.all(vit == true_states))
        marginal_seq_correct += int(jnp.all(marg == true_states))

    vpa = viterbi_correct / total_positions
    mpa = marginal_correct / total_positions
    vsa = viterbi_seq_correct / num_sequences
    msa = marginal_seq_correct / num_sequences

    if mpa > vpa:
        winner = "marginal"
    elif vpa > mpa:
        winner = "viterbi"
    else:
        winner = "tie"

    return {
        "viterbi_position_accuracy": float(vpa),
        "marginal_position_accuracy": float(mpa),
        "viterbi_sequence_accuracy": float(vsa),
        "marginal_sequence_accuracy": float(msa),
        "per_position_winner": winner,
    }
'''
    code += new_functions

    with open('/app/model.py', 'w') as f:
        f.write(code)

    print("Applied 4 bug fixes + decoding/evaluation functions to /app/model.py")


def verify_fixes():
    """Verify the forward algorithm, Viterbi, and forward-backward are correct."""
    import sys
    sys.path.insert(0, '/app')

    import importlib
    import model
    importlib.reload(model)

    import jax.numpy as jnp
    from jax.scipy.special import logsumexp
    import numpy as np
    import itertools

    # Verify forward algorithm on small example
    transition_prob = jnp.array([[0.7, 0.3], [0.4, 0.6]])
    emission_prob = jnp.array([[0.5, 0.3, 0.2], [0.1, 0.4, 0.5]])
    words = jnp.array([0, 2, 1])

    per_state = np.zeros(2)
    for s0 in range(2):
        for s1 in range(2):
            for s2 in range(2):
                p = (0.5
                     * float(emission_prob[s0, words[0]])
                     * float(transition_prob[s0, s1])
                     * float(emission_prob[s1, words[1]])
                     * float(transition_prob[s1, s2])
                     * float(emission_prob[s2, words[2]]))
                per_state[s2] += p
    brute_force_total = np.log(np.sum(per_state))

    transition_log_prob = jnp.log(transition_prob)
    emission_log_prob = jnp.log(emission_prob)
    init_log_prob = jnp.log(jnp.array([0.5, 0.5])) + emission_log_prob[:, words[0]]
    result = model.forward_log_prob(
        init_log_prob, words[1:], transition_log_prob, emission_log_prob,
    )
    forward_total = float(logsumexp(result))
    np.testing.assert_allclose(forward_total, brute_force_total, atol=1e-5)
    print(f"Forward algorithm OK: {forward_total:.6f} == {brute_force_total:.6f}")

    # Verify Viterbi on same example
    best_log_prob = -float('inf')
    best_seq = None
    for seq in itertools.product(range(2), repeat=3):
        log_p = np.log(0.5)
        log_p += float(jnp.log(emission_prob[seq[0], words[0]]))
        for t in range(1, 3):
            log_p += float(jnp.log(transition_prob[seq[t - 1], seq[t]]))
            log_p += float(jnp.log(emission_prob[seq[t], words[t]]))
        if log_p > best_log_prob:
            best_log_prob = log_p
            best_seq = list(seq)

    viterbi_result = model.viterbi_decode(words, transition_prob, emission_prob)
    assert list(np.array(viterbi_result)) == best_seq, (
        f"Viterbi: got {list(np.array(viterbi_result))}, expected {best_seq}"
    )
    print(f"Viterbi OK: {list(np.array(viterbi_result))} == {best_seq}")

    # Verify forward-backward marginal posteriors
    C, T = 2, 3
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

    fb_result = model.forward_backward(words, transition_prob, emission_prob)
    np.testing.assert_allclose(np.array(fb_result), marginals, atol=1e-5)
    print(f"Forward-backward OK: posteriors match brute force")

    # Verify marginal decode
    marg_result = model.marginal_decode(words, transition_prob, emission_prob)
    expected_marg = np.argmax(marginals, axis=1)
    assert list(np.array(marg_result)) == list(expected_marg), (
        f"Marginal decode: got {list(np.array(marg_result))}, expected {list(expected_marg)}"
    )
    print(f"Marginal decode OK: {list(np.array(marg_result))} == {list(expected_marg)}")

    print("\nAll verifications passed!")


if __name__ == '__main__':
    apply_fixes()
    verify_fixes()
