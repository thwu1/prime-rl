#!/usr/bin/env python3
#
# Fixes all defects in /app/pk_simulator.R

import sys

with open("/app/pk_simulator.R", "r") as f:
    code = f.read()

# ============================================================
# Fix 1: James LBM female coefficient (1.17 -> 1.07)
# The published James (1976) formula for females uses 1.07
# ============================================================
old_lbm = "1.17 * weight_kg"
new_lbm = "1.07 * weight_kg"
assert old_lbm in code, "Could not find James LBM female coefficient to fix"
code = code.replace(old_lbm, new_lbm)

# ============================================================
# Fix 2: Schnider k21 denominator (v1 -> v2)
# k21 = Cl2/V2 (transfer from central TO peripheral uses
# peripheral volume as denominator)
# ============================================================
old_k21 = "k21 <- cl2 / v1"
new_k21 = "k21 <- cl2 / v2"
assert old_k21 in code, "Could not find Schnider k21 to fix"
code = code.replace(old_k21, new_k21, 1)

# ============================================================
# Fix 3: Eleveld female clearance (theta[4] -> theta[15])
# The Eleveld 2018 model uses theta15=2.10 for female clearance
# and theta4=1.79 for male clearance
# ============================================================
old_cl = "  cl <- theta[4] * (weight / 70)^0.75 * (cl_mat / cl_mat_ref)"
new_cl = """  if (sex == "m") {
    cl <- theta[4] * (weight / 70)^0.75 * (cl_mat / cl_mat_ref)
  } else {
    cl <- theta[15] * (weight / 70)^0.75 * (cl_mat / cl_mat_ref)
  }"""
assert old_cl in code, "Could not find Eleveld clearance line to fix"
code = code.replace(old_cl, new_cl, 1)

# ============================================================
# Fix 4: Minto age reference (35 -> 40)
# The Minto 1997 model uses age=40 as the reference covariate
# center for clearance and ke0 (matching the volume equations)
# ============================================================
old_age = "(age - 35)"
new_age = "(age - 40)"
count = code.count(old_age)
assert count > 0, "Could not find Minto age reference to fix"
code = code.replace(old_age, new_age)

# ============================================================
# Fix 5: Implement effect-site TCI algorithm
# The stub delegates to plasma targeting which targets Cp=target
# instead of driving Ce toward the target. Correct approach uses
# peak-Ce targeting (Shafer-Gregg): find the infusion rate for
# one step such that the resulting peak effect-site concentration
# (after redistribution with zero further infusion) equals the
# target. This avoids the overshoot of one-step deadbeat control
# and the oscillation of simple virtual-Cp approaches.
# ============================================================
old_tci = """tci_effect_rate <- function(state, params, target_ce, dt_min, n_substeps = 10) {
  # Effect-site targeting via plasma approximation
  tci_plasma_rate(state, params, target_ce, dt_min, n_substeps)
}"""

new_tci = """tci_effect_rate <- function(state, params, target_ce, dt_min, n_substeps = 10) {
  # Effect-site targeting via peak concentration targeting
  find_peak_ce <- function(s, rate) {
    s <- simulate_step(s, params, rate, dt_min, n_substeps)
    pk <- s[4]
    prev <- s[4]
    for (i in 1:80) {
      s <- simulate_step(s, params, 0, dt_min, n_substeps)
      if (s[4] > pk) pk <- s[4]
      if (s[4] < prev - 1e-8 && prev <= pk + 1e-8) break
      prev <- s[4]
    }
    pk
  }

  pk0 <- find_peak_ce(state, 0)
  if (pk0 >= target_ce) return(0)

  test_rate <- 100
  pkt <- find_peak_ce(state, test_rate)
  if (abs(pkt - pk0) < 1e-12) return(0)

  r_est <- test_rate * (target_ce - pk0) / (pkt - pk0)
  lo <- max(r_est * 0.3, 0)
  hi <- r_est * 2.0 + 1.0

  pk_hi <- find_peak_ce(state, hi)
  while (pk_hi < target_ce && hi < 50000) {
    hi <- hi * 2
    pk_hi <- find_peak_ce(state, hi)
  }

  for (i in 1:15) {
    mid <- (lo + hi) / 2
    pk <- find_peak_ce(state, mid)
    if (pk < target_ce) {
      lo <- mid
    } else {
      hi <- mid
    }
  }

  max((lo + hi) / 2, 0)
}"""

assert old_tci in code, "Could not find TCI effect rate stub to replace"
code = code.replace(old_tci, new_tci)

with open("/app/pk_simulator.R", "w") as f:
    f.write(code)

print("All 5 fixes applied successfully to /app/pk_simulator.R")
