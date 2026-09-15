// Hierarchical AR(1) model for longitudinal panel data
// J subjects observed over T time points
// Subject-specific intercepts and innovation variances
// Non-centered parameterization for hierarchical effects
//

data {
  int<lower=1> J;          // number of subjects
  int<lower=1> T;          // number of time points per subject
  array[J, T] real y;      // panel observations
}

parameters {
  real<lower=0, upper=1> rho;         // AR(1) coefficient

  // Hierarchical parameters for subject-level intercepts (AR intercept form)
  real gamma_alpha;                    // population mean of subject intercepts
  real<lower=0> tau_alpha;             // population SD of subject intercepts

  // Hierarchical parameters for subject-level log innovation SDs
  real gamma_logsigma;                 // population mean of log(sigma)
  real<lower=0> tau_logsigma;          // population SD of log(sigma)

  // Raw standard normal draws for non-centered parameterization
  vector[J] z;
}

transformed parameters {
  // Subject-specific intercepts (in AR(1) intercept form: y_t = alpha + rho*y_{t-1})
  vector[J] alpha = gamma_alpha + tau_alpha * z;

  // Subject-specific innovation standard deviations
  // NOTE: uses the same z vector as alpha above
  vector[J] logsigma = gamma_logsigma + tau_logsigma * z;
  vector<lower=0>[J] sigma = exp(logsigma);
}

model {
  // Priors
  rho ~ beta(1, 1);

  gamma_alpha ~ normal(0, 100);
  gamma_logsigma ~ normal(0, 100);

  tau_alpha ~ cauchy(0, 5);
  tau_logsigma ~ cauchy(0, 5);

  z ~ std_normal();

  // Likelihood: AR(1) in intercept form
  for (j in 1:J) {
    // First observation from stationary distribution
    y[j, 1] ~ normal(alpha[j] / (1 - rho), sigma[j] / sqrt(1 - rho^2));
    for (t in 2:T) {
      y[j, t] ~ normal(alpha[j] + rho * y[j, t-1], sigma[j]);
    }
  }
}

generated quantities {
  // Implied unconditional means (derived from intercept form)
  vector[J] mu_implied = alpha / (1 - rho);
}
