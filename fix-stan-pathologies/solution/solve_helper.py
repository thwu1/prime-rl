#!/usr/bin/env python3
"""
Generate a fixed hierarchical AR(1) Stan model.

Reads the broken model at /app/model.stan, identifies three interacting
pathologies, and writes a corrected model to /app/fixed_model.stan.

Fixes applied:
  1. Unconditional-mean parameterization replaces intercept form,
     eliminating the alpha/(1-rho) singularity near the unit root.
  2. Separate NCP raw vectors for subject means and log-SDs,
     eliminating spurious perfect correlation from the shared z vector.
  3. Weakly informative priors (exponential, narrower normals) replace
     heavy-tailed Cauchy scale priors and overly diffuse location priors,
     eliminating funnel geometry.

"""

import json
import re


def read_broken_model(path="/app/model.stan"):
    """Read the broken model to extract data block dimensions."""
    with open(path, "r") as f:
        content = f.read()
    return content


def diagnose_pathologies(model_text):
    """Identify pathologies in the broken model."""
    issues = []

    # Pathology 1: intercept form with rho near unit root
    if "alpha" in model_text and "rho * y[j, t-1]" in model_text:
        issues.append("intercept_form")

    # Pathology 2: shared z vector for two distinct hierarchical effects
    if model_text.count("vector[J] z") == 1:
        z_uses = len(re.findall(r'\bz\b', model_text))
        if z_uses > 3:  # declaration + two uses in transformed parameters
            issues.append("shared_ncp_vector")

    # Pathology 3: heavy-tailed Cauchy priors on scale parameters
    if "cauchy" in model_text.lower():
        issues.append("cauchy_scale_priors")

    # Pathology 3b: overly diffuse location priors
    if "normal(0, 100)" in model_text:
        issues.append("diffuse_location_priors")

    return issues


def build_fixed_model():
    """Construct the corrected Stan model."""

    data_block = """data {
  int<lower=1> J;          // number of subjects
  int<lower=1> T;          // number of time points per subject
  array[J, T] real y;      // panel observations
}"""

    parameters_block = """parameters {
  real<lower=0, upper=1> rho;           // AR(1) coefficient

  // Hierarchical parameters for subject unconditional means
  real gamma_mu;                         // population mean
  real<lower=0> tau_mu;                  // population SD

  // Hierarchical parameters for subject log innovation SDs
  real gamma_logsigma;                   // population mean
  real<lower=0> tau_logsigma;            // population SD

  // Separate raw vectors for non-centered parameterization
  vector[J] z_mu;                        // raw for subject means
  vector[J] z_logsigma;                  // raw for subject log-SDs
}"""

    transformed_block = """transformed parameters {
  // Subject-specific unconditional means
  vector[J] mu = gamma_mu + tau_mu * z_mu;

  // Subject-specific innovation standard deviations
  vector[J] logsigma = gamma_logsigma + tau_logsigma * z_logsigma;
  vector<lower=0>[J] sigma = exp(logsigma);
}"""

    model_block = """model {
  // Weakly informative priors
  rho ~ beta(1, 1);

  gamma_mu ~ normal(0, 10);
  gamma_logsigma ~ normal(0, 5);

  tau_mu ~ exponential(1);
  tau_logsigma ~ exponential(1);

  z_mu ~ std_normal();
  z_logsigma ~ std_normal();

  // Likelihood: AR(1) in unconditional mean form
  for (j in 1:J) {
    y[j, 1] ~ normal(mu[j], sigma[j]);
    for (t in 2:T) {
      y[j, t] ~ normal((1 - rho) * mu[j] + rho * y[j, t - 1], sigma[j]);
    }
  }
}"""

    gq_block = """generated quantities {
  // Derived intercepts (for comparison with original parameterization)
  vector[J] alpha_derived = (1 - rho) * mu;
}"""

    header = (
        "// Fixed hierarchical AR(1) model for longitudinal panel data\n"
        "//\n"
        "// Fixes applied:\n"
        "// 1. Unconditional mean parameterization replaces intercept form\n"
        "//    - Eliminates alpha/rho correlation singularity near unit root\n"
        "//    - y[t] = (1-rho)*mu + rho*y[t-1] instead of alpha + rho*y[t-1]\n"
        "//\n"
        "// 2. Separate NCP raw vectors for subject means and log-SDs\n"
        "//    - z_mu for subject unconditional means\n"
        "//    - z_logsigma for subject innovation log-SDs\n"
        "//    - Eliminates spurious perfect correlation from shared z\n"
        "//\n"
        "// 3. Weakly informative priors replace heavy-tailed Cauchy\n"
        "//    - exponential(1) for scale parameters instead of cauchy(0,5)\n"
        "//    - normal(0,10) for location parameters instead of normal(0,100)\n"
        "//    - Eliminates funnel geometry from fat-tailed scale priors\n"
    )

    blocks = [header, data_block, parameters_block, transformed_block,
              model_block, gq_block]
    return "\n\n".join(blocks) + "\n"


def main():
    # Read and diagnose the broken model
    broken = read_broken_model()
    issues = diagnose_pathologies(broken)
    print("Diagnosed pathologies: {}".format(issues))

    # Build and write the fixed model
    fixed = build_fixed_model()
    with open("/app/fixed_model.stan", "w") as f:
        f.write(fixed)
    print("Fixed model has {} lines, {} parameters".format(
        len(fixed.splitlines()),
        sum(1 for line in fixed.splitlines() if "real" in line or "vector" in line)
    ))


if __name__ == "__main__":
    main()
