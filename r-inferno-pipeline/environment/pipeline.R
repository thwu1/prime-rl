#!/usr/bin/env Rscript


# Clinical Trial Data Processing Pipeline
# Multi-file analysis system for multi-site measurement data.

library(jsonlite)

source("/app/lib/transforms.R")
source("/app/lib/statistics.R")
source("/app/lib/robust.R")

data <- read.csv("/app/data/measurements.csv", stringsAsFactors = TRUE)
dir.create("/app/output", showWarnings = FALSE, recursive = TRUE)

results <- list()

# --- Section 1: Concentration Analysis ---
conc_values <- clean_concentrations(data)
valid_conc <- conc_values[!is.na(conc_values)]
results$concentration <- list(
  mean_concentration = round(mean(valid_conc), 6),
  median_concentration = round(median(valid_conc), 6),
  n_valid = length(valid_conc)
)

# --- Section 2: Data Quality Report ---
quality <- count_quality(data)
results$quality <- list(
  n_complete = quality$n_complete,
  n_missing = quality$n_missing,
  completeness_pct = round(quality$n_complete / nrow(data) * 100, 2)
)

# --- Section 3: Treatment Comparison ---
trial_rows <- data[data$treatment == c("drug", "placebo"), ]
drug_mean <- mean(trial_rows$measurement[trial_rows$treatment == "drug"],
                  na.rm = TRUE)
placebo_mean <- mean(trial_rows$measurement[trial_rows$treatment == "placebo"],
                     na.rm = TRUE)
results$treatment <- list(
  drug_mean = round(drug_mean, 6),
  placebo_mean = round(placebo_mean, 6),
  effect_size = round(drug_mean - placebo_mean, 6),
  n_analyzed = nrow(trial_rows)
)

# --- Section 4: Site-Weighted Effect ---
sites <- levels(data$site)
site_effects <- numeric(length(sites))
site_sizes <- numeric(length(sites))

for (j in seq_along(sites)) {
  s <- sites[j]
  site_data <- data[data$site == s & !is.na(data$measurement), ]
  d_mean <- mean(site_data$measurement[site_data$treatment == "drug"])
  p_mean <- mean(site_data$measurement[site_data$treatment == "placebo"])
  site_effects[j] <- d_mean - p_mean
  site_sizes[j] <- nrow(site_data)
}

target_weight <- find_weight(0.3)
overall_effect <- compute_overall_mean(site_effects)

results$weighted_effect <- list(
  site_effects = setNames(as.list(round(site_effects, 6)), sites),
  site_sample_sizes = setNames(as.list(as.integer(site_sizes)), sites),
  overall_weighted_effect = round(overall_effect, 6),
  weight_used = target_weight
)

# --- Section 5: Normalization ---
site_baselines <- tapply(data$baseline, data$site, mean)
normalizers <- make_normalizers(sites, site_baselines)

norm_values <- numeric(length(sites))
for (j in seq_along(sites)) {
  site_meas <- data$measurement[data$site == sites[j] &
                                !is.na(data$measurement)]
  site_mean_meas <- mean(site_meas)
  norm_values[j] <- normalizers[[j]](site_mean_meas)
}

results$normalization <- list(
  normalized_site_means = setNames(as.list(round(norm_values, 6)), sites)
)

# --- Section 6: Confidence Intervals ---
stat_mat <- build_stat_matrix(data, sites)
derived <- compute_ci_matrix(stat_mat)

results$confidence_intervals <- list()
for (j in seq_along(sites)) {
  results$confidence_intervals[[sites[j]]] <- list(
    se = round(derived[j, 1], 6),
    ci_lower = round(derived[j, 2], 6),
    ci_upper = round(derived[j, 3], 6)
  )
}

# --- Section 7: Outlier Capping ---
results$outlier_analysis <- list()
for (s in sites) {
  site_meas <- data$measurement[data$site == s & !is.na(data$measurement)]
  cap <- mean(site_meas) + 2 * sd(site_meas)
  capped <- min(site_meas, cap)
  results$outlier_analysis[[s]] <- list(
    capped_mean = round(mean(capped), 6),
    n_capped = as.integer(sum(site_meas > cap))
  )
}

# --- Section 8: Robust Location Estimates ---
huber_results <- huber_site_means(data, sites, k = 1.345)
results$robust_means <- setNames(
  lapply(seq_along(sites), function(j) {
    list(
      huber_mean = round(huber_results$estimates[j], 6),
      iterations = as.integer(huber_results$iterations[j])
    )
  }),
  sites
)

# --- Section 9: Hodges-Lehmann Treatment Effects ---
hl_effects <- hodges_lehmann_effects(data, sites)
results$hodges_lehmann <- setNames(
  as.list(round(hl_effects, 6)),
  sites
)

# --- Section 10: Cross-Validation Summary ---
ref_baselines <- find_reference_baselines(data, sites)
results$summary <- list(
  mean_normalized = round(mean(norm_values), 6),
  weighted_treatment_effect = round(overall_effect * target_weight, 6),
  quality_adjusted_n = as.integer(quality$n_complete),
  reference_baselines = setNames(as.list(round(ref_baselines, 6)), sites),
  mean_huber_estimate = round(mean(huber_results$estimates), 6),
  median_hl_effect = round(median(hl_effects), 6)
)

# Write results
writeLines(toJSON(results, auto_unbox = TRUE, pretty = TRUE),
           "/app/output/results.json")
cat("Pipeline completed. Results written to /app/output/results.json\n")
