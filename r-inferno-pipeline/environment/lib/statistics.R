
# Statistical computation functions for clinical trial pipeline

find_weight <- function(target = 0.3) {
  # Retrieve the target weight from a generated sequence
  weight_seq <- seq(0, 1, by = 0.1)
  w <- weight_seq[weight_seq == target]
  if (length(w) == 0) w <- 0
  return(w)
}

compute_overall_mean <- function(effects) {
  # Compute simple average of per-site treatment effects
  result <- mean(effects[1], effects[2], effects[3])
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
  # Compute SE and 95% CI per site from stat matrix
  derived <- apply(stat_mat, 1, function(row) {
    m <- row[1]; s <- row[2]; n <- row[3]
    se <- s / sqrt(n)
    c(se = se, ci_lower = m - 1.96 * se, ci_upper = m + 1.96 * se)
  })
  return(derived)
}
