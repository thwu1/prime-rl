# SA-CCR Add-on Functions (BCBS 279)
# Per-asset-class PFE add-on calculations:
#   Interest Rate, Credit, Commodity


# ============================================================
# Interest Rate Add-on (BCBS 279, para 166-169)
# Hedging sets by currency, maturity buckets <1y, 1-5y, >5y
# Cross-bucket aggregation with correlations
# ============================================================
addon_ir <- function(trades) {
  currencies <- unique(trades$currency)
  total <- 0

  for (ccy in currencies) {
    ct <- trades[trades$currency == ccy, ]
    D <- c(0, 0, 0)  # maturity buckets: <1y, 1-5y, >5y

    for (i in 1:nrow(ct)) {
      tr <- ct[i, ]
      sd_val <- supervisory_duration(tr$si, tr$ei)
      adj_not <- tr$notional * sd_val
      mf <- maturity_factor(tr$ei)

      delta <- calc_delta(tr$buy_sell, tr$option_type,
                          tr$underlying_price, tr$strike_price,
                          tr$exercise_date, 0.50)

      eff <- delta * adj_not * mf
      bucket <- if (tr$ei <= 1) 1 else if (tr$ei <= 5) 2 else 3
      D[bucket] <- D[bucket] + eff
    }

    # Cross-maturity-bucket aggregation (para 169)
    eff_not <- sqrt(D[1]^2 + D[2]^2 + D[3]^2 +
                     1.4 * D[1] * D[2] +
                     1.4 * D[2] * D[3] +
                     0.6 * D[1] * D[3])

    total <- total + 0.005 * eff_not  # SF_IR = 0.5%
  }
  total
}

# ============================================================
# Credit Add-on (BCBS 279, para 172-173)
# Entity-level aggregation: each entity's effective notional
# times supervisory factor, summed across entities
# ============================================================
addon_credit <- function(trades) {
  entities <- unique(trades$ref_entity)
  total <- 0

  for (entity in entities) {
    et <- trades[trades$ref_entity == entity, ]
    eff <- 0

    for (i in 1:nrow(et)) {
      tr <- et[i, ]
      sd_val <- supervisory_duration(tr$si, tr$ei)
      adj_not <- tr$notional * sd_val
      delta <- calc_delta(tr$buy_sell, tr$option_type)
      mf <- maturity_factor(tr$ei)
      eff <- eff + delta * adj_not * mf
    }

    sf <- get_credit_sf(tr$asset_subclass, tr$subclass)
    total <- total + abs(eff * sf)
  }
  total
}

# ============================================================
# Commodity Add-on (BCBS 279, para 178-179)
# Four hedging sets (energy, metals, agricultural, other)
# Within each: single-factor model by commodity type
# ============================================================
addon_commodity <- function(trades) {
  hedging_sets <- unique(trades$commodity_hedging_set)
  total <- 0

  for (hs in hedging_sets) {
    hs_tr <- trades[trades$commodity_hedging_set == hs, ]
    com_types <- unique(hs_tr$commodity_type)
    type_addons <- numeric(length(com_types))

    for (k in seq_along(com_types)) {
      ct_tr <- hs_tr[hs_tr$commodity_type == com_types[k], ]
      eff <- 0

      for (i in 1:nrow(ct_tr)) {
        tr <- ct_tr[i, ]
        delta <- calc_delta(tr$buy_sell, tr$option_type)
        mf <- maturity_factor(tr$ei)
        eff <- eff + delta * tr$notional * mf
      }

      sf <- ifelse(hs == "Energy", 0.40, 0.18)
      type_addons[k] <- abs(eff) * sf
    }

    # Single-factor model aggregation within hedging set
    rho <- 0.40
    sys <- (rho * sum(type_addons))^2
    idio <- (1 - rho) * sum(type_addons^2)

    total <- total + sqrt(sys + idio)
  }
  total
}
