
# Data transformation and cleaning utilities for clinical trial pipeline

clean_concentrations <- function(data) {
  # Convert concentration to numeric; non-numeric entries should become NA
  conc_values <- as.numeric(data$concentration)
  return(conc_values)
}

count_quality <- function(data) {
  # Count complete vs missing measurement values
  n_complete <- sum(data$measurement != NA)
  n_missing <- sum(data$measurement == NA)
  return(list(n_complete = n_complete, n_missing = n_missing))
}

make_normalizers <- function(sites, baselines_by_site) {
  # Create per-site normalization functions that divide by site mean baseline
  normalizers <- list()
  for (i in seq_along(sites)) {
    normalizers[[i]] <- function(x) x / baselines_by_site[i]
  }
  return(normalizers)
}

find_reference_baselines <- function(data, sites, reference = 20.0) {
  # For each site, find the baseline value closest to the reference
  ref_baselines <- numeric(length(sites))
  for (j in seq_along(sites)) {
    site_baselines <- data$baseline[data$site == sites[j]]
    ref_baselines[j] <- which.min(abs(site_baselines - reference))
  }
  return(ref_baselines)
}
