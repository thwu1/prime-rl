"""Groundwater system characterization analysis.

Derives reference ET from meteorological data, builds competing groundwater
time series models with different impulse response functions, performs model
selection via AIC, extracts response characteristics, computes residual
diagnostics, and validates via split-sample test.
"""

import json
import numpy as np
import pandas as pd
import pastas as ps
import pyet

# ---- 1. Read data ----
head = pd.read_csv("/app/data/head.csv", index_col=0, parse_dates=True).squeeze()
head.name = "head"

prec = pd.read_csv("/app/data/precipitation.csv", index_col=0, parse_dates=True).squeeze()
prec.name = "precipitation"

temp = pd.read_csv("/app/data/temperature.csv", index_col=0, parse_dates=True)
meteo = pd.read_csv("/app/data/meteo.csv", index_col=0, parse_dates=True)

# Parse metadata for coordinates
lat_deg = 52.1
elevation = 10  # meters
lat_rad = lat_deg * np.pi / 180.0

# ---- 2. Compute FAO-56 Penman-Monteith reference ET ----
tmean = temp["tmean"]
tmin = temp["tmin"]
tmax = temp["tmax"]
rh = meteo["rh"]
wind = meteo["wind"]
rs = meteo["rs"]

et = pyet.pm_fao56(
    tmean,
    wind=wind,
    rs=rs,
    tmax=tmax,
    tmin=tmin,
    rh=rh,
    elevation=elevation,
    lat=lat_rad,
)
et.name = "evaporation"

# Handle any NaN values in ET
et = et.ffill().bfill()
et = et.clip(lower=0)

# ET statistics
et_mean = float(et.mean())
et_annual = float(et.mean() * 365.25)

# ---- 3. Define calibration and validation periods ----
cal_start = "2003-01-01"
cal_end = "2011-12-31"
val_start = "2012-01-01"
val_end = "2015-12-31"

# ---- 4. Build and calibrate models with different response functions ----
response_functions = {
    "Exponential": ps.Exponential,
    "Gamma": ps.Gamma,
    "FourParam": ps.FourParam,
}

model_results = {}

for rfunc_name, rfunc_class in response_functions.items():
    ml = ps.Model(head, name=f"model_{rfunc_name}")
    rm = ps.RechargeModel(prec, et, rfunc=rfunc_class(), name="recharge")
    ml.add_stressmodel(rm)

    try:
        ml.solve(
            tmin=cal_start,
            tmax=cal_end,
            report=False,
        )
    except Exception as e:
        print(f"Warning: Model {rfunc_name} failed to solve: {e}")
        continue

    # Compute calibration metrics
    res = ml.residuals()
    obs = ml.observations()
    n_obs = len(res)
    rss = float(np.sum(res.values ** 2))
    k = int(ml.parameters["vary"].sum())

    evp = float((1 - np.var(res.values) / np.var(obs.values)) * 100)
    rmse = float(np.sqrt(np.mean(res.values ** 2)))
    aic = float(n_obs * np.log(rss / n_obs) + 2 * k)

    model_results[rfunc_name] = {
        "evp": round(evp, 2),
        "rmse": round(rmse, 4),
        "aic": round(aic, 2),
        "n_parameters": k,
        "_model": ml,  # keep reference for later analysis
    }

# ---- 5. Select best model by AIC ----
best_name = min(
    model_results,
    key=lambda x: model_results[x]["aic"],
)
ml_best = model_results[best_name]["_model"]

# ---- 6. Extract step response characteristics ----
step = ml_best.get_step_response("recharge")
gain = float(step.iloc[-1])

# Normalize step response and find 95% response time
step_norm = step / step.iloc[-1] if abs(step.iloc[-1]) > 1e-10 else step
t95_indices = np.where(step_norm.values >= 0.95)[0]
if len(t95_indices) > 0:
    t95 = float(step.index[t95_indices[0]])
else:
    t95 = float(step.index[-1])

# ---- 7. Durbin-Watson statistic ----
res_best = ml_best.residuals()
diffs = np.diff(res_best.values)
dw = float(np.sum(diffs ** 2) / np.sum(res_best.values ** 2))

# ---- 8. Residual diagnostics ----
res_values = res_best.values

# Lag-1 Pearson autocorrelation
lag1_ac = float(np.corrcoef(res_values[:-1], res_values[1:])[0, 1])

# Monthly mean residuals and seasonal amplitude
res_series = pd.Series(res_values, index=res_best.index)
monthly_means = res_series.groupby(res_series.index.month).mean()
seasonal_amp = float((monthly_means.max() - monthly_means.min()) / 2)

# ---- 9. Split-sample validation ----
# Simulate best model over validation period using calibrated parameters
sim_val = ml_best.simulate(tmin=val_start, tmax=val_end)

# Get observations in validation period
obs_val = head.loc[val_start:val_end].dropna()

# Interpolate simulation to observation timestamps
sim_at_obs = np.interp(
    obs_val.index.astype(np.int64).astype(np.float64),
    sim_val.index.astype(np.int64).astype(np.float64),
    sim_val.values,
)

res_val = obs_val.values - sim_at_obs
val_evp = float((1.0 - np.var(res_val) / np.var(obs_val.values)) * 100)
val_rmse = float(np.sqrt(np.mean(res_val ** 2)))

# ---- 10. Assemble and write results ----
# Clean model results (remove _model references)
models_output = {}
for name, mr in model_results.items():
    models_output[name] = {
        "evp": mr["evp"],
        "rmse": mr["rmse"],
        "aic": mr["aic"],
        "n_parameters": mr["n_parameters"],
    }

results = {
    "et_stats": {
        "method": "FAO-56 Penman-Monteith",
        "mean_mm_day": round(et_mean, 3),
        "annual_total_mm": round(et_annual, 1),
    },
    "models": models_output,
    "best_model": best_name,
    "best_model_evp": model_results[best_name]["evp"],
    "response_time_95": round(t95, 1),
    "step_response_gain": round(gain, 4),
    "durbin_watson": round(dw, 4),
    "n_observations": int(len(head)),
    "calibration_period": {
        "start": cal_start,
        "end": cal_end,
    },
    "validation": {
        "evp": round(val_evp, 2),
        "rmse": round(val_rmse, 4),
        "period": {
            "start": val_start,
            "end": val_end,
        },
    },
    "residual_diagnostics": {
        "lag1_autocorrelation": round(lag1_ac, 4),
        "seasonal_amplitude_m": round(seasonal_amp, 4),
    },
}

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"Best model: {best_name}")
print(f"  Calibration EVP: {model_results[best_name]['evp']}%")
print(f"  Validation EVP: {round(val_evp, 2)}%")
print(f"  95% response time: {round(t95, 1)} days")
print(f"  Step response gain: {round(gain, 4)}")
print(f"  Durbin-Watson: {round(dw, 4)}")
print(f"  Lag-1 autocorrelation: {round(lag1_ac, 4)}")
print(f"  Seasonal amplitude: {round(seasonal_amp, 4)} m")
print(f"  Mean ET: {round(et_mean, 2)} mm/day")
print("Results written to /app/results.json")
