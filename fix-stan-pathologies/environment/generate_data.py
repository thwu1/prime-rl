#!/usr/bin/env python3
"""Generate simulated panel data from a hierarchical AR(1) model.

True data-generating process:
  y[j,t] = (1 - rho) * mu[j] + rho * y[j,t-1] + Normal(0, sigma[j])
  mu[j]       ~ Normal(gamma_mu, tau_mu)
  log(sigma[j]) ~ Normal(gamma_logsigma, tau_logsigma)
"""

import json
import random
import math

random.seed(42)

J = 10   # subjects
T = 30   # time points per subject

# True population parameters
rho_true = 0.92
gamma_mu_true = 5.0
tau_mu_true = 1.5
gamma_logsigma_true = -0.5
tau_logsigma_true = 0.3

# Generate subject-level parameters
mu_true = [random.gauss(gamma_mu_true, tau_mu_true) for _ in range(J)]
logsigma_true = [random.gauss(gamma_logsigma_true, tau_logsigma_true) for _ in range(J)]
sigma_true = [math.exp(ls) for ls in logsigma_true]

# Generate panel data
y = []
for j in range(J):
    yj = [0.0] * T
    yj[0] = random.gauss(mu_true[j], sigma_true[j])
    for t in range(1, T):
        mean_t = (1.0 - rho_true) * mu_true[j] + rho_true * yj[t - 1]
        yj[t] = random.gauss(mean_t, sigma_true[j])
    y.append(yj)

# Save as CmdStan JSON
data = {"J": J, "T": T, "y": y}
with open("/app/data.json", "w") as f:
    json.dump(data, f, indent=2)

# Save true parameters for verification
truth = {
    "rho": rho_true,
    "gamma_mu": gamma_mu_true,
    "tau_mu": tau_mu_true,
    "gamma_logsigma": gamma_logsigma_true,
    "tau_logsigma": tau_logsigma_true,
    "mu": mu_true,
    "sigma": sigma_true
}
with open("/app/true_params.json", "w") as f:
    json.dump(truth, f, indent=2)

print("Data generated: J={}, T={}".format(J, T))
print("True rho = {}".format(rho_true))
for j in range(J):
    print("  Subject {}: mu={:.2f}, sigma={:.3f}".format(j + 1, mu_true[j], sigma_true[j]))
