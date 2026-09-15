#
# Mack Chain Ladder with Cornish-Fisher Quantile Estimation
# Based on Mack (1993, 1999) and Dal Moro (SSRN 2965384)

# ====================== TRIANGLE DATA ======================

# RAA: Reinsurance Association of America run-off triangle
# Source: Historical Loss Development, RAA, 1991, p.96
RAA <- matrix(c(
  5012,  8269, 10907, 11805, 13539, 16181, 18009, 18608, 18662, 18834,
   106,  4285,  5396, 10666, 13782, 15599, 15496, 16169, 16704,    NA,
  3410,  8992, 13873, 16141, 18735, 22214, 22863, 23466,    NA,    NA,
  5655, 11555, 15766, 21266, 23425, 26083, 27067,    NA,    NA,    NA,
  1092,  9565, 15836, 22169, 25955, 26180,    NA,    NA,    NA,    NA,
  1513,  6445, 11702, 12935, 15852,    NA,    NA,    NA,    NA,    NA,
   557,  4020, 10946, 12314,    NA,    NA,    NA,    NA,    NA,    NA,
  1351,  6947, 13112,    NA,    NA,    NA,    NA,    NA,    NA,    NA,
  3133,  5395,    NA,    NA,    NA,    NA,    NA,    NA,    NA,    NA,
  2063,    NA,    NA,    NA,    NA,    NA,    NA,    NA,    NA,    NA
), nrow = 10, ncol = 10, byrow = TRUE)
dimnames(RAA) <- list(origin = 1981:1990, dev = 1:10)

# GenIns: General Insurance claims triangle
# Source: Taylor & Ashe (1983), Journal of Econometrics 23, 37-61
GenIns <- matrix(c(
  357848, 1124788, 1735330, 2218270, 2745596, 3319994, 3466336, 3606286, 3833515, 3901463,
  352118, 1236139, 2170033, 3353322, 3799067, 4120063, 4647867, 4914039, 5339085,       NA,
  290507, 1292306, 2218525, 3235179, 3985995, 4132918, 4628910, 4909315,       NA,       NA,
  310608, 1418858, 2195047, 3757447, 4029929, 4381982, 4588268,       NA,       NA,       NA,
  443160, 1136350, 2128333, 2897821, 3402672, 3873311,       NA,       NA,       NA,       NA,
  396132, 1333217, 2180715, 2985752, 3691712,       NA,       NA,       NA,       NA,       NA,
  440832, 1288463, 2419861, 3483130,       NA,       NA,       NA,       NA,       NA,       NA,
  359480, 1421128, 2864498,       NA,       NA,       NA,       NA,       NA,       NA,       NA,
  376686, 1363294,       NA,       NA,       NA,       NA,       NA,       NA,       NA,       NA,
  344014,       NA,       NA,       NA,       NA,       NA,       NA,       NA,       NA,       NA
), nrow = 10, ncol = 10, byrow = TRUE)
dimnames(GenIns) <- list(origin = 1:10, dev = 1:10)

# ====================== UTILITY FUNCTIONS ======================

getLatestCumulative <- function(Triangle) {
  m <- nrow(Triangle)
  latest <- numeric(m)
  latestcol <- integer(m)
  for (i in 1:m) {
    nonNA <- which(!is.na(Triangle[i, ]))
    if (length(nonNA) > 0) {
      latest[i] <- Triangle[i, max(nonNA)]
      latestcol[i] <- max(nonNA)
    }
  }
  names(latest) <- rownames(Triangle)
  attr(latest, "latestcol") <- latestcol
  latest
}

checkTriangle <- function(Triangle) {
  m <- nrow(Triangle)
  n <- ncol(Triangle)
  if (n > m) stop("Origin periods must be >= development periods")
  if (is.null(dimnames(Triangle))) {
    dimnames(Triangle) <- list(origin = 1:m, dev = 1:n)
  }
  storage.mode(Triangle) <- "double"
  Triangle
}

# ====================== CHAIN LADDER ======================

chainladder <- function(Triangle, weights = 1, delta = 1) {
  Triangle <- checkTriangle(Triangle)
  n <- ncol(Triangle)
  m <- nrow(Triangle)

  if (length(weights) == 1) {
    W <- matrix(weights, nrow = m, ncol = n)
    W[is.na(Triangle)] <- NA
  } else {
    W <- weights
  }

  delta <- rep(delta, n - 1)[1:(n - 1)]

  Models <- list()
  for (i in 1:(n - 1)) {
    x_val <- Triangle[, i]
    y_val <- Triangle[, i + 1]
    w_val <- W[, i] / Triangle[, i]^delta[i]
    valid <- !is.na(x_val) & !is.na(y_val) & !is.na(w_val)
    df <- data.frame(x = x_val[valid], y = y_val[valid])
    Models[[i]] <- lm(y ~ x + 0, weights = w_val[valid], data = df)
  }

  list(Models = Models, Triangle = Triangle, delta = delta, weights = W)
}

predict_chainladder <- function(CL) {
  Triangle <- CL$Triangle
  n <- ncol(Triangle)
  FullTriangle <- Triangle

  for (j in 2:n) {
    missing <- is.na(FullTriangle[, j])
    if (any(missing)) {
      FullTriangle[missing, j] <- predict(CL$Models[[j - 1]],
                                          newdata = data.frame(x = FullTriangle[missing, j - 1]))
    }
  }
  FullTriangle
}

# ====================== SIGMA ESTIMATION ======================

estimate_sigma <- function(sigma) {
  n <- length(sigma)
  dev <- 1:n
  valid <- !is.na(sigma) & sigma > 0
  my.dev <- dev[valid]
  my.model <- lm(log(sigma[my.dev]) ~ my.dev)
  sigma[is.na(sigma)] <- exp(predict(my.model,
                                      newdata = data.frame(my.dev = dev[is.na(sigma)])))
  list(sigma = sigma, model = my.model)
}

# ====================== MACK STANDARD ERRORS ======================

mack_se <- function(Models, FullTriangle, est.sigma = "log-linear", weights, alpha) {
  n <- ncol(FullTriangle)
  m <- nrow(FullTriangle)

  smmry <- suppressWarnings(lapply(Models, summary))
  f     <- sapply(smmry, function(s) s$coef["x", "Estimate"])
  f.se  <- sapply(smmry, function(s) s$coef["x", "Std. Error"])
  sigma <- sapply(smmry, function(s) s$sigma)

  isna <- is.na(sigma)

  if (est.sigma[1] == "log-linear") {
    if (sum(!isna) <= 1) {
      est.sigma <- "Mack"
    } else {
      sig.model <- suppressWarnings(estimate_sigma(sigma))
      sigma <- sig.model$sigma
      p.value <- tryCatch(summary(sig.model$model)$coefficient[2, 4],
                          error = function(e) 1)
      if (is.nan(p.value) || is.infinite(p.value) || p.value > 0.05) {
        est.sigma <- "Mack"
      } else {
        f.se[isna] <- sigma[isna] / sqrt(weights[1, isna] * FullTriangle[1, isna]^alpha[isna])
      }
    }
  }

  if (est.sigma[1] == "Mack") {
    for (i in which(isna)) {
      ratio <- sigma[i - 1]^4 / sigma[i - 2]^2
      if (is.nan(ratio) || is.infinite(ratio)) {
        sigma[i] <- sqrt(abs(min(sigma[i - 2]^2, sigma[i - 1]^2)))
      } else {
        sigma[i] <- sqrt(abs(min(ratio, min(sigma[i - 2]^2, sigma[i - 1]^2))))
      }
      f.se[i] <- sigma[i] / sqrt(weights[1, i] * FullTriangle[1, i]^alpha[i])
    }
  }

  W <- weights
  W[is.na(W)] <- 1
  F.se <- t(sigma / t(sqrt(W[, -n] * t(t(FullTriangle[, -n])^alpha[-n]))))

  list(sigma = sigma, f = f, f.se = f.se, F.se = F.se)
}

# ====================== RECURSIVE MACK S.E. ======================

mack_recursive_se <- function(FullTriangle, f, f.se, F.se) {
  n <- ncol(FullTriangle)
  m <- nrow(FullTriangle)

  procrisk  <- FullTriangle * 0
  paramrisk <- FullTriangle * 0

  for (k in 1:(n - 1)) {
    for (i in (m - k + 1):m) {
      procrisk[i, k+1] <- sqrt(FullTriangle[i,k]^2 * F.se[i,k]^2 + procrisk[i,k]^2 * f[k])

      paramrisk[i, k+1] <- sqrt(f.se[k]^2 + paramrisk[i,k]^2 * f[k]^2)
    }
  }

  list(procrisk = procrisk, paramrisk = paramrisk)
}

# ====================== TOTAL MACK S.E. ======================

total_mack_se <- function(FullTriangle, f, f.se, F.se, procrisk) {
  n <- ncol(FullTriangle)
  m <- nrow(FullTriangle)

  total.procrisk  <- sqrt(colSums(procrisk^2, na.rm = TRUE))
  total.paramrisk <- numeric(n)

  M <- sapply(1:n, function(k) sum(FullTriangle[1:k, k], na.rm = TRUE))

  for (k in 1:(n - 1)) {
    total.paramrisk[k + 1] <- sqrt(
      M[k]^2 * f.se[k]^2 + total.paramrisk[k]^2 * f[k]^2
    )
  }

  total.se <- sqrt(total.procrisk^2 + total.paramrisk^2)[n]
  attr(total.se, "processrisk") <- total.procrisk
  attr(total.se, "paramrisk")   <- total.paramrisk
  total.se
}

# ====================== MACK CHAIN LADDER ======================

MackChainLadder <- function(Triangle, weights = 1, alpha = 1, est.sigma = "log-linear",
                            tail = FALSE) {
  Triangle <- checkTriangle(Triangle)
  m <- nrow(Triangle)
  n <- ncol(Triangle)

  delta <- 2 - alpha
  CL <- chainladder(Triangle, weights = weights, delta = delta)
  alpha_vec <- 2 - CL$delta

  FullTriangle <- predict_chainladder(CL)

  SE <- mack_se(CL$Models, FullTriangle, est.sigma = est.sigma,
                weights = CL$weights, alpha = alpha_vec)

  if (is.logical(tail)) {
    tail.factor <- 1.0
  } else {
    tail.factor <- as.numeric(tail)
  }
  SE$f <- c(SE$f, tail.factor)

  if (tail.factor > 1) {
    FullTriangle <- cbind(FullTriangle, FullTriangle[, n] * tail.factor)
    colnames(FullTriangle) <- c(colnames(FullTriangle)[1:n], "Inf")

    .f <- SE$f[1:(n - 1)]
    .dev <- 1:(n - 1)
    mf <- lm(log(.f - 1) ~ .dev)
    tail.pos <- (log(tail.factor - 1) - coef(mf)[1]) / coef(mf)[2]

    .fse <- SE$f.se[1:(n - 1)]
    mse.model <- lm(log(.fse) ~ .dev)
    tail.se <- exp(predict(mse.model, newdata = data.frame(.dev = tail.pos)))
    SE$f.se <- c(SE$f.se, tail.se = tail.se)

    .sigma <- SE$sigma[1:(n - 1)]
    msig <- lm(log(.sigma) ~ .dev)
    tail.sigma <- as.numeric(exp(predict(msig, newdata = data.frame(.dev = tail.pos))))
    SE$sigma <- c(SE$sigma, tail.sigma = tail.sigma)

    se.F.tail <- tail.sigma / sqrt(FullTriangle[, n]^alpha_vec[n - 1])
    SE$F.se <- cbind(SE$F.se, se.F.tail)
  }

  recursive <- mack_recursive_se(FullTriangle, SE$f, SE$f.se, SE$F.se)
  Total.SE  <- total_mack_se(FullTriangle, SE$f, SE$f.se, SE$F.se, recursive$procrisk)
  Mack.S.E  <- sqrt(recursive$procrisk^2 + recursive$paramrisk^2)

  list(
    Triangle           = Triangle,
    FullTriangle       = FullTriangle,
    Models             = CL$Models,
    f                  = SE$f,
    f.se               = SE$f.se,
    F.se               = SE$F.se,
    sigma              = SE$sigma,
    Mack.ProcessRisk   = recursive$procrisk,
    Mack.ParameterRisk = recursive$paramrisk,
    Mack.S.E           = Mack.S.E,
    weights            = CL$weights,
    alpha              = alpha_vec,
    Total.Mack.S.E     = Total.SE,
    Total.ProcessRisk  = attr(Total.SE, "processrisk"),
    Total.ParameterRisk = attr(Total.SE, "paramrisk")
  )
}

# ====================== CORNISH-FISHER SKEWNESS ======================

mack_skewness <- function(x) {
  Triangle     <- x$Triangle
  FullTriangle <- x$FullTriangle
  n <- ncol(Triangle)

  Sigma2 <- x$sigma^2
  f      <- x$f

  myModel <- matrix(NA, nrow = n, ncol = n - 1)
  for (i in 1:(n - 1)) {
    avail <- 1:(n - i)
    myModel[avail, i] <- Triangle[avail, i + 1] / Triangle[avail, i] - f[i]
  }

  Interm1 <- sapply(1:(n - 1), function(i) sum(Triangle[1:(n - i), i]^1.5))
  Interm2 <- as.numeric(sapply(1:(n - 1), function(i) sum(Triangle[1:(n - i), i])))

  Sk3k <- sapply(1:(n - 1), function(i) {
    1/(n - i) * sum(Triangle[1:(n-i), i]^1.5 * myModel[1:(n-i), i]^3)
  })

  for (k in 1:(n - 1)) {
    if (is.infinite(Sk3k[k]) || is.nan(Sk3k[k])) Sk3k[k] <- 0
  }

  Variance <- numeric(n - 1)
  Skewnes  <- numeric(n - 1)

  for (k in 1:(n - 1)) {
    Variance[k] <- Triangle[n + 1 - k, k]^2 * Sigma2[k] *
                   (1 / Interm2[k] + 1 / Triangle[n + 1 - k, k])

    if (k < n - 1) {
      Skewnes[k] <- Triangle[n + 1 - k, k]^1.5 * Sk3k[k] +
                    Triangle[n + 1 - k, k]^3 * Sk3k[k] * Interm1[k] / Interm2[k]^3
    }

    for (j in (k + 1):(n - 1)) {
      intermediaire  <- sum(FullTriangle[1:(n - j), j])
      intermediaire1 <- sum(FullTriangle[1:(n - j), j]^1.5)

      if (k < n - 1) {
        Skewnes[k] <- Skewnes[k] * f[j]^3 +
          FullTriangle[n + 1 - k, j]^1.5 * Sk3k[j] *
            (1 + Variance[k] / FullTriangle[n + 1 - k, j]^2)^(3/8) +
          3 * Sigma2[j] * f[j] * Variance[k] +
          FullTriangle[n + 1 - k, j]^3 * intermediaire1 / intermediaire^3 * Sk3k[j]

        Variance[k] <- Variance[k] * f[j]^2 +
          FullTriangle[n + 1 - k, j]^2 * Sigma2[j] *
            (1 / intermediaire + 1 / FullTriangle[n + 1 - k, j])
      }
    }
  }

  Inter <- numeric(n - 1)
  for (k in 1:(n - 1)) {
    Inter[n - k] <- Sigma2[k] / f[k]^2 / Interm2[k]
  }
  for (k in 2:(n - 2)) {
    Inter[k] <- Inter[k - 1] + Inter[k]
  }

  Correlation <- matrix(0, nrow = n - 2, ncol = n - 2)
  for (k in 1:(n - 2)) {
    for (l in (k + 1):(n - 1)) {
      Correlation[k, l - 1] <- Inter[k] * FullTriangle[k + 1, n] *
        FullTriangle[l + 1, n] / sqrt(Variance[n - k]) / sqrt(Variance[n - l])
    }
  }

  OverSkew <- sum(Skewnes)

  for (o in 1:(n - 2)) {
    for (p in (o + 1):(n - 1)) {
      OverSkew <- OverSkew +
        3 * Correlation[o, p - 1] * sqrt(Variance[n - o] * Variance[n - p]) *
        (Variance[n - o] / FullTriangle[o + 1, n] + Variance[n - p] / FullTriangle[p + 1, n]) *
        (2 + Correlation[o, p - 1] * sqrt(Variance[n - o] * Variance[n - p]) /
           (FullTriangle[p + 1, n] * FullTriangle[o + 1, n]))
      OverSkew <- OverSkew +
        3 * Correlation[o, p - 1]^2 * Variance[n - o] * Variance[n - p] *
        (FullTriangle[o + 1, n] + FullTriangle[p + 1, n]) /
        (FullTriangle[o + 1, n] * FullTriangle[p + 1, n])
    }
  }

  for (o in 1:(n - 3)) {
    for (p in (o + 1):(n - 2)) {
      for (q in (p + 1):(n - 1)) {
        OverSkew <- OverSkew +
          6 * Correlation[o, p - 1] * Correlation[p, q - 1] * Correlation[o, q - 1] *
          sqrt(Variance[n - o] * Variance[n - p] * Variance[n - q]) *
          (sqrt(Variance[n - o] * Variance[n - p] * Variance[n - q]) /
             (FullTriangle[o + 1, n] * FullTriangle[p + 1, n] * FullTriangle[q + 1, n]) +
             sqrt(Variance[n - o]) / (Correlation[p, q - 1] * FullTriangle[o + 1, n]) +
             sqrt(Variance[n - p]) / (Correlation[o, q - 1] * FullTriangle[p + 1, n]) +
             sqrt(Variance[n - q]) / (Correlation[o, p - 1] * FullTriangle[q + 1, n]))
      }
    }
  }

  Skewnesi <- numeric(n)
  Sk3ki    <- numeric(n)
  Skewnesi[1:2] <- 0
  Sk3ki[1:2]    <- 0

  for (k in 3:n) {
    if (Variance[n - k + 1] > 0) {
      Skewnesi[k] <- Skewnes[n - k + 1] / Variance[n - k + 1]^1.5
    }
    Sk3ki[k] <- Sk3k[n - k + 1]
  }

  list(Skewnes = Skewnesi, Correlation = Correlation, OverSkew = OverSkew, Sk3k = Sk3ki)
}

# ====================== QUANTILE ESTIMATION ======================

quantile_mack <- function(x, probs = c(0.75, 0.95)) {
  Latest   <- getLatestCumulative(x$Triangle)
  Ultimate <- x$FullTriangle[, ncol(x$FullTriangle)]
  IBNR     <- Ultimate - Latest
  Mack.S.E <- x$Mack.S.E[, ncol(x$Mack.S.E)]
  CV       <- Mack.S.E / IBNR

  Skewn <- mack_skewness(x)

  z <- qnorm(probs)

  CF <- sapply(z, function(q) q + 1/6 * (q^2 - 1) * Skewn$Skewnes)
  QuantilePY <- (1 + CF * CV) * IBNR

  CF_tot       <- z + 1/6 * (z^2 - 1) * Skewn$OverSkew / x$Total.Mack.S.E^3
  TotQuantile  <- (1 + CF_tot * x$Total.Mack.S.E / sum(IBNR)) * sum(IBNR)
  TotSkew      <- Skewn$OverSkew / x$Total.Mack.S.E^3

  ByOrigin <- data.frame(Skewness = Skewn$Skewnes, QuantilePY)
  names(ByOrigin) <- c("Skewness", paste0("IBNR ", probs * 100, "%"))

  Totals <- as.data.frame(c(TotSkew, TotQuantile))
  colnames(Totals) <- "Totals"
  rownames(Totals) <- c("Skewness", paste0("IBNR ", probs * 100, "%:"))

  list(ByOrigin = ByOrigin, Totals = Totals)
}
