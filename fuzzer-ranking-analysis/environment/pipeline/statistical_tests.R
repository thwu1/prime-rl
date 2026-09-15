#!/usr/bin/env Rscript
# Statistical tests for FuzzBench experiment analysis
# Performs Friedman omnibus test and Nemenyi post-hoc comparisons

library(jsonlite)

data <- read.csv("/app/pipeline/tmp/final_coverage.csv")

fuzzers <- sort(unique(data$fuzzer))
benchmarks <- sort(unique(data$benchmark))
k <- length(fuzzers)
n_bench <- length(benchmarks)

# Compute median final coverage per fuzzer/benchmark
med_agg <- aggregate(final_edges ~ fuzzer + benchmark, data, median)

# Build matrix: rows=benchmarks (blocks), cols=fuzzers (treatments)
med_matrix <- matrix(NA, nrow = n_bench, ncol = k,
                     dimnames = list(benchmarks, fuzzers))
for (i in 1:nrow(med_agg)) {
    med_matrix[med_agg$benchmark[i], med_agg$fuzzer[i]] <- med_agg$final_edges[i]
}

# Friedman omnibus test
friedman_result <- friedman.test(med_matrix)
friedman_stat <- as.numeric(friedman_result$statistic)
friedman_p <- as.numeric(friedman_result$p.value)

# Average ranks across benchmarks
# rank() gives ascending ranks: 1 = lowest value
rank_matrix <- t(apply(med_matrix, 1, rank))
avg_ranks <- colMeans(rank_matrix)

# Nemenyi post-hoc pairwise comparisons
# Standard error for rank differences
se <- sqrt(k * (k + 1) / (12.0 * k))

pairwise_p <- list()
for (i in 1:(k - 1)) {
    for (j in (i + 1):k) {
        fi <- fuzzers[i]
        fj <- fuzzers[j]
        pair <- sort(c(fi, fj))
        key <- paste0(pair[1], "_vs_", pair[2])
        diff_val <- abs(avg_ranks[fi] - avg_ranks[fj])
        q_stat <- diff_val / se
        p_val <- 1.0 - ptukey(q_stat, k, 1e6)
        pairwise_p[[key]] <- round(p_val, 6)
    }
}

# Critical difference at alpha = 0.05
q_alpha <- qtukey(0.95, k, 1e6)
cd <- q_alpha * se

# Build output structures
med_cov_out <- list()
for (b in benchmarks) {
    brow <- list()
    for (f in fuzzers) {
        brow[[f]] <- med_matrix[b, f]
    }
    med_cov_out[[b]] <- brow
}

avg_ranks_out <- list()
for (f in fuzzers) {
    avg_ranks_out[[f]] <- round(as.numeric(avg_ranks[f]), 4)
}

output <- list(
    median_final_coverage = med_cov_out,
    overall_test_statistic = round(friedman_stat, 6),
    overall_test_p_value = friedman_p,
    average_ranks = avg_ranks_out,
    pairwise_p_values = pairwise_p,
    critical_difference = round(cd, 6)
)

write_json(output, "/app/pipeline/tmp/stats_output.json",
           auto_unbox = TRUE, pretty = TRUE)
cat("Statistical tests complete.\n")
