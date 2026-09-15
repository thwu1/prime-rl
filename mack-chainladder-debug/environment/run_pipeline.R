#
# Actuarial Reserving Pipeline
# Runs Mack Chain Ladder and Munich Chain Ladder methods

source("/app/reserving.R")
source("/app/munich.R")

cat("=== Part 1: Mack Chain Ladder on RAA ===\n")
result_mack <- MackChainLadder(RAA)
raa_total_mack_se <- as.numeric(result_mack$Total.Mack.S.E)
cat(sprintf("RAA Total Mack S.E.: %.2f\n", raa_total_mack_se))

cat("\n=== Part 2: Mack + Cornish-Fisher Skewness on GenIns ===\n")
result_genins <- MackChainLadder(GenIns, est.sigma = "Mack")
q <- quantile_mack(result_genins, 0.65)
genins_skewness <- q$ByOrigin$Skewness
genins_overall_skewness <- q$Totals$Totals[1]
cat(sprintf("GenIns Per-origin skewness: %s\n",
            paste(sprintf("%.4f", genins_skewness), collapse = ", ")))
cat(sprintf("GenIns Overall Skewness: %.4f\n", genins_overall_skewness))

cat("\n=== Part 3: Munich Chain Ladder ===\n")
LDFweights <- build_ldf_weights(MCLpaid)
mcl <- MunichChainLadder(
  Paid = MCLpaid,
  Incurred = MCLincurred,
  tailP = 1.05,
  tailI = 1,
  est.sigmaP = "Mack",
  est.sigmaI = "Mack",
  weights = LDFweights
)
mcl_summary <- summary_mcl(mcl)
mcl_paid_ult <- as.numeric(mcl_summary$Totals[2, "Paid"])
mcl_incurred_ult <- as.numeric(mcl_summary$Totals[2, "Incurred"])
cat(sprintf("MCL Paid Ultimate Total: %.2f\n", mcl_paid_ult))
cat(sprintf("MCL Incurred Ultimate Total: %.2f\n", mcl_incurred_ult))

# ---- Write results as JSON ----
to_json_array <- function(x) {
  paste0("[", paste(sprintf("%.10g", x), collapse = ", "), "]")
}

json <- paste0(
  '{\n',
  '  "raa_total_mack_se": ', sprintf("%.10g", raa_total_mack_se), ',\n',
  '  "genins_skewness": ', to_json_array(genins_skewness), ',\n',
  '  "genins_overall_skewness": ', sprintf("%.10g", genins_overall_skewness), ',\n',
  '  "mcl_paid_ultimate": ', sprintf("%.10g", mcl_paid_ult), ',\n',
  '  "mcl_incurred_ultimate": ', sprintf("%.10g", mcl_incurred_ult), '\n',
  '}\n'
)
writeLines(json, "/app/results.json")
cat("\nResults written to /app/results.json\n")
