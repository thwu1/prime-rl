# SA-CCR Core Functions (BCBS 279)
# Supervisory parameters, delta adjustments, maturity factors,
# replacement cost, multiplier, and credit supervisory lookups

library(jsonlite)


# ============================================================
# Supervisory Duration (BCBS 279, para 157)
# SD_i = (exp(-0.05*S_i) - exp(-0.05*E_i)) / 0.05
# ============================================================
supervisory_duration <- function(S, E) {
  (exp(-0.05 * S) - exp(-0.05 * E)) / 0.05
}

# ============================================================
# Supervisory Delta (BCBS 279, para 159)
# Non-options: +1 (long) or -1 (short)
# Options: Black-Scholes d1, applied to standard normal CDF
# Bought call: +Phi(d1)  Sold call: -Phi(d1)
# Bought put: -Phi(-d1)  Sold put: +Phi(-d1)
# ============================================================
calc_delta <- function(buy_sell, option_type, P = NA, K = NA,
                       T_opt = NA, sigma = NA) {
  is_option <- !is.na(option_type) && nchar(option_type) > 0

  if (!is_option) {
    return(ifelse(buy_sell == "Buy", 1, -1))
  }

  d1 <- (log(P / K) + 0.5 * sigma^2 * T_opt) / (sigma * sqrt(T_opt))

  sign_mult <- ifelse(
    (buy_sell == "Buy" && option_type == "call") ||
    (buy_sell == "Sell" && option_type == "put"),
    1, -1
  )

  return(sign_mult * pnorm(d1))
}

# ============================================================
# Maturity Factor (BCBS 279, para 164)
# Unmargined: MF = sqrt(min(M_i, 1)) where M_i floored at
#             10 business days (10/250 years)
# ============================================================
maturity_factor <- function(remaining_maturity) {
  M <- max(remaining_maturity, 10 / 250)
  sqrt(min(M, 1))
}

# ============================================================
# Replacement Cost (BCBS 279, para 136)
# Unmargined: RC = max(V - C, 0)
# ============================================================
replacement_cost <- function(V, C = 0) {
  V_C <- V - C
  RC <- max(V_C, 0)
  list(V_C = V_C, RC = RC)
}

# ============================================================
# Multiplier (BCBS 279, para 149)
# multiplier = min(1, floor + (1-floor) * exp(V_C / (2*(1-floor)*AddOn)))
# floor = 0.05
# ============================================================
calc_multiplier <- function(V_C, addon_agg) {
  if (V_C >= 0 || addon_agg == 0) return(1)
  min(1, 0.05 + 0.95 * exp(V_C / (2.0 * addon_agg)))
}

# ============================================================
# Credit Supervisory Factors (BCBS 279, Table 2)
# ============================================================
get_credit_sf <- function(asset_subclass, subclass) {
  if (asset_subclass == "CreditIndex") {
    return(switch(subclass, "IG" = 0.0038, "SG" = 0.0106, 0.0038))
  }
  switch(subclass,
    "AAA" = 0.0038, "AA" = 0.0038, "A" = 0.0042,
    "BBB" = 0.0054, "BB" = 0.0106, "B" = 0.016,
    "CCC" = 0.06, 0.0054)
}

# ============================================================
# Credit Correlation Parameters (BCBS 279, Table 2)
# Single name: rho = 0.50, Index: rho = 0.80
# ============================================================
get_credit_corr <- function(asset_subclass) {
  ifelse(asset_subclass == "CreditIndex", 0.80, 0.50)
}
