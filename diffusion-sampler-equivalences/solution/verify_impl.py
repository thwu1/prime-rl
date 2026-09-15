"""
Verify mathematical equivalences between diffusion formulations and write results.json.
"""

import json
import numpy as np
from diffusion import (
    linear_beta_schedule,
    cosine_alpha_bar_schedule,
    ddpm_ancestral_step,
    ddim_step,
    vp_to_edm_sigma,
    signal_to_noise_ratio,
    predicted_x0,
)

results = {}

# 1. Linear schedule boundary values
s_lin = linear_beta_schedule(1000, 1e-4, 0.02)
results["linear_alpha_bar_first"] = float(s_lin["alpha_bar"][0])
results["linear_alpha_bar_last"] = float(s_lin["alpha_bar"][-1])

# 2. Cosine schedule monotonicity
s_cos = cosine_alpha_bar_schedule(1000, s=0.008)
results["cosine_monotonic"] = bool(np.all(np.diff(s_cos["alpha_bar"]) < 0))

# 3. Forward reparameterization consistency
np.random.seed(42)
x_0 = np.random.randn(100)
eps = np.random.randn(100)
max_diff = 0.0
for t in [0, 50, 200, 500, 999]:
    ab_t = s_lin["alpha_bar"][t]
    x_t = np.sqrt(ab_t) * x_0 + np.sqrt(1 - ab_t) * eps
    recovered = predicted_x0(x_t, eps, t, s_lin)
    diff = np.max(np.abs(recovered - x_0))
    max_diff = max(max_diff, diff)
results["forward_consistency_max_diff"] = float(max_diff)

# 4. DDIM determinism (eta=0)
np.random.seed(42)
x_t_test = np.random.randn(100)
eps_test = np.random.randn(100)
z1 = np.random.randn(100)
z2 = np.random.randn(100)
r1 = ddim_step(x_t_test, eps_test, 500, 499, s_lin, eta=0.0, z=z1)
r2 = ddim_step(x_t_test, eps_test, 500, 499, s_lin, eta=0.0, z=z2)
results["ddim_deterministic_max_diff"] = float(np.max(np.abs(r1 - r2)))

# 5. DDPM vs DDIM(eta=1) equivalence
np.random.seed(123)
x_t_eq = np.random.randn(100)
eps_eq = np.random.randn(100)
z_eq = np.random.randn(100)
max_equiv_diff = 0.0
for t in [1, 50, 200, 500, 999]:
    ddpm_r = ddpm_ancestral_step(x_t_eq, eps_eq, t, s_lin, z=z_eq)
    ddim_r = ddim_step(x_t_eq, eps_eq, t, t - 1, s_lin, eta=1.0, z=z_eq)
    diff = np.max(np.abs(ddpm_r - ddim_r))
    max_equiv_diff = max(max_equiv_diff, diff)
results["ddpm_ddim_eta1_max_diff"] = float(max_equiv_diff)

# 6. VP-to-EDM conversion at alpha_bar=0.5
results["edm_sigma_at_half"] = float(vp_to_edm_sigma(0.5))

# 7. SNR at alpha_bar=0.5
results["snr_at_half"] = float(signal_to_noise_ratio(0.5))

# 8. SNR = 1/sigma_edm^2 relationship
holds = True
for ab in [0.1, 0.3, 0.5, 0.7, 0.9]:
    snr = signal_to_noise_ratio(ab)
    sigma = vp_to_edm_sigma(ab)
    if not np.isclose(snr, 1.0 / sigma ** 2, rtol=1e-8):
        holds = False
results["snr_edm_relationship_holds"] = holds

with open("/app/results.json", "w") as f:
    json.dump(results, f, indent=2)

print("Verification complete. Results written to /app/results.json")
print(json.dumps(results, indent=2))
