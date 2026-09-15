The directory `/app/lvq/` contains Python implementations of LVQ classifiers — GLVQ, GMLVQ, and RSLVQ — as scikit-learn compatible estimators. The GMLVQ and RSLVQ modules contain mathematical bugs. The base class (`/app/lvq/base.py`) and GLVQ (`/app/lvq/glvq.py`) are correct reference implementations.

**Part 1 — Fix all bugs** so that:

1. `GmlvqModel(prototypes_per_class=2, random_state=42)` achieves >90% accuracy on Iris (shuffled with `check_random_state(42)`).
2. After GMLVQ training, `np.trace(omega_.T @ omega_)` equals `1.0 +/- 1e-6`.
3. On a 2D dataset (feature 0: intra-class variance 0.3, feature 1: variance 4.0, class means [0,0] and [4,4], 50 samples/class, `RandomState(123)`), GMLVQ's `omega_` assigns >50% relevance to feature 0.
4. With `regularization > 0`, the smallest normalized eigenvalue of `omega_.T @ omega_` exceeds `0.01`.
5. `RslvqModel(prototypes_per_class=2, random_state=42)` achieves >85% accuracy on Iris with `n_iter_ > 1`.
6. `RslvqModel.posterior(y, x)` returns probabilities in `[0, 1]` summing to `1.0 +/- 1e-6`, with the correct class dominant for well-separated samples.

**Part 2 — Implement GRLVQ** in `/app/lvq/grlvq.py`:

Create `GrlvqModel` extending `GlvqModel` with per-feature diagonal relevance weighting. The model must work within the existing LVQ class hierarchy and its optimization/gradient machinery.

Constructor: `prototypes_per_class`, `initial_prototypes`, `initial_relevances`, `regularization` (default `0.0`), `max_iter`, `gtol`, `beta`, `c`, `display`, `random_state`.

After `fit()`, attribute `lambda_` must be a 1D array of shape `[n_features]`, all values >= 0, summing to 1.0. Distance metric for classification: `d(x, w) = sum_j lambda_j * (x_j - w_j)^2`. Override `_compute_distance(x)` returning shape `[n_samples, n_prototypes]`.

Behavioral requirements:
- Achieves >90% accuracy on Iris with `prototypes_per_class=2, random_state=42`.
- On the same 2D synthetic dataset as Part 1, `lambda_[0] > lambda_[1]`.
- With `regularization > 0`, `lambda_.min() > 0.005`.
- Full scikit-learn compatibility: `fit(X, y)`, `predict(X)`, `score(X, y)`.

Verify with `/tests/test.sh`.
