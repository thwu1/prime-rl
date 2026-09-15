// Bayesian Lotka-Volterra predator-prey model with lognormal observation error
// Uses modern ode_rk45 interface (vector state)
//

functions {
  vector dz_dt(real t, vector z, array[] real theta) {
    real u = z[1];  // prey (hare)
    real v = z[2];  // predator (lynx)

    real alpha = theta[1];  // prey intrinsic growth rate
    real beta  = theta[2];  // predation rate
    real gamma = theta[3];  // predator intrinsic death rate
    real delta = theta[4];  // predator growth from prey

    vector[2] dzdt;
    dzdt[1] = (alpha - beta * v) * u;
    dzdt[2] = (-gamma + delta * u) * v;
    return dzdt;
  }
}

data {
  int<lower=0> N;                        // number of observation times (excludes t=0)
  array[N] real ts;                      // observation times (1, 2, ..., N)
  array[2] real y_init;                  // initial observed populations [hare, lynx] at t=0
  array[N, 2] real<lower=0> y;          // observed populations at ts
  int<lower=1> N_pred;                   // number of forward prediction times
  array[N_pred] real ts_pred;           // prediction times (N+1, N+2, ...)
}

parameters {
  array[4] real<lower=0> theta;          // ODE parameters {alpha, beta, gamma, delta}
  array[2] real<lower=0> z_init;         // initial latent populations
  array[2] real<lower=0> sigma;          // per-species measurement error scales
}

transformed parameters {
  array[N] vector[2] z = ode_rk45(dz_dt, to_vector(z_init), 0.0, ts, theta);
}

model {
  // Priors
  theta[{1, 3}] ~ normal(1, 0.5);
  theta[{2, 4}] ~ normal(0.05, 0.05);
  sigma ~ lognormal(-1, 1);
  z_init ~ lognormal(log(10), 1);

  // Lognormal observation model
  for (k in 1:2) {
    y_init[k] ~ lognormal(log(z_init[k]), sigma[k]);
    for (n in 1:N)
      y[n, k] ~ lognormal(log(z[n][k]), sigma[k]);
  }
}

generated quantities {
  // Posterior predictive replication for observed period
  array[2] real y_init_rep;
  array[N, 2] real y_rep;

  for (k in 1:2) {
    y_init_rep[k] = lognormal_rng(log(z_init[k]), sigma[k]);
    for (n in 1:N)
      y_rep[n, k] = lognormal_rng(log(z[n][k]), sigma[k]);
  }

  // Forward predictions: solve ODE from last observed state
  array[N_pred] vector[2] z_pred = ode_rk45(dz_dt, z[N], ts[N], ts_pred, theta);
  array[N_pred, 2] real y_pred;
  for (k in 1:2)
    for (n in 1:N_pred)
      y_pred[n, k] = lognormal_rng(log(z_pred[n][k]), sigma[k]);
}
