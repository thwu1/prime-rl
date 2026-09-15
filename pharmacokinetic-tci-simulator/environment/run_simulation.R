#!/usr/bin/env Rscript

source("/app/pk_simulator.R")
library(jsonlite)

scenarios <- fromJSON("/app/scenarios.json", simplifyVector = FALSE)$scenarios

all_results <- data.frame()
for (sc in scenarios) {
  cat(sprintf("Running scenario %d: %s model\n", sc$id, sc$model))
  res <- run_scenario(sc)
  all_results <- rbind(all_results, res)
}

write.csv(all_results, "/app/results.csv", row.names = FALSE)
cat("Results written to /app/results.csv\n")
