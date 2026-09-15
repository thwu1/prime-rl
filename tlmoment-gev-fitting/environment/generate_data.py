import numpy as np
import json
import os

rng = np.random.default_rng(20240315)

os.makedirs('/app/data/raw', exist_ok=True)
os.makedirs('/app/logs', exist_ok=True)

# Site Alpha: clean GEV(loc=15, scale=4.0, shape=-0.1)
alpha_c = -0.1
alpha_loc = 15.0
alpha_scale = 4.0
u = rng.uniform(1e-10, 1 - 1e-10, size=3000)
alpha_data = alpha_loc + alpha_scale * (1.0 - (-np.log(u)) ** alpha_c) / alpha_c
np.save('/app/data/raw/site_alpha.npy', alpha_data)

# Site Beta: contaminated GEV(loc=10, scale=3.5, shape=-0.15) + Cauchy outliers
beta_c = -0.15
beta_loc = 10.0
beta_scale = 3.5
u = rng.uniform(1e-10, 1 - 1e-10, size=4950)
beta_gev = beta_loc + beta_scale * (1.0 - (-np.log(u)) ** beta_c) / beta_c
cauchy_raw = rng.standard_cauchy(size=50)
cauchy_clipped = np.clip(cauchy_raw, -40, 40)
cauchy_samples = 80.0 + 15.0 * cauchy_clipped
beta_data = np.concatenate([beta_gev, cauchy_samples])
rng.shuffle(beta_data)
np.save('/app/data/raw/site_beta.npy', beta_data)

# Site Gamma: clean GEV(loc=25, scale=6.0, shape=-0.2)
gamma_c = -0.2
gamma_loc = 25.0
gamma_scale = 6.0
u = rng.uniform(1e-10, 1 - 1e-10, size=2000)
gamma_data = gamma_loc + gamma_scale * (1.0 - (-np.log(u)) ** gamma_c) / gamma_c
np.save('/app/data/raw/site_gamma.npy', gamma_data)

# Pipeline execution log (shows site_beta flagged but does NOT explain why)
log_content = """=== Extreme Value Analysis Pipeline ===
Run ID: EVA-2024-0315
Timestamp: 2024-03-15T14:23:07Z
Method: Maximum Likelihood Estimation
Input: /app/data/raw/

--- Processing site_alpha (n=3000) ---
  Optimizer: L-BFGS-B converged in 23 iterations
  Estimates: loc=14.87  scale=3.95  shape=-0.098
  Log-likelihood: -8234.12
  AIC: 16474.24
  Status: PASS

--- Processing site_beta (n=5000) ---
  Optimizer: L-BFGS-B reached max iterations (500)
  WARNING: Hessian matrix near-singular at solution point
  WARNING: Gradient norm 2.34e-02 exceeds tolerance
  Estimates: loc=22.41  scale=8.73  shape=-0.42
  Log-likelihood: -18921.56
  AIC: 37849.12
  Status: FLAGGED

--- Processing site_gamma (n=2000) ---
  Optimizer: L-BFGS-B converged in 31 iterations
  Estimates: loc=24.82  scale=5.91  shape=-0.193
  Log-likelihood: -6102.78
  AIC: 12211.56
  Status: PASS

=== Summary ===
Total sites: 3
Passed: 2 (site_alpha, site_gamma)
Flagged: 1 (site_beta)

site_beta estimates are unreliable. Shape parameter -0.42 is unusually
negative and location/scale estimates appear inflated. Manual review of
input data and methodology is required before using these estimates
for design calculations.
"""
with open('/app/logs/pipeline_run_20240315.log', 'w') as f:
    f.write(log_content)

# Configuration file
config = {
    "pipeline": {
        "input_dir": "/app/data/raw/",
        "output_file": "/app/results.json"
    },
    "distribution": "GEV",
    "shape_convention": "scipy genextreme: c < 0 = Frechet (heavy right tail), Q(u,c) = loc + scale*(1-(-log u)^c)/c"
}
with open('/app/config.json', 'w') as f:
    json.dump(config, f, indent=2)

# Output schema (tells the solver WHAT to output but not HOW to solve it)
schema = {
    "_description": "Required output format for corrected GEV parameter estimates",
    "sites": {
        "<site_name>": {
            "lmoments": ["lambda_1", "lambda_2", "lambda_3", "lambda_4"],
            "tlmoments": ["tl_1 (s=1, t=1)", "tl_2", "tl_3", "tl_4"],
            "lratios": ["tau_3 = l3/l2", "tau_4 = l4/l2"],
            "tlratios": ["tau_3_tl = tl3/tl2", "tau_4_tl = tl4/tl2"],
            "gev_params": {
                "loc": "location",
                "scale": "scale (positive)",
                "shape": "shape (scipy convention)"
            },
            "estimation_method": "lmom | tlmom",
            "data_quality": "clean | contaminated"
        }
    }
}
with open('/app/output_schema.json', 'w') as f:
    json.dump(schema, f, indent=2)

print("Environment setup complete")
print(f"  site_alpha: {len(alpha_data)} observations")
print(f"  site_beta: {len(beta_data)} observations")
print(f"  site_gamma: {len(gamma_data)} observations")
