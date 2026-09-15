#!/usr/bin/env python3
"""
Fix bugs in reserving.R and complete munich.R implementation.
"""


def fix_reserving():
    """Fix 4 mathematical bugs in the Mack Chain Ladder implementation."""
    with open("/app/reserving.R", "r") as f:
        code = f.read()

    # Bug 1: Process risk recursion uses f[k] instead of f[k]^2
    code = code.replace(
        "procrisk[i,k]^2 * f[k])",
        "procrisk[i,k]^2 * f[k]^2)",
    )

    # Bug 2: Parameter risk recursion missing FullTriangle[i,k]^2 multiplier
    code = code.replace(
        "sqrt(f.se[k]^2 + paramrisk[i,k]^2",
        "sqrt(FullTriangle[i,k]^2 * f.se[k]^2 + paramrisk[i,k]^2",
    )

    # Bug 3: Total Mack SE M vector sums wrong rows (1:k instead of (m+1-k):m)
    code = code.replace(
        "sum(FullTriangle[1:k, k], na.rm = TRUE)",
        "sum(FullTriangle[(m+1-k):m, k], na.rm = TRUE)",
    )

    # Bug 4: Skewness Sk3k denominator missing bias correction term
    code = code.replace(
        "1/(n - i) * sum(Triangle[1:(n-i), i]^1.5",
        "1/(n - i - Interm1[i]^2/Interm2[i]^3) * sum(Triangle[1:(n-i), i]^1.5",
    )

    with open("/app/reserving.R", "w") as f:
        f.write(code)
    print("Fixed 4 bugs in reserving.R")


def fix_and_complete_munich():
    """Fix bugs and implement missing residual computation in munich.R."""
    with open("/app/munich.R", "r") as f:
        code = f.read()

    # Bug 5: Q-model regression weights use 1/Paid instead of 1/Incurred
    # The Q-model regresses Paid ~ Incurred, so weight should be 1/Incurred
    code = code.replace(
        "weights = 1/Paid[rows, s] * W[rows, s])\n    q.f[s]",
        "weights = 1/Incurred[rows, s] * W[rows, s])\n    q.f[s]",
    )

    # Bug 6: Paid recursive correction uses wrong ratio direction.
    # Should use I/P - qinverse.f (deviation of inverse ratio from expected)
    code = code.replace(
        """      # Paid MCL adjustment: correct development using ratio deviation
      mclcorrection <- lambdaP * MackPaid$sigma[j] / rhoP.sigma[j] * (
        FullPaid[i, j] / FullIncurred[i, j] - q.f[j]
      )""",
        """      # Paid MCL adjustment: correct development using ratio deviation
      mclcorrection <- lambdaP * MackPaid$sigma[j] / rhoP.sigma[j] * (
        FullIncurred[i, j] / FullPaid[i, j] - qinverse.f[j]
      )""",
    )

    # Implementation: Replace residual stubs with full computation
    old_residual_block = """  PaidResiduals <- rep(NA, n * n)
  IncurredResiduals <- rep(NA, n * n)
  QResiduals <- rep(NA, n * n)
  QinverseResiduals <- rep(NA, n * n)

  # ---- Lambda estimation: correlation between development and ratio residuals ----
  inc.res.model <- lm(IncurredResiduals ~ QResiduals + 0)
  lambdaI <- coef(inc.res.model)[1]

  paid.res.model <- lm(PaidResiduals ~ QinverseResiduals + 0)
  lambdaP <- coef(paid.res.model)[1]"""

    new_residual_block = """  # Weight mask: zero out diagonal and take interior triangle
  weights_t <- W
  diag(weights_t[1:m, n:1]) <- NA
  weights_t <- weights_t[1:(m-1), 1:(n-1)]

  # Paid development residuals
  Paidf <- t(matrix(rep(MackPaid$f[-n], (m-1)), ncol = (m-1)))
  PaidSigma <- t(matrix(rep(MackPaid$sigma, (m-1)), ncol = (m-1)))
  PaidRatios <- Paid[-m, -1] / Paid[-m, -n]
  PaidResiduals <- (PaidRatios - Paidf) / PaidSigma[, 1:ncol(Paidf)] * sqrt(Paid[-m, -n]) * weights_t

  # Incurred development residuals
  Incurredf <- t(matrix(rep(MackIncurred$f[-n], (m-1)), ncol = (m-1)))
  IncurredSigma <- t(matrix(rep(MackIncurred$sigma, (m-1)), ncol = (m-1)))
  IncurredRatios <- Incurred[-m, -1] / Incurred[-m, -n]
  IncurredResiduals <- (IncurredRatios - Incurredf) / IncurredSigma[, 1:ncol(Incurredf)] * sqrt(Incurred[-m, -n]) * weights_t

  # Q-ratio residuals (Paid/Incurred)
  QRatios <- (Paid/Incurred)[, -n]
  Qf <- t(matrix(rep(q.f[-n], m), ncol = m))
  QSigma <- t(matrix(rep(rhoI.sigma[-n], m), ncol = m))
  QResiduals <- (QRatios - Qf) / QSigma * sqrt(Incurred[, -n]) * W[, -n]

  # Q-inverse residuals (Incurred/Paid)
  QinverseRatios <- 1/QRatios
  Qinversef <- 1/Qf
  QinverseSigma <- t(matrix(rep(rhoP.sigma[-n], m), ncol = m))
  QinverseResiduals <- (QinverseRatios - Qinversef) / QinverseSigma * sqrt(Paid[, -n]) * W[, -n]

  # Transform residual matrices to vector form for regression
  # Keep upper triangle, mask last two dev columns
  getMCLResiduals <- function(res, n) {
    x <- matrix(NA, n, n)
    my.tri <- function(x) col(as.matrix(x)) < ncol(as.matrix(x)) - row(as.matrix(x)) + 1
    .ind <- which(my.tri(x), TRUE)
    x[.ind] <- res[.ind]
    x[, (n-1):n] <- NA
    return(as.vector(x))
  }

  QinverseResiduals <- getMCLResiduals(QinverseResiduals, n)
  QResiduals <- getMCLResiduals(QResiduals, n)
  IncurredResiduals <- getMCLResiduals(IncurredResiduals, n)
  PaidResiduals <- getMCLResiduals(PaidResiduals, n)

  # ---- Lambda estimation: correlation between development and ratio residuals ----
  inc.res.model <- lm(IncurredResiduals ~ QResiduals + 0)
  lambdaI <- coef(inc.res.model)[1]

  paid.res.model <- lm(PaidResiduals ~ QinverseResiduals + 0)
  lambdaP <- coef(paid.res.model)[1]"""

    code = code.replace(old_residual_block, new_residual_block)

    with open("/app/munich.R", "w") as f:
        f.write(code)
    print("Fixed 2 bugs and implemented residual computation in munich.R")


if __name__ == "__main__":
    fix_reserving()
    fix_and_complete_munich()
    print("All fixes applied successfully.")
