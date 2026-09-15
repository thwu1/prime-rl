A colleague's Bayesian HMM project at `/app/` is producing unreliable inference results. The MCMC sampler shows severe convergence failures. Examine the project — diagnostic logs, model source code, data, and configuration — to identify and fix the root cause.

Once the model converges reliably, complete the analysis pipeline: fit models for each candidate model order using all available training data, perform Bayesian model selection on the held-out evaluation set, and decode hidden state sequences.

## Output

Write `/app/results.json` with exactly these fields:

```json
{
  "selected_K": "<int>",
  "test_loglik_K2": "<float>",
  "test_loglik_K3": "<float>",
  "emission_means": ["<K ordered floats>"],
  "emission_stds": ["<K positive floats>"],
  "transition_matrix": [["<K x K, rows sum to 1>"]],
  "decoded_states_seq0": ["<T_test ints in 0..K-1>"],
  "decoded_states_seq1": ["<T_test ints in 0..K-1>"],
  "num_divergences": "<int>",
  "max_rhat": "<float>"
}
```

- `selected_K`: model order achieving higher total held-out marginal log-likelihood (sum over all evaluation sequences, computed via the forward algorithm with posterior mean parameters)
- `test_loglik_K2`, `test_loglik_K3`: total held-out log-likelihood for each candidate model order
- `emission_means`, `emission_stds`, `transition_matrix`: posterior mean parameters of the selected model
- `decoded_states_seq0`, `decoded_states_seq1`: Viterbi (MAP) hidden state sequences for each evaluation observation
- `num_divergences`: number of divergent MCMC transitions for the selected model
- `max_rhat`: maximum R-hat diagnostic across all parameters for the selected model