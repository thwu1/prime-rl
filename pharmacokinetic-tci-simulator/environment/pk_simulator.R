#
# Three-compartment pharmacokinetic models with effect-site targeting TCI
#
# Models:
#   Schnider (1998) propofol
#   Marsh (1991) propofol
#   Eleveld (2018) propofol
#   Minto (1997) remifentanil
#
# Body composition:
#   James (1976) lean body mass
#   Al-Sallami (2015) fat-free mass

# ============================================================
# Body Composition
# ============================================================

james_lbm <- function(height_cm, weight_kg, sex) {
  if (sex == "m") {
    lbm <- 1.1 * weight_kg - 128 * (weight_kg / height_cm)^2
  } else {
    lbm <- 1.17 * weight_kg - 148 * (weight_kg / height_cm)^2
  }
  max(lbm, 0)
}

alsallami_ffm <- function(age, height_cm, weight_kg, sex) {
  bmi <- weight_kg / (height_cm / 100)^2
  if (sex == "m") {
    mat <- 0.88 + (1 - 0.88) / (1 + (age / 13.4)^(-12.7))
    ffm <- mat * (9270 * weight_kg) / (6680 + 216 * bmi)
  } else {
    mat <- 1.11 + (1 - 1.11) / (1 + (age / 7.1)^(-1.1))
    ffm <- mat * (9270 * weight_kg) / (8780 + 244 * bmi)
  }
  ffm
}

# ============================================================
# Schnider (1998) Propofol Model
# ============================================================

schnider_params <- function(age, weight, height, sex) {
  lbm <- james_lbm(height, weight, sex)

  v1 <- 4.27
  v2 <- 18.9 - 0.391 * (age - 53)
  v3 <- 238

  cl1 <- 1.89 + 0.0456 * (weight - 77) - 0.0681 * (lbm - 59) + 0.0264 * (height - 177)
  cl2 <- 1.29 - 0.024 * (age - 53)
  cl3 <- 0.836

  k10 <- cl1 / v1
  k12 <- cl2 / v1
  k13 <- cl3 / v1
  k21 <- cl2 / v1
  k31 <- cl3 / v3
  ke0 <- 0.456

  list(v1=v1, v2=v2, v3=v3, k10=k10, k12=k12, k13=k13, k21=k21, k31=k31, ke0=ke0)
}

# ============================================================
# Marsh (1991) Propofol Model
# ============================================================

marsh_params <- function(weight) {
  v1 <- 0.228 * weight
  v2 <- 0.463 * weight
  v3 <- 2.893 * weight

  k10 <- 0.119
  k12 <- 0.112
  k13 <- 0.042
  k21 <- 0.055
  k31 <- 0.0031
  ke0 <- 0.26

  list(v1=v1, v2=v2, v3=v3, k10=k10, k12=k12, k13=k13, k21=k21, k31=k31, ke0=ke0)
}

# ============================================================
# Eleveld (2018) Propofol Model
# ============================================================

eleveld_propofol_params <- function(age, weight, height, sex, opiates = FALSE) {
  theta <- c(6.28, 25.5, 273, 1.79, 1.75, 1.11, 0.191, 42.3, 9.06,
             -0.0156, -0.00286, 33.6, -0.0138, 68.3, 2.10, 1.30, 1.42, 0.68)

  ageing <- function(i, a) exp(i * (a - 35))
  sigmoid <- function(x, e50, y) x^y / (x^y + e50^y)
  central <- function(i) sigmoid(i, theta[12], 1)

  pma <- age * 52 + 40
  pma_ref <- 35 * 52 + 40

  cl_mat <- sigmoid(pma, theta[8], theta[9])
  cl_mat_ref <- sigmoid(pma_ref, theta[8], theta[9])

  q3_mat <- sigmoid(pma, theta[14], 1)
  q3_mat_ref <- sigmoid(pma_ref, theta[14], 1)

  ffm <- alsallami_ffm(age, height, weight, sex)
  ffm_ref <- alsallami_ffm(35, 170, 70, "m")

  v1 <- theta[1] * central(weight) / central(70)
  v2 <- theta[2] * (weight / 70) * ageing(theta[10], age)
  v3 <- theta[3] * (ffm / ffm_ref)

  v2_ref <- theta[2]
  v3_ref <- theta[3]

  cl <- theta[4] * (weight / 70)^0.75 * (cl_mat / cl_mat_ref)

  q2 <- theta[5] * (v2 / v2_ref)^0.75 * (1 + theta[16] * (1 - q3_mat / q3_mat_ref))
  q3 <- theta[6] * (v3 / v3_ref)^0.75 * (q3_mat / q3_mat_ref)

  ke0 <- 0.146 * (weight / 70)^(-0.25)

  if (opiates) {
    v3 <- v3 * exp(theta[13] * age)
    cl <- cl * exp(theta[11] * age)
  }

  k10 <- cl / v1
  k12 <- q2 / v1
  k13 <- q3 / v1
  k21 <- q2 / v2
  k31 <- q3 / v3

  list(v1=v1, v2=v2, v3=v3, k10=k10, k12=k12, k13=k13, k21=k21, k31=k31, ke0=ke0)
}

# ============================================================
# Minto (1997) Remifentanil Model
# ============================================================

minto_params <- function(age, weight, height, sex) {
  lbm <- james_lbm(height, weight, sex)

  v1 <- 5.1 - 0.0201 * (age - 40) + 0.072 * (lbm - 55)
  v2 <- 9.82 - 0.0811 * (age - 40) + 0.108 * (lbm - 55)
  v3 <- 5.42

  cl1 <- 2.6 - 0.0162 * (age - 35) + 0.0191 * (lbm - 55)
  cl2 <- 2.05 - 0.0301 * (age - 35)
  cl3 <- 0.076 - 0.00113 * (age - 35)

  k10 <- cl1 / v1
  k12 <- cl2 / v1
  k13 <- cl3 / v1
  k21 <- cl2 / v2
  k31 <- cl3 / v3

  ke0 <- 0.595 - 0.007 * (age - 35)

  list(v1=v1, v2=v2, v3=v3, k10=k10, k12=k12, k13=k13, k21=k21, k31=k31, ke0=ke0)
}

# ============================================================
# ODE Solver (4th order Runge-Kutta)
# ============================================================

pk_deriv <- function(state, params, infusion_rate) {
  x1 <- state[1]
  x2 <- state[2]
  x3 <- state[3]
  xe <- state[4]

  dx1 <- -(params$k10 + params$k12 + params$k13) * x1 +
          params$k21 * x2 + params$k31 * x3 + infusion_rate / params$v1
  dx2 <- params$k12 * x1 - params$k21 * x2
  dx3 <- params$k13 * x1 - params$k31 * x3
  dxe <- params$ke0 * (x1 - xe)

  c(dx1, dx2, dx3, dxe)
}

rk4_step <- function(state, params, infusion_rate, dt) {
  k1 <- pk_deriv(state, params, infusion_rate)
  k2 <- pk_deriv(state + dt / 2 * k1, params, infusion_rate)
  k3 <- pk_deriv(state + dt / 2 * k2, params, infusion_rate)
  k4 <- pk_deriv(state + dt * k3, params, infusion_rate)

  state + (dt / 6) * (k1 + 2 * k2 + 2 * k3 + k4)
}

simulate_step <- function(state, params, infusion_rate, dt_min, n_substeps = 10) {
  sub_dt <- dt_min / n_substeps
  for (i in 1:n_substeps) {
    state <- rk4_step(state, params, infusion_rate, sub_dt)
  }
  state
}

# ============================================================
# TCI Algorithm
# ============================================================

tci_plasma_rate <- function(state, params, target_cp, dt_min, n_substeps = 10) {
  state_0 <- simulate_step(state, params, 0, dt_min, n_substeps)
  cp_0 <- state_0[1]

  if (cp_0 >= target_cp) return(0)

  test_rate <- 100
  state_test <- simulate_step(state, params, test_rate, dt_min, n_substeps)
  cp_test <- state_test[1]

  if (abs(cp_test - cp_0) < 1e-12) return(0)

  rate <- test_rate * (target_cp - cp_0) / (cp_test - cp_0)
  max(rate, 0)
}

tci_effect_rate <- function(state, params, target_ce, dt_min, n_substeps = 10) {
  # Effect-site targeting via plasma approximation
  tci_plasma_rate(state, params, target_ce, dt_min, n_substeps)
}

# ============================================================
# Simulation Driver
# ============================================================

run_scenario <- function(scenario) {
  model <- scenario$model

  params <- switch(model,
    "schnider" = schnider_params(scenario$age, scenario$weight,
                                  scenario$height, scenario$sex),
    "marsh" = marsh_params(scenario$weight),
    "eleveld" = eleveld_propofol_params(scenario$age, scenario$weight,
                                         scenario$height, scenario$sex,
                                         opiates = isTRUE(scenario$opiates)),
    "minto" = minto_params(scenario$age, scenario$weight,
                            scenario$height, scenario$sex)
  )

  dt_min <- scenario$dt_sec / 60
  total_steps <- round(scenario$total_time_min / dt_min)

  state <- c(0, 0, 0, 0)

  targets <- scenario$targets

  results <- data.frame(
    scenario_id = integer(0),
    time_min = numeric(0),
    plasma_conc = numeric(0),
    effect_conc = numeric(0),
    infusion_rate = numeric(0)
  )

  for (step in 1:total_steps) {
    t_min <- step * dt_min

    current_target <- targets[[1]]$ce_target
    for (tgt in targets) {
      if (t_min >= tgt$time_min) {
        current_target <- tgt$ce_target
      }
    }

    rate <- tci_effect_rate(state, params, current_target, dt_min)

    state <- simulate_step(state, params, rate, dt_min)

    results <- rbind(results, data.frame(
      scenario_id = scenario$id,
      time_min = round(t_min, 6),
      plasma_conc = state[1],
      effect_conc = state[4],
      infusion_rate = rate
    ))
  }

  results
}
