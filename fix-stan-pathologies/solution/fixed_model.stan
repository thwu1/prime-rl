// Fixed hierarchical AR(1) model for longitudinal panel data
//
// Fixes applied:
// 1. Unconditional mean parameterization replaces intercept form
//    - Eliminates alpha/rho correlation singularity near unit root
//    - y[t] = (1-rho)*mu + rho*y[t-1] instead of alpha + rho*y[t-1]
//
// 2. Separate NCP raw vectors for subject means and log-SDs
//    - z_mu for subject unconditional means
//    - z_logsigma for subject innovation log-SDs
//    - Eliminates spurious perfect correlation from shared z
//
// 3. Weakly informative priors replace heavy-tailed Cauchy
//    - exponential(1) for scale parameters instead of cauchy(0,5)
//    - normal(0,10) for location parameters instead of normal(0,100)
//    - Eliminates funnel geometry from fat-tailed scale priors

data {
  int<lower=1> J;          // number of subjects
  int<lower=1> T;          // number of time points per subject
  array[J, T] real y;      // panel observations
}

parameters {
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
}

transformed parameters {
  // Subject-specific unconditional means
  vector[J] mu = gamma_mu + tau_mu * z_mu;

  // Subject-specific innovation standard deviations
  vector[J] logsigma = gamma_logsigma + tau_logsigma * z_logsigma;
  vector<lower=0>[J] sigma = exp(logsigma);
}

model {
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
}

generated quantities {
  // Derived intercepts (for comparison with original parameterization)
  vector[J] alpha_derived = (1 - rho) * mu;
}
