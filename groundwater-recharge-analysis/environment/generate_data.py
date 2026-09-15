"""Generate synthetic groundwater and meteorological data for the task.

Creates realistic time series for a monitoring well at ~52N latitude
with known underlying response function parameters for verification.
"""

import numpy as np
import pandas as pd
import os

np.random.seed(42)

dates = pd.date_range("2000-01-01", "2015-12-31", freq="D")
n = len(dates)
doy = dates.dayofyear.values.astype(float)

# --- Temperature (deg C) - seasonal cycle for Northern Europe (~52N) ---
tmean = 10.0 + 8.5 * np.sin(2 * np.pi * (doy - 105) / 365.25)
tmean += np.random.normal(0, 2.0, n)
tmin = tmean - 4.5 + np.random.normal(0, 0.7, n)
tmax = tmean + 4.5 + np.random.normal(0, 0.7, n)
tmin = np.minimum(tmin, tmean - 0.5)
tmax = np.maximum(tmax, tmean + 0.5)

# --- Relative Humidity (%) ---
rh = 78.0 - 12.0 * np.sin(2 * np.pi * (doy - 105) / 365.25)
rh += np.random.normal(0, 4.0, n)
rh = np.clip(rh, 35, 98)

# --- Wind speed at 2m height (m/s) ---
wind = 3.0 + 0.8 * np.sin(2 * np.pi * (doy - 30) / 365.25)
wind += np.abs(np.random.normal(0, 0.7, n))
wind = np.clip(wind, 0.5, 8.0)

# --- Incoming solar radiation (MJ/m2/day) ---
rs = 8.0 + 9.0 * np.sin(2 * np.pi * (doy - 80) / 365.25)
rs += np.random.normal(0, 1.5, n)
rs = np.clip(rs, 0.5, 25.0)

# --- Precipitation (mm/day) ---
wet_prob = 0.50 + 0.10 * np.cos(2 * np.pi * (doy - 105) / 365.25)
wet_day = np.random.random(n) < wet_prob
precipitation = np.zeros(n)
prec_scale = 3.0 + 0.5 * np.cos(2 * np.pi * (doy - 105) / 365.25)
precipitation[wet_day] = np.random.gamma(1.5, prec_scale[wet_day])

# --- Simple ET estimate for head generation (not from pyet) ---
et_gen = np.clip(0.13 * np.maximum(tmean, 0) + 0.3, 0.1, 5.0)

# --- Generate groundwater head via convolution ---
# Linear recharge: R = max(P - f * ET, 0)
f_evap = 1.0
recharge = np.maximum(precipitation - f_evap * et_gen, 0)

# Exponential block response: h(t) = (A/a) * exp(-t/a)
# Step response gain = A, memory = a
A_true = 2.5
a_true = 200.0
t_resp = np.arange(0, 3000)
block = A_true * np.exp(-t_resp / a_true) / a_true

head_contrib = np.convolve(recharge, block, mode="full")[:n]
base_level = 25.5
head = base_level + head_contrib + np.random.normal(0, 0.08, n)

# --- Irregular observations (~65% coverage) ---
obs_mask = np.random.random(n) < 0.65
obs_mask[0] = True
obs_mask[-1] = True
head_obs = pd.Series(head, index=dates, name="head")
head_obs = head_obs[obs_mask]

# --- Save all data ---
os.makedirs("/app/data", exist_ok=True)

head_obs.to_csv("/app/data/head.csv", header=True)

pd.Series(precipitation, index=dates, name="precipitation").to_csv(
    "/app/data/precipitation.csv", header=True
)

pd.DataFrame(
    {"tmean": tmean, "tmin": tmin, "tmax": tmax}, index=dates
).to_csv("/app/data/temperature.csv")

pd.DataFrame(
    {"rh": rh, "wind": wind, "rs": rs}, index=dates
).to_csv("/app/data/meteo.csv")

with open("/app/data/metadata.txt", "w") as f:
    f.write("Station: Synthetic Well NL-042\n")
    f.write("Latitude: 52.1 degrees N\n")
    f.write("Longitude: 5.18 degrees E\n")
    f.write("Elevation: 10 m above sea level\n")
    f.write("Data period: 2000-01-01 to 2015-12-31\n")
    f.write("Variables and units:\n")
    f.write("  head.csv - groundwater head (m above mean sea level)\n")
    f.write("  precipitation.csv - daily precipitation (mm/day)\n")
    f.write("  temperature.csv - daily air temperature:\n")
    f.write("    tmean, tmin, tmax (degrees Celsius)\n")
    f.write("  meteo.csv - meteorological data:\n")
    f.write("    rh: relative humidity (%)\n")
    f.write("    wind: wind speed at 2m height (m/s)\n")
    f.write("    rs: incoming shortwave solar radiation (MJ/m2/day)\n")

print(f"Generated {len(head_obs)} head observations")
print(f"Head range: {head.min():.2f} to {head.max():.2f} m")
print(f"Mean precipitation: {precipitation.mean():.2f} mm/day")
print(f"Mean ET (generation): {et_gen.mean():.2f} mm/day")
