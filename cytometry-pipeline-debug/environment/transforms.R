# transforms.R — Flow Cytometry Data Transforms
#
# Implements the logicle (bi-exponential) transform as described by
# Parks, Roederer, and Moore (2006) Cytometry A 69A:541-551.
#
# The logicle transform is the inverse of a parameterized biexponential
# function B(y), mapping data-scale values to a display scale suitable
# for visualization of fluorescence data with both positive and negative
# values.
#

#' Logicle Transform
#'
#' @param x   Numeric vector of values to transform
#' @param T_  Top of scale (maximum data value, e.g. 262144)
#' @param W   Width parameter: decades of linearization around zero
#' @param M   Full width of display in asymptotic decades
#' @param A   Additional decades of negative values to display
#' @return Transformed numeric vector on [0, M] display scale
logicle_transform <- function(x, T_ = 262144, W = 0.5, M = 4.5, A = 0) {
  params <- compute_logicle_params(T_, W, M, A)

  # Apply transform to each value via numerical inversion
  sapply(x, function(xi) logicle_inverse(xi, params))
}

#' Compute internal logicle parameters from user-facing T, W, M, A
#'
#' The biexponential function is:
#'   B(y) = a * exp(b * y) - c * exp(-d * y) + f
#'
#' Parameters a, b, c, d, f are derived so that:
#'   B(1) = T   (top of scale)
#'   B(w + x2) = 0  (zero crossing at the linearization boundary)
#'   B(0) is the bottom of the negative range
#'
#' The parameter d is found by solving:
#'   2 * (ln(d) - ln(b)) + b * (x1 - x0) = 0
#'
compute_logicle_params <- function(T_, W, M, A) {
  # Normalized scale parameters
  w  <- W / (M + A)          # width in normalized units
  x2 <- A / (M + A)          # negative display boundary
  x1 <- x2 + w               # linearization point
  x0 <- x2 + 2 * w           # symmetry point
  b  <- (M + A) * log(10)    # total range in ln units

  # Solve for d: the decay rate of the negative exponential term.
  # The equation is derived from the constraint that the slope of B(y)
  # at the origin matches the linear approximation in the W region.
  solve_for_d <- function(d) {
    2 * (log(d) - log(b)) + b * (x0 - x1)
  }

  d <- tryCatch({
    uniroot(solve_for_d, interval = c(1e-10, 100), tol = 1e-12)$root
  }, error = function(e) {
    warning("uniroot failed for logicle parameter d, using fallback")
    b / 2
  })

  # Derive remaining parameters from b, d, and scale points
  c_a  <- exp(x0 * (b + d))
  mf_a <- exp(b * x1) - c_a / exp(d * x1)
  a    <- T_ / ((exp(b) - mf_a) - c_a / exp(d))
  c_   <- c_a * a
  f    <- -mf_a * a

  list(a = a, b = b, c = c_, d = d, f = f,
       w = w, x0 = x0, x1 = x1, x2 = x2,
       T_ = T_, W = W, M = M, A = A)
}

#' Invert the biexponential function for a single value
#'
#' Given x, find y such that B(y) = x using root-finding.
#' Then scale y to the [0, M] display range.
#'
logicle_inverse <- function(x, params) {
  a  <- params$a
  b  <- params$b
  c_ <- params$c
  d  <- params$d
  f  <- params$f
  M  <- params$M

  # Biexponential function B(y)
  B <- function(y) a * exp(b * y) - c_ * exp(-d * y) + f

  # Initial estimate from dominant exponential term
  if (x > 0) {
    y <- log(max(x / a, 1e-30)) / b
  } else {
    y <- 0
  }

  # Single-step secant correction
  h  <- 1e-3
  By <- B(y) - x
  Bh <- B(y + h) - x
  dB <- (Bh - By) / h
  if (abs(dB) > .Machine$double.eps) {
    y <- y - By / dB
  }

  # Constrain to valid normalized display range
  y <- max(0, min(y, 1))

  # Scale to display range
  y * M
}

#' Estimate logicle W parameter from data
#'
#' Uses the 5th percentile of negative values to set the width of
#' the linearization region.
#'
#' @param data Numeric vector of expression values
#' @param T_  Top of scale
#' @param M   Full display width in decades
#' @param A   Additional negative decades
#' @return Named list of parameters T_, W, M, A
estimate_logicle_params <- function(data, T_ = 262144, M = 4.5, A = 0) {
  neg_values <- data[data < 0]

  if (length(neg_values) == 0) {
    W <- 0.5
  } else {
    r <- quantile(neg_values, 0.05)
    W <- (M - log10(T_ / abs(r))) / 2
    W <- max(W, 0.1)
    W <- min(W, M / 2)
  }

  list(T_ = T_, W = W, M = M, A = A)
}
