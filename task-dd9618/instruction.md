A probabilistic simulator is defined in `/app/model.py`. It maps 2D parameters theta ~ Uniform([-1,1]^2) to 2D observations x through a nonlinear stochastic process. The likelihood p(x|theta) is intractable -- only forward simulations are possible.

Pre-generated observations are at `/app/data/observation_{1,2,3}.csv` and ground-truth reference posterior samples at `/app/data/reference_posterior_{1,2,3}.csv` (10000 samples each, CSV with header row, columns theta1/theta2).

Build an inference and evaluation system that produces the following deliverables:

- `/app/metrics.py` exporting two functions:
  - `c2st(X, Y, seed=1)` -- Classifier Two-Sample Test. Takes two numpy arrays and a seed integer. Returns a float in [0, 1] where 0.5 means indistinguishable distributions and 1.0 means perfectly separable.
  - `mmd(X, Y)` -- Maximum Mean Discrepancy (unbiased estimate). Takes two numpy arrays. Returns a float where 0 means identical distributions.

- `/app/results/posterior_{1,2,3}.npy` -- numpy arrays of shape (N, 2) with N >= 5000, all values in [-1, 1]

- `/app/results/metrics.json` -- format: `{"obs_1": {"c2st": <float>}, "obs_2": {"c2st": <float>}, "obs_3": {"c2st": <float>}}`

The C2ST score of each of your posterior sample sets against the corresponding reference posterior must be below 0.65.