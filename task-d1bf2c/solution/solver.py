#!/usr/bin/env python3
"""Solution: Dynamical system model selection via parameter estimation and BIC."""


import csv
import importlib.util
import json
import os

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import minimize

# ---------------------------------------------------------------------------
# Load configuration and data
# ---------------------------------------------------------------------------

with open("/app/data/config.json") as f:
    config = json.load(f)

Y0 = config["initial_conditions"]
T_START = config["t_start"]
NOISE_STD = config["observation_noise_std"]
PRED_TIMES = config["prediction_times"]

t_obs, y1_obs, y2_obs = [], [], []
with open("/app/data/observations.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        t_obs.append(float(row["t"]))
        y1_obs.append(float(row["y1"]))
        y2_obs.append(float(row["y2"]))

t_obs = np.array(t_obs)
y1_obs = np.array(y1_obs)
y2_obs = np.array(y2_obs)
n_obs = len(t_obs)
n_total = 2 * n_obs  # y1 + y2 observations

# ---------------------------------------------------------------------------
# Load candidate models
# ---------------------------------------------------------------------------

MODEL_NAMES = ["model_a", "model_b", "model_c", "model_d"]
models = {}
for name in MODEL_NAMES:
    spec = importlib.util.spec_from_file_location(name, f"/app/models/{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    models[name] = mod


# ---------------------------------------------------------------------------
# Parameter estimation
# ---------------------------------------------------------------------------

def make_nll(model):
    """Create negative log-likelihood function for Gaussian observation noise."""
    def neg_log_likelihood(params):
        try:
            sol = solve_ivp(
                lambda t, y: model.vector_field(t, y, list(params)),
                [T_START, t_obs[-1] + 0.01],
                Y0,
                method="RK45",
                t_eval=t_obs,
                rtol=1e-8,
                atol=1e-10,
                max_step=1.0,
            )
            if sol.status != 0 or sol.y.shape[1] != n_obs:
                return 1e12
            if not np.all(np.isfinite(sol.y)):
                return 1e12
            r1 = (y1_obs - sol.y[0]) / NOISE_STD
            r2 = (y2_obs - sol.y[1]) / NOISE_STD
            return 0.5 * (np.sum(r1 ** 2) + np.sum(r2 ** 2))
        except Exception:
            return 1e12
    return neg_log_likelihood


def fit_model(model):
    """Fit model parameters via maximum likelihood with multi-start optimization."""
    nll_func = make_nll(model)
    bounds = model.PARAM_BOUNDS
    x0 = np.array(model.DEFAULT_PARAMS, dtype=float)

    best = None
    best_val = 1e12

    # Default starting point
    res = minimize(nll_func, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": 2000, "ftol": 1e-14})
    if res.fun < best_val:
        best_val = res.fun
        best = res

    # Perturbed starting points
    rng = np.random.default_rng(42)
    for _ in range(12):
        x0_p = np.array([
            np.clip(x0[i] * (1 + rng.normal(0, 0.5)),
                    bounds[i][0], bounds[i][1])
            for i in range(len(x0))
        ])
        res = minimize(nll_func, x0_p, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": 2000, "ftol": 1e-14})
        if res.fun < best_val:
            best_val = res.fun
            best = res

    # Polish with Nelder-Mead from best result
    if best is not None:
        res2 = minimize(nll_func, best.x, method="Nelder-Mead",
                        options={"maxiter": 5000, "xatol": 1e-10, "fatol": 1e-10})
        if res2.fun < best_val:
            best_val = res2.fun
            best = res2

    return best


# ---------------------------------------------------------------------------
# Fit all models and compute BIC
# ---------------------------------------------------------------------------

fit_results = {}
for name in MODEL_NAMES:
    print(f"Fitting {name}...")
    model = models[name]
    result = fit_model(model)
    k = len(model.PARAM_NAMES)
    nll = result.fun
    bic = k * np.log(n_total) + 2 * nll
    fit_results[name] = {
        "params": result.x.tolist(),
        "nll": float(nll),
        "bic": float(bic),
        "k": k,
        "param_names": model.PARAM_NAMES,
    }
    print(f"  k={k}, NLL={nll:.4f}, BIC={bic:.4f}")
    print(f"  params={dict(zip(model.PARAM_NAMES, result.x))}")

# Rank by BIC (lower is better)
ranked = sorted(fit_results.items(), key=lambda x: x[1]["bic"])
print("\nModel ranking (BIC, lower is better):")
for name, r in ranked:
    print(f"  {name}: BIC={r['bic']:.4f}")

# ---------------------------------------------------------------------------
# Write ranking.json
# ---------------------------------------------------------------------------

os.makedirs("/app/results", exist_ok=True)

ranking_json = {
    "rankings": [
        {"model": name, "score": float(-r["bic"])}
        for name, r in ranked
    ]
}
with open("/app/results/ranking.json", "w") as f:
    json.dump(ranking_json, f, indent=2)

# ---------------------------------------------------------------------------
# Write selected_model.json
# ---------------------------------------------------------------------------

best_name = ranked[0][0]
best_info = fit_results[best_name]
selected_json = {
    "name": best_name,
    "fitted_parameters": dict(
        zip(best_info["param_names"], [float(p) for p in best_info["params"]])
    ),
}
with open("/app/results/selected_model.json", "w") as f:
    json.dump(selected_json, f, indent=2)

# ---------------------------------------------------------------------------
# Write prediction.json with uncertainty
# ---------------------------------------------------------------------------

best_model = models[best_name]
best_params = np.array(best_info["params"])

# Mean prediction
sol_pred = solve_ivp(
    lambda t, y: best_model.vector_field(t, y, list(best_params)),
    [T_START, max(PRED_TIMES) + 0.01],
    Y0,
    method="DOP853",
    t_eval=PRED_TIMES,
    rtol=1e-10,
    atol=1e-12,
)

# Estimate parameter uncertainty via finite-difference Hessian of NLL
nll_func = make_nll(best_model)
n_params = len(best_params)
hessian = np.zeros((n_params, n_params))

for i in range(n_params):
    for j in range(i, n_params):
        ei = np.zeros(n_params)
        ej = np.zeros(n_params)
        ei[i] = 1e-4 * max(abs(best_params[i]), 1e-6)
        ej[j] = 1e-4 * max(abs(best_params[j]), 1e-6)

        fpp = nll_func(best_params + ei + ej)
        fpm = nll_func(best_params + ei - ej)
        fmp = nll_func(best_params - ei + ej)
        fmm = nll_func(best_params - ei - ej)

        h2 = 4.0 * ei[i] * ej[j]
        if h2 > 0:
            hessian[i, j] = (fpp - fpm - fmp + fmm) / h2
            hessian[j, i] = hessian[i, j]

# Parameter std from inverse Hessian (Cramer-Rao)
try:
    param_cov = np.linalg.inv(hessian)
    param_std = np.sqrt(np.maximum(np.diag(param_cov), 0))
    # Sanity: if any std is zero or huge, fall back
    param_std = np.where(
        (param_std > 0) & (param_std < 10 * np.abs(best_params)),
        param_std,
        np.abs(best_params) * 0.05,
    )
except np.linalg.LinAlgError:
    param_std = np.abs(best_params) * 0.05

# Monte Carlo uncertainty propagation
rng = np.random.default_rng(99)
y1_samples = []
y2_samples = []
bounds = best_model.PARAM_BOUNDS

for _ in range(200):
    p_sample = best_params + rng.normal(0, 1, n_params) * param_std
    p_sample = np.array([
        np.clip(p_sample[k], bounds[k][0], bounds[k][1])
        for k in range(n_params)
    ])
    try:
        s = solve_ivp(
            lambda t, y, p=list(p_sample): best_model.vector_field(t, y, p),
            [T_START, max(PRED_TIMES) + 0.01],
            Y0,
            method="DOP853",
            t_eval=PRED_TIMES,
            rtol=1e-8,
            atol=1e-10,
        )
        if s.status == 0 and np.all(np.isfinite(s.y)):
            y1_samples.append(s.y[0])
            y2_samples.append(s.y[1])
    except Exception:
        pass

if len(y1_samples) > 10:
    y1_std = np.std(y1_samples, axis=0).tolist()
    y2_std = np.std(y2_samples, axis=0).tolist()
else:
    y1_std = [NOISE_STD * 3.0] * len(PRED_TIMES)
    y2_std = [NOISE_STD * 3.0] * len(PRED_TIMES)

prediction_json = {
    "times": PRED_TIMES,
    "y1_mean": sol_pred.y[0].tolist(),
    "y2_mean": sol_pred.y[1].tolist(),
    "y1_std": y1_std,
    "y2_std": y2_std,
}
with open("/app/results/prediction.json", "w") as f:
    json.dump(prediction_json, f, indent=2)

# ---------------------------------------------------------------------------
# Write diagnostics.json
# ---------------------------------------------------------------------------

sol_train = solve_ivp(
    lambda t, y: best_model.vector_field(t, y, list(best_params)),
    [T_START, t_obs[-1] + 0.01],
    Y0,
    method="DOP853",
    t_eval=t_obs,
    rtol=1e-10,
    atol=1e-12,
)

res_y1 = y1_obs - sol_train.y[0]
res_y2 = y2_obs - sol_train.y[1]

diagnostics_json = {
    "training_rmse_y1": float(np.sqrt(np.mean(res_y1 ** 2))),
    "training_rmse_y2": float(np.sqrt(np.mean(res_y2 ** 2))),
    "normalized_residual_variance_y1": float(np.var(res_y1 / NOISE_STD)),
    "normalized_residual_variance_y2": float(np.var(res_y2 / NOISE_STD)),
}
with open("/app/results/diagnostics.json", "w") as f:
    json.dump(diagnostics_json, f, indent=2)

print(f"\nSelected: {best_name}")
print(f"Parameters: {selected_json['fitted_parameters']}")
print(f"Diagnostics: {diagnostics_json}")
print("Done!")
