#!/usr/bin/env Rscript

args <- commandArgs(trailingOnly = TRUE)

if (length(args) != 2) {
  cat("Usage: Rscript run_batch.R <input.csv> <output.csv>\n")
  quit(status = 1)
}

input_file <- args[1]
output_file <- args[2]

source("/app/R/compute_all.R")

df <- read.csv(input_file, stringsAsFactors = FALSE)
result <- compute_all_risks(df)
write.csv(result, output_file, row.names = FALSE)

cat("Results written to", output_file, "\n")
