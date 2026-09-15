# SA-CCR Add-on Functions (BCBS 279) - CORRECTED VERSION
# Returns list(total, detail) from each add-on function
# for per-hedging-set / per-entity output.


# ============================================================
# Interest Rate Add-on (BCBS 279, para 166-169)
# Added mf_override parameter for margined trades.
# Returns list(total, detail) where detail maps currency to
# hedging-set-level add-on.
# ============================================================
addon_ir <- function(trades, mf_override = NULL) {
  currencies <- unique(trades$currency)
  total <- 0
  detail <- list()

  for (ccy in currencies) {
    ct <- trades[trades$currency == ccy, ]
    D <- c(0, 0, 0)

    for (i in 1:nrow(ct)) {
      tr <- ct[i, ]
      sd_val <- supervisory_duration(tr$si, tr$ei)
      adj_not <- tr$notional * sd_val

      if (!is.null(mf_override)) {
        mf <- mf_override
      } else {
        mf <- maturity_factor(tr$ei)
      }

      delta <- calc_delta(tr$buy_sell, tr$option_type,
                          tr$underlying_price, tr$strike_price,
                          tr$exercise_date, 0.50)

      eff <- delta * adj_not * mf
      bucket <- if (tr$ei <= 1) 1 else if (tr$ei <= 5) 2 else 3
      D[bucket] <- D[bucket] + eff
    }

    eff_not <- sqrt(D[1]^2 + D[2]^2 + D[3]^2 +
                     1.4 * D[1] * D[2] +
                     1.4 * D[2] * D[3] +
                     0.6 * D[1] * D[3])

    hs_addon <- 0.005 * eff_not
    detail[[ccy]] <- round(hs_addon)
    total <- total + hs_addon
  }
  list(total = total, detail = detail)
}

# ============================================================
# Credit Add-on (BCBS 279, para 172-173)
# FIX: Replaced flat absolute-value summation with the
# single-factor model (systematic/idiosyncratic decomposition).
# Entity-level addons are signed, not absolute.
# Systematic: (sum(addon_k * rho_k))^2
# Idiosyncratic: sum((1 - rho_k^2) * addon_k^2)
# Returns list(total, detail) where detail maps entity to
# signed entity-level add-on.
# ============================================================
addon_credit <- function(trades, mf_override = NULL) {
  entities <- unique(trades$ref_entity)
  n <- length(entities)
  ent_addons <- numeric(n)
  ent_corrs <- numeric(n)
  detail <- list()

  for (j in seq_along(entities)) {
    et <- trades[trades$ref_entity == entities[j], ]
    eff <- 0

    for (i in 1:nrow(et)) {
      tr <- et[i, ]
      sd_val <- supervisory_duration(tr$si, tr$ei)
      adj_not <- tr$notional * sd_val
      delta <- calc_delta(tr$buy_sell, tr$option_type)

      if (!is.null(mf_override)) {
        mf <- mf_override
      } else {
        mf <- maturity_factor(tr$ei)
      }
      eff <- eff + delta * adj_not * mf
    }

    sf <- get_credit_sf(tr$asset_subclass, tr$subclass)
    ent_addons[j] <- eff * sf
    ent_corrs[j] <- get_credit_corr(tr$asset_subclass)
    detail[[entities[j]]] <- round(eff * sf)
  }

  # Single-factor model decomposition
  systematic <- (sum(ent_addons * ent_corrs))^2
  idiosyncratic <- sum((1 - ent_corrs^2) * ent_addons^2)

  total <- sqrt(systematic + idiosyncratic)
  list(total = total, detail = detail)
}

# ============================================================
# Commodity Add-on (BCBS 279, para 178-179)
# FIX: SF lookup by commodity type, not hedging set name.
#      Electricity = 40%, all others = 18%.
# FIX: idiosyncratic component uses (1 - rho^2), not (1 - rho).
# Added mf_override parameter for margined trades.
# Returns list(total, detail) where detail maps hedging set
# name to its add-on.
# ============================================================
addon_commodity <- function(trades, mf_override = NULL) {
  hedging_sets <- unique(trades$commodity_hedging_set)
  total <- 0
  detail <- list()

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

        if (!is.null(mf_override)) {
          mf <- mf_override
        } else {
          mf <- maturity_factor(tr$ei)
        }
        eff <- eff + delta * tr$notional * mf
      }

      # FIX: SF by commodity type, not hedging set
      sf <- ifelse(com_types[k] == "Electricity", 0.40, 0.18)
      type_addons[k] <- abs(eff) * sf
    }

    rho <- 0.40
    sys <- (rho * sum(type_addons))^2
    # FIX: (1 - rho^2), not (1 - rho)
    idio <- (1 - rho^2) * sum(type_addons^2)

    hs_addon <- sqrt(sys + idio)
    detail[[hs]] <- round(hs_addon)
    total <- total + hs_addon
  }
  list(total = total, detail = detail)
}
