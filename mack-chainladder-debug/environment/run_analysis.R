#!/usr/bin/env Rscript

source("/app/reserving.R")

cat("=== Actuarial Reserving Pipeline ===\n\n")

# Analysis 1: Mack Chain Ladder on RAA (default parameters: est.sigma="log-linear")
cat("Running MackChainLadder on RAA...\n")
mack_raa <- MackChainLadder(RAA)
raa_total_se <- as.numeric(mack_raa$Total.Mack.S.E)
cat(sprintf("  Total Mack S.E.: %.4f\n", raa_total_se))

# Analysis 2: Mack Chain Ladder on GenIns (est.sigma="Mack")
cat("Running MackChainLadder on GenIns (est.sigma='Mack')...\n")
mack_genins <- MackChainLadder(GenIns, est.sigma = "Mack")

cat("Computing Cornish-Fisher quantiles...\n")
q <- quantile_mack(mack_genins, probs = 0.65)
genins_skewness <- round(q$ByOrigin$Skewness, 3)
genins_overall_skew <- round(q$Totals$Totals[1], 3)

cat(sprintf("  Per-origin skewness: %s\n",
            paste(genins_skewness, collapse = ", ")))
cat(sprintf("  Overall skewness: %.3f\n", genins_overall_skew))

# Write results as JSON
json_lines <- c(
  "{",
  sprintf('  "raa_total_mack_se": %.2f,', round(raa_total_se, 2)),
  sprintf('  "genins_skewness": [%s],',
          paste(sprintf("%.3f", genins_skewness), collapse = ", ")),
  sprintf('  "genins_overall_skewness": %.3f', genins_overall_skew),
  "}"
)
writeLines(json_lines, "/app/results.json")

cat("\nResults written to /app/results.json\n")
