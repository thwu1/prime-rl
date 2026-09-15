# SA-CCR Calculator (BCBS 279)
# Standardised Approach for Counterparty Credit Risk
# Computes Exposure at Default (EAD) for derivative netting sets
#
# EAD = alpha * (RC + PFE)
# alpha = 1.4
# PFE = multiplier * AddOn_aggregate

source("/app/core.R")
source("/app/addons.R")


# ============================================================
# EAD Calculation (BCBS 279, para 128)
# EAD = 1.4 * (RC + PFE)
# ============================================================
calc_ead <- function(trades_file, margin_file = NULL) {
  trades <- read.csv(trades_file, stringsAsFactors = FALSE)
  V <- sum(trades$mtm)

  rc <- replacement_cost(V)

  ir_tr <- trades[trades$asset_class == "IRD", ]
  cr_tr <- trades[trades$asset_class == "Credit", ]
  co_tr <- trades[trades$asset_class == "Commodity", ]

  addon_ir_val <- 0
  addon_credit_val <- 0
  addon_commodity_val <- 0

  if (nrow(ir_tr) > 0) addon_ir_val <- addon_ir(ir_tr)
  if (nrow(cr_tr) > 0) addon_credit_val <- addon_credit(cr_tr)
  if (nrow(co_tr) > 0) addon_commodity_val <- addon_commodity(co_tr)

  addon_agg <- addon_ir_val + addon_credit_val + addon_commodity_val

  mult <- calc_multiplier(rc$V_C, addon_agg)
  PFE <- mult * addon_agg
  EAD <- 1.4 * (rc$RC + PFE)

  result <- list(
    V = V, RC = rc$RC, V_C = rc$V_C,
    addon_aggregate = round(addon_agg, 2),
    multiplier = round(mult, 4),
    PFE = round(PFE, 2),
    EAD = round(EAD)
  )

  if (addon_ir_val > 0) result$addon_ir <- round(addon_ir_val, 2)
  if (addon_credit_val > 0) result$addon_credit <- round(addon_credit_val, 2)
  if (addon_commodity_val > 0) result$addon_commodity <- round(addon_commodity_val, 2)

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
