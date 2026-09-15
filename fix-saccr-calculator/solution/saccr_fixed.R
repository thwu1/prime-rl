# SA-CCR Calculator (BCBS 279) - CORRECTED VERSION
# Full margined-trade pipeline implemented.
# Per-hedging-set / per-entity detail output added.

source("/app/core.R")
source("/app/addons.R")


# ============================================================
# EAD Calculation (BCBS 279, para 128)
# FIX: Full margined-trade pipeline:
#   - Read margin file
#   - Compute MPOR from re-margining frequency
#   - Compute margined maturity factor
#   - Compute margined replacement cost with TH, MTA, NICA
#   - Thread mf_override to all add-on functions
# ============================================================
calc_ead <- function(trades_file, margin_file = NULL) {
  trades <- read.csv(trades_file, stringsAsFactors = FALSE)
  V <- sum(trades$mtm)

  ir_tr <- trades[trades$asset_class == "IRD", ]
  cr_tr <- trades[trades$asset_class == "Credit", ]
  co_tr <- trades[trades$asset_class == "Commodity", ]

  mf_val <- NULL

  if (!is.null(margin_file)) {
    mg <- read.csv(margin_file, stringsAsFactors = FALSE)
    mpor <- calc_mpor(mg$margin_freq_days[1])
    mf_val <- maturity_factor(margined = TRUE, MPOR = mpor)
    rc <- replacement_cost(V, mg$net_collateral[1], TRUE,
                           mg$threshold[1], mg$mta[1], mg$nica[1])
  } else {
    rc <- replacement_cost(V)
  }

  ir_result <- list(total = 0, detail = list())
  cr_result <- list(total = 0, detail = list())
  co_result <- list(total = 0, detail = list())

  if (nrow(ir_tr) > 0) ir_result <- addon_ir(ir_tr, mf_val)
  if (nrow(cr_tr) > 0) cr_result <- addon_credit(cr_tr, mf_val)
  if (nrow(co_tr) > 0) co_result <- addon_commodity(co_tr, mf_val)

  addon_agg <- ir_result$total + cr_result$total + co_result$total

  mult <- calc_multiplier(rc$V_C, addon_agg)
  PFE <- mult * addon_agg
  EAD <- 1.4 * (rc$RC + PFE)

  result <- list(
    EAD = round(EAD),
    RC = round(rc$RC, 2),
    V_C = round(rc$V_C, 2),
    addon_aggregate = round(addon_agg, 2),
    multiplier = round(mult, 4),
    PFE = round(PFE, 2)
  )

  if (ir_result$total > 0) {
    result$addon_ir <- round(ir_result$total, 2)
    result$ir_detail <- ir_result$detail
  }
  if (cr_result$total > 0) {
    result$addon_credit <- round(cr_result$total, 2)
    result$credit_detail <- cr_result$detail
  }
  if (co_result$total > 0) {
    result$addon_commodity <- round(co_result$total, 2)
    result$commodity_detail <- co_result$detail
  }

  result
}

# ============================================================
# Run All BCBS 279 Annex 4a Examples
# ============================================================
run_all <- function() {
  results <- list()
  results$example1 <- calc_ead("/app/data/trades_ex1.csv")
  results$example2 <- calc_ead("/app/data/trades_ex2.csv")
  results$example3 <- calc_ead("/app/data/trades_ex3.csv")
  results$example4 <- calc_ead("/app/data/trades_ex4.csv")
  results$example5 <- calc_ead("/app/data/trades_ex5.csv", "/app/data/margin_ex5.csv")

  output <- toJSON(results, auto_unbox = TRUE, pretty = TRUE)
  writeLines(output, "/app/results.json")
  cat(output, "\n")
  invisible(results)
}

if (!interactive()) {
  run_all()
}
