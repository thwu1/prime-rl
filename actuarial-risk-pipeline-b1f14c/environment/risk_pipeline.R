
#######################################################################
# Actuarial Risk Computation Pipeline
# Implements: discretization, Panjer recursion, VaR, CTE, Beekman ruin
# This implementation does NOT use the actuar package.
#######################################################################

# --- Distribution helpers ---

pgamma_cdf <- function(x, shape, rate) {
  pgamma(x, shape = shape, rate = rate)
}

levgamma <- function(x, shape, rate) {
  # Limited expected value E[min(X, x)] for Gamma(shape, rate)
  shape / rate * pgamma(x, shape + 1, rate) + x * (1 - pgamma(x, shape, rate))
}

ppareto_cdf <- function(x, shape, scale) {
  # CDF of Pareto: 1 - (scale/(scale+x))^shape
  1 - (scale / (scale + x))^shape
}

# --- Stage 1: Discretization ---

discretize_dist <- function(cdf_func, from, to, step, method, lev_func = NULL) {
  if (method == "upper") {
    x <- seq(from, to, by = step)
    Fx <- cdf_func(x)
    return(diff(Fx))

  } else if (method == "lower") {
    x <- seq(from, to, by = step)
    Fx <- cdf_func(x)
    return(c(0, diff(Fx)))

  } else if (method == "rounding") {
    # Rounding / midpoint discretization
    x <- seq(from, to, by = step)
    Fx <- cdf_func(x)
    return(diff(Fx))

  } else if (method == "unbiased") {
    if (is.null(lev_func)) stop("lev_func required for unbiased method")
    x <- seq(from, to, by = step)
    Ex <- lev_func(x)
    Fx_bounds <- cdf_func(c(from, to))

    first <- -diff(head(Ex, 2)) / step + 1 - Fx_bounds[1]
    middle <- (2 * head(Ex[-1], -1) - head(Ex, -2) - tail(Ex, -2)) / step
    last <- diff(tail(Ex, 2)) / step - 1 + Fx_bounds[2]
    return(c(first, middle, last))
  }
  stop(paste("Unknown method:", method))
}

# --- Stage 2: Panjer Recursion ---

panjer_recursion <- function(fx, dist, params, x_scale = 1, tol = 1e-6, maxit = 500) {
  M <- length(fx) - 1  # severity support upper bound (math 0-indexed)

  if (dist == "poisson") {
    lambda <- params$lambda
    a <- 0
    b <- lambda
    fs0 <- exp(lambda * fx[1] - 1)
  } else if (dist == "geometric") {
    p <- params$prob
    a <- 1 - p
    b <- 1 - p
    fs0 <- 1 / (1 - ((1 - p) / p) * (fx[1] - 1))
  } else {
    stop(paste("Unsupported distribution:", dist))
  }

  norm <- 1 - a * fx[1]

  fs <- numeric(0)
  fs[1] <- fs0
  cumul <- fs0

  for (math_x in 1:maxit) {
    m <- min(math_x, M)
    s <- 0
    for (k in 1:m) {
      s <- s + (a + b * k / math_x) * fx[k + 1] * fs[math_x - k + 1]
    }
    fs[math_x + 1] <- s / norm
    cumul <- cumul + fs[math_x + 1]

    if (cumul >= 1 - tol) break
  }

  knots <- (0:(length(fs) - 1)) * x_scale
  list(knots = knots, pmf = fs, cdf = pmin(cumsum(fs), 1))
}

# --- Stage 3: Risk Measures ---

compute_var <- function(knots, pmf, conf_level) {
  cdf <- cumsum(pmf)
  idx <- which(cdf >= conf_level)[1]
  if (is.na(idx)) return(tail(knots, 1))
  if (idx <= 1) return(knots[1])
  knots[idx - 1]
}

compute_cte <- function(knots, pmf, conf_level) {
  # CTE = E[S | S > VaR(conf_level)]
  return(NA_real_)
}

# --- Stage 4: Beekman Ruin Bounds ---

beekman_ruin_bounds <- function(severity_cdf, from, to, step, freq_prob) {
  # Compute lower and upper bounds on ruin probability psi(u)
  # for u in {0, 5, 10, ..., 50}
  u_vals <- seq(0, 50, by = 5)
  return(list(lower = rep(NA_real_, length(u_vals)),
              upper = rep(NA_real_, length(u_vals))))
}
