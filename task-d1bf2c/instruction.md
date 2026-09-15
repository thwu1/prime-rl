Noisy observations from an unknown 2D dynamical system are in `/app/data/observations.csv` (columns: `t`, `y1`, `y2`). Four candidate ODE models with different structural forms and free parameters are defined in `/app/models/` (`model_a.py` through `model_d.py`). Each model exposes a standard interface: `vector_field(t, y, params)`, `PARAM_NAMES`, `DEFAULT_PARAMS`, and `PARAM_BOUNDS`. System metadata (initial conditions, observation noise level, forecast time points) is in `/app/data/config.json`.

Determine which candidate model generated the observations. Fit each model's parameters to the observed data, then rank the models accounting for the trade-off between data fidelity and structural complexity. For the top-ranked model, produce forward trajectory predictions with uncertainty estimates at the time points specified in the config.

Write results to `/app/results/`:
- `ranking.json`: `{"rankings": [{"model": "<name>", "score": <float>}, ...]}` best model first
- `selected_model.json`: `{"name": "<model_name>", "fitted_parameters": {"<param>": <value>, ...}}`
- `prediction.json`: `{"times": [<float>, ...], "y1_mean": [<float>, ...], "y2_mean": [<float>, ...], "y1_std": [<float>, ...], "y2_std": [<float>, ...]}`
- `diagnostics.json`: `{"training_rmse_y1": <float>, "training_rmse_y2": <float>, "normalized_residual_variance_y1": <float>, "normalized_residual_variance_y2": <float>}`