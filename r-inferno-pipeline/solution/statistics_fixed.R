
# Statistical computation functions for clinical trial pipeline

find_weight <- function(target = 0.3) {
  # Fix 5: floating-point comparison (R Inferno Circle 1)
  weight_seq <- seq(0, 1, by = 0.1)
  w <- weight_seq[which.min(abs(weight_seq - target))]
  if (length(w) == 0) w <- 0
  return(w)
}

compute_overall_mean <- function(effects) {
  # Fix 6: mean(a, b, c) treats b as trim - use c() (R Inferno mean trap)
  result <- mean(c(effects[1], effects[2], effects[3]))
  return(result)
}

build_stat_matrix <- function(data, sites) {
  # Build matrix of per-site statistics: mean, sd, n
  stat_mat <- matrix(NA, nrow = length(sites), ncol = 3)
  for (j in seq_along(sites)) {
    vals <- data$measurement[data$site == sites[j] &
                             !is.na(data$measurement)]
    stat_mat[j, ] <- c(mean(vals), sd(vals), length(vals))
  }
  return(stat_mat)
}

compute_ci_matrix <- function(stat_mat) {
  # Fix 7: apply() returns columns per input row - need t() (R Inferno 8.1.47)
  derived <- apply(stat_mat, 1, function(row) {
    m <- row[1]; s <- row[2]; n <- row[3]
    se <- s / sqrt(n)
    c(se = se, ci_lower = m - 1.96 * se, ci_upper = m + 1.96 * se)
  })
  return(t(derived))
}
