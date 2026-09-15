
# Data transformation and cleaning utilities for clinical trial pipeline

clean_concentrations <- function(data) {
  # Fix 1: as.character() prevents factor-level coercion (R Inferno 8.2.1)
  conc_values <- as.numeric(as.character(data$concentration))
  return(conc_values)
}

count_quality <- function(data) {
  # Fix 2: is.na() instead of == NA / != NA (R Inferno 8.1.4)
  n_complete <- sum(!is.na(data$measurement))
  n_missing <- sum(is.na(data$measurement))
  return(list(n_complete = n_complete, n_missing = n_missing))
}

make_normalizers <- function(sites, baselines_by_site) {
  # Fix 3: lapply+force prevents lazy evaluation variable capture (R Inferno 8.3.16)
  normalizers <- lapply(seq_along(sites), function(i) {
    force(i)
    function(x) x / baselines_by_site[i]
  })
  return(normalizers)
}

find_reference_baselines <- function(data, sites, reference = 20.0) {
  # Fix 4: which.min returns INDEX, we need the VALUE
  ref_baselines <- numeric(length(sites))
  for (j in seq_along(sites)) {
    site_baselines <- data$baseline[data$site == sites[j]]
    ref_baselines[j] <- site_baselines[which.min(abs(site_baselines - reference))]
  }
  return(ref_baselines)
}
