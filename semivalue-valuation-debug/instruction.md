The `/app/` directory contains a data valuation framework for scoring individual training data points and identifying mislabeled examples. A test dataset is generated at runtime at `/app/data/dataset.npz` (numpy arrays: `x_train`, `y_train`, `x_valid`, `y_valid`; approximately 20% of training labels are corrupted).

Running `python3 /app/pipeline.py` must complete without errors and write `/app/results.json` with this schema:

```json
{
  "shapley": {"data_values": [<floats>], "detected_indices": [<sorted ints>]},
  "beta_shapley": {"data_values": [<floats>], "detected_indices": [<sorted ints>]},
  "banzhaf": {"data_values": [<floats>], "detected_indices": [<sorted ints>]},
  "loo": {"data_values": [<floats>], "detected_indices": [<sorted ints>]},
  "data_oob": {"data_values": [<floats>], "detected_indices": [<sorted ints>]},
  "ensemble": {"detected_indices": [<sorted ints>], "method": "borda_count"},
  "convergence": {"gr_statistic": <float>, "epochs_run": <int>},
  "stability": {"split_half_correlation": <float>},
  "removal_validation": {"original_accuracy": <float>, "cleaned_accuracy": <float>}
}
```

**Correctness requirements:**

- Each `data_values` array has 100 elements, all finite, not uniformly zero.
- Semivalue weights for Shapley, Beta Shapley, and Banzhaf evaluators must be mathematically correct and sum to 1.0.
- The `loo` evaluator must compute leave-one-out values: each point's value equals the change in utility when that point is excluded from the full training set.
- The `data_oob` evaluator must produce values in [0, 1] that distinguish mislabeled from clean points through per-datum out-of-bag prediction accuracy on training features.
- The convergence `gr_statistic` must satisfy the Gelman-Rubin potential scale reduction factor's theoretical lower bound (>= 0.94).
- `stability.split_half_correlation` reports the Spearman rank correlation between mean per-point marginal increments computed from the first and second halves of sampled permutation epochs. Must exceed 0.3.
- The ensemble detector must aggregate all five evaluator rankings via Borda count. At least one individual evaluator must achieve F1 >= 0.25 on noisy label detection. The ensemble must achieve F1 >= 0.20.
- Removing ensemble-detected noisy points from training must yield higher classification accuracy on the validation set than training on the full corrupted set.
- The pipeline must complete within 5 minutes.

**Framework layout:**

- `/app/pipeline.py` — orchestration and results output
- `/app/valuation/sampler.py` — permutation sampler with truncation and convergence diagnostics
- `/app/valuation/evaluators.py` — semivalue-weighted evaluators (Shapley, Beta Shapley, Banzhaf)
- `/app/valuation/loo.py` — leave-one-out evaluator (stub)
- `/app/valuation/oob.py` — out-of-bag evaluator
- `/app/valuation/detector.py` — noisy label detection and rank aggregation

Preserve all module paths and public class/method names.
