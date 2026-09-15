`/app/model.py` implements a semi-supervised Hidden Markov Model in NumPyro. The model learns transition and emission probabilities from labeled `(word, category)` pairs and unlabeled word sequences, marginalizing over latent categories via the forward algorithm. The implementation contains multiple interacting bugs that cause MCMC inference to fail.

## Part 1: Fix the model

Diagnose and fix all bugs in `/app/model.py` so that:

- MCMC inference converges with a divergence rate below 3%
- All posterior samples are finite (no NaN or Inf)
- Posterior means for transition and emission matrices are within 0.20 max elementwise error of ground truth

Functions `forward_one_step`, `forward_log_prob`, `simulate_data`, `semi_supervised_hmm`, and `run_inference` must remain importable with existing signatures.

## Part 2: Implement and evaluate competing decoding strategies

Add these functions to `/app/model.py`:

`viterbi_decode(words, transition_prob, emission_prob)` — Joint MAP decoder: find the single most probable complete hidden state sequence. Uniform initial distribution (`1/num_categories`). Returns integer array of shape `(T,)`.

`forward_backward(words, transition_prob, emission_prob)` — Compute the marginal posterior `P(state_t = c | all observations)` at every time step using the forward-backward algorithm. Uniform initial distribution. Returns array of shape `(T, C)` where each row is a normalized probability distribution summing to 1.

`marginal_decode(words, transition_prob, emission_prob)` — Marginal MAP decoder: at each position independently, return the state with highest marginal posterior from the forward-backward posteriors. Returns integer array of shape `(T,)`.

`evaluate_decoders(rng_key, transition_prob, emission_prob, num_sequences, sequence_length)` — Design and execute a controlled comparison of Viterbi vs marginal decoding. Generate `num_sequences` HMM sequences of the given length using the provided parameters (uniform start distribution), decode each with both strategies using the true parameters, and return a dict with:

- `"viterbi_position_accuracy"`: float — fraction of all decoded positions matching ground truth (Viterbi)
- `"marginal_position_accuracy"`: float — fraction of all decoded positions matching ground truth (marginal)
- `"viterbi_sequence_accuracy"`: float — fraction of entirely-correct full sequences (Viterbi)
- `"marginal_sequence_accuracy"`: float — fraction of entirely-correct full sequences (marginal)
- `"per_position_winner"`: `"viterbi"`, `"marginal"`, or `"tie"` — which achieves higher per-position accuracy

The evaluation must correctly reflect the relationship between joint MAP and marginal MAP optimality for different loss functions.