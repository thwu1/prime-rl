
# Robust statistical functions for clinical trial pipeline

huber_site_means <- function(data, sites, k = 1.345, tol = 1e-6, max_iter = 100L) {
  n_sites <- length(sites)
  estimates <- numeric(n_sites)
  iters_out <- integer(n_sites)

  meas_vec <- suppressWarnings(as.numeric(as.character(data$measurement)))
  site_vec <- as.character(data$site)

  for (j in seq_len(n_sites)) {
    ok <- site_vec == sites[j] & !is.na(meas_vec)
    vals <- meas_vec[ok]
    n <- length(vals)

    mu <- median(vals)

    abs_devs <- abs(vals - mu)
    mad_s <- median(abs_devs) * 1.4826

    if (mad_s < .Machine$double.eps) {
      estimates[j] <- mu
      iters_out[j] <- 0L
      next
    }

    n_iter <- max_iter
    for (it in seq_len(max_iter)) {
      r <- (vals - mu) / mad_s
      w <- ifelse(abs(r) <= k, 1.0, k / abs(r))
      mu_new <- sum(w * vals) / sum(w)
      if (abs(mu_new - mu) < tol) {
        n_iter <- it
        mu <- mu_new
        break
      }
      mu <- mu_new
    }
    estimates[j] <- mu
    iters_out[j] <- as.integer(n_iter)
  }

  list(estimates = estimates, iterations = as.integer(iters_out))
}

hodges_lehmann_effects <- function(data, sites) {
  n_sites <- length(sites)
  hl <- numeric(n_sites)

  meas_vec <- suppressWarnings(as.numeric(as.character(data$measurement)))
  site_vec <- as.character(data$site)
  treat_vec <- as.character(data$treatment)

  for (j in seq_len(n_sites)) {
    ok <- site_vec == sites[j] & !is.na(meas_vec)
    drug_vals <- meas_vec[ok & treat_vec == "drug"]
    plac_vals <- meas_vec[ok & treat_vec == "placebo"]

    diffs <- sort(as.vector(outer(drug_vals, plac_vals, FUN = function(a, b) a - b)))
    hl[j] <- median(diffs)
  }

  hl
}
