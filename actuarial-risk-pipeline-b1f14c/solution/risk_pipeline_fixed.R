
#######################################################################
# Actuarial Risk Computation Pipeline — CORRECTED VERSION
# All bugs fixed, CTE implemented, Beekman ruin bounds implemented.
#######################################################################

# --- Distribution helpers ---

pgamma_cdf <- function(x, shape, rate) {
  pgamma(x, shape = shape, rate = rate)
}

levgamma <- function(x, shape, rate) {
  shape / rate * pgamma(x, shape + 1, rate) + x * (1 - pgamma(x, shape, rate))
}

ppareto_cdf <- function(x, shape, scale) {
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
    # FIX: evaluate CDF at midpoints (half-step offsets), not grid points
    x <- c(from, seq(from + step / 2, to - step / 2, by = step))
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
  M <- length(fx) - 1

  if (dist == "poisson") {
    lambda <- params$lambda
    a <- 0
    b <- lambda
    # FIX: correct parenthesization: exp(lambda * (fx[1] - 1))
    fs0 <- exp(lambda * (fx[1] - 1))
  } else if (dist == "geometric") {
    p <- params$prob
    a <- 1 - p
    # FIX: geometric = NB(r=1, p), so b = (r-1)*(1-p) = 0
    b <- 0
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
  # FIX: return knots[idx], not knots[idx - 1]
  idx <- which(cdf >= conf_level)[1]
  if (is.na(idx)) return(tail(knots, 1))
  knots[idx]
}

compute_cte <- function(knots, pmf, conf_level) {
  # FIX: implement CTE = E[S | S > VaR(conf_level)]
  var_val <- compute_var(knots, pmf, conf_level)
  pos <- knots > var_val
  if (!any(pos)) return(tail(knots, 1))
  sum(knots[pos] * pmf[pos]) / sum(pmf[pos])
}

# --- Stage 4: Beekman Ruin Bounds ---

beekman_ruin_bounds <- function(severity_cdf, from, to, step, freq_prob) {
  # FIX: full implementation using discretization + Panjer recursion
  # severity_cdf is the CDF of the integrated tail distribution H(x)

  # Discretize H using lower and upper methods
  f_lower <- discretize_dist(severity_cdf, from, to, step, "lower")
  f_upper <- discretize_dist(severity_cdf, from, to, step, "upper")

  # Apply Panjer recursion with geometric frequency
  F_lower <- panjer_recursion(f_lower, "geometric",
                              list(prob = freq_prob), x_scale = step)
  F_upper <- panjer_recursion(f_upper, "geometric",
                              list(prob = freq_prob), x_scale = step)

  u_vals <- seq(0, 50, by = 5)

  # Evaluate the step-function CDF at each u value
  get_cdf_at <- function(result, u) {
    idx <- which(result$knots <= u)
    if (length(idx) == 0) return(0)
    result$cdf[max(idx)]
  }

  # Lower bound on psi(u) = 1 - upper_bound_on_F(u)
  # Upper bound on psi(u) = 1 - lower_bound_on_F(u)
  psi_lower <- sapply(u_vals, function(u) 1 - get_cdf_at(F_upper, u))
  psi_upper <- sapply(u_vals, function(u) 1 - get_cdf_at(F_lower, u))

  list(lower = psi_lower, upper = psi_upper)
}
