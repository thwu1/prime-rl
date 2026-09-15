#
# Munich Chain Ladder — Quarg & Mack (2004)
# Reduces the gap between paid-based and incurred-based IBNR projections
# by incorporating the correlation between paid and incurred development.
#
# Requires: source("/app/reserving.R") for Mack Chain Ladder functions

# ====================== MCL TRIANGLE DATA ======================

# Paid and incurred triangles from Quarg & Mack (2004)
MCLpaid <- matrix(c(
   576, 1804, 1970, 2024, 2074, 2102, 2131,
   866, 1948, 2162, 2232, 2284, 2348,   NA,
  1412, 3758, 4252, 4416, 4494,   NA,   NA,
  2286, 5292, 5724, 5850,   NA,   NA,   NA,
  1868, 3778, 4648,   NA,   NA,   NA,   NA,
  1442, 4010,   NA,   NA,   NA,   NA,   NA,
  2044,   NA,   NA,   NA,   NA,   NA,   NA
), nrow = 7, ncol = 7, byrow = TRUE)
dimnames(MCLpaid) <- list(origin = 1:7, dev = 1:7)

MCLincurred <- matrix(c(
   978, 2104, 2134, 2144, 2174, 2182, 2174,
  1844, 2552, 2466, 2480, 2508, 2454,   NA,
  2904, 4354, 4698, 4600, 4644,   NA,   NA,
  3502, 5958, 6070, 6142,   NA,   NA,   NA,
  2812, 4882, 4852,   NA,   NA,   NA,   NA,
  2642, 4406,   NA,   NA,   NA,   NA,   NA,
  5022,   NA,   NA,   NA,   NA,   NA,   NA
), nrow = 7, ncol = 7, byrow = TRUE)
dimnames(MCLincurred) <- list(origin = 1:7, dev = 1:7)

# ====================== MCL HELPERS ======================

# Construct Last-3 LDF weight selection matrix
# Zeroes out development factors from calendar periods more than 3 from latest
build_ldf_weights <- function(Triangle) {
  t_idx <- row(Triangle) + col(Triangle) - 1
  n <- ncol(Triangle)
  w <- ifelse(t_idx <= n - 4, 0, ifelse(t_idx > n, NA, 1))
  w
}

# Normalize weight input to matrix matching triangle dimensions
checkWeights <- function(weights, Triangle) {
  if (length(weights) == 1) {
    W <- matrix(weights, nrow = nrow(Triangle), ncol = ncol(Triangle))
    W[is.na(Triangle)] <- NA
  } else {
    W <- weights
  }
  W
}

# Upper-left triangle indicator
left.tri <- function(x) col(as.matrix(x)) < ncol(as.matrix(x)) - row(as.matrix(x)) + 2

# ====================== MUNICH CHAIN LADDER ======================

MunichChainLadder <- function(Paid, Incurred,
                               est.sigmaP = "log-linear",
                               est.sigmaI = "log-linear",
                               tailP = FALSE,
                               tailI = FALSE,
                               weights = 1) {

  if (!all(dim(Paid) == dim(Incurred)))
    stop("Paid and Incurred triangles must have same dimension")

  n <- ncol(Paid)
  m <- nrow(Paid)

  if (m > n)
    stop("MunichChainLadder does not support fewer dev periods than origin periods")

  # Step 1: Run standard Mack Chain Ladder on each triangle independently
  MackPaid <- MackChainLadder(Paid, weights = weights, tail = tailP, est.sigma = est.sigmaP)
  MackIncurred <- MackChainLadder(Incurred, weights = weights, tail = tailI, est.sigma = est.sigmaI)
  W <- checkWeights(weights, Paid)

  # ---- Q-model: regress Paid on Incurred to estimate P/I ratio factors ----
  q.f <- rep(1, n)
  rhoI.sigma <- rep(0, n)
  for (s in 1:n) {
    rows <- 1:(n - s + 1)
    model <- lm(Paid[rows, s] ~ Incurred[rows, s] + 0,
                weights = 1/Paid[rows, s] * W[rows, s])
    q.f[s] <- summary(model)$coef[1]
    rhoI.sigma[s] <- summary(model)$sigma
  }
  rhoI.sigma <- estimate_sigma(rhoI.sigma)$sigma

  # ---- Q-inverse model: regress Incurred on Paid for I/P ratio factors ----
  qinverse.f <- rep(1, n)
  rhoP.sigma <- rep(0, n)
  for (s in 1:n) {
    rows <- 1:(n - s + 1)
    model <- lm(Incurred[rows, s] ~ Paid[rows, s] + 0,
                weights = 1/Paid[rows, s] * W[rows, s])
    qinverse.f[s] <- summary(model)$coef[1]
    rhoP.sigma[s] <- summary(model)$sigma
  }
  rhoP.sigma <- estimate_sigma(rhoP.sigma)$sigma

  # ---- Compute standardized residuals ----
  # The Munich method exploits the correlation between paid development
  # and incurred-to-paid ratios (and vice versa). Four types of residuals
  # are needed:
  #   1. Paid development residuals: (actual_ratio - f) / sigma * sqrt(C) * w
  #   2. Incurred development residuals: same structure for incurred
  #   3. Q-ratio residuals: (P/I - q.f) / rhoI.sigma * sqrt(I) * w
  #   4. Q-inverse residuals: (I/P - 1/q.f) / rhoP.sigma * sqrt(P) * w
  #
  # Development residuals use the (m-1) x (n-1) interior triangle with
  # the diagonal masked. Q and Q-inverse residuals use the full m x (n-1)
  # body. All residual matrices must then be reshaped into vectors
  # (keeping only the upper triangle, masking last two dev columns)
  # for the lambda regression step.

  PaidResiduals <- rep(NA, n * n)
  IncurredResiduals <- rep(NA, n * n)
  QResiduals <- rep(NA, n * n)
  QinverseResiduals <- rep(NA, n * n)

  # ---- Lambda estimation: correlation between development and ratio residuals ----
  inc.res.model <- lm(IncurredResiduals ~ QResiduals + 0)
  lambdaI <- coef(inc.res.model)[1]

  paid.res.model <- lm(PaidResiduals ~ QinverseResiduals + 0)
  lambdaP <- coef(paid.res.model)[1]

  # ---- Recursive Munich Chain Ladder correction ----
  FullPaid <- cbind(Paid, rep(NA, m))
  FullIncurred <- cbind(Incurred, rep(NA, m))

  for (j in 1:n) {
    for (i in (n - j + 1):m) {
      # Paid MCL adjustment: correct development using ratio deviation
      mclcorrection <- lambdaP * MackPaid$sigma[j] / rhoP.sigma[j] * (
        FullPaid[i, j] / FullIncurred[i, j] - q.f[j]
      )
      mclcorrection <- ifelse(!is.na(mclcorrection), mclcorrection, 0)
      FullPaid[i, j + 1] <- FullPaid[i, j] * (MackPaid$f[j] + mclcorrection)

      # Incurred MCL adjustment: correct development using ratio deviation
      mclcorrection <- lambdaI * MackIncurred$sigma[j] / rhoI.sigma[j] * (
        FullPaid[i, j] / FullIncurred[i, j] - q.f[j]
      )
      mclcorrection <- ifelse(!is.na(mclcorrection), mclcorrection, 0)
      FullIncurred[i, j + 1] <- FullIncurred[i, j] * (MackIncurred$f[j] + mclcorrection)
    }
  }

  list(
    Paid = Paid,
    Incurred = Incurred,
    MCLPaid = FullPaid[, c(1:(n - 1), n + 1)],
    MCLIncurred = FullIncurred[, c(1:(n - 1), n + 1)],
    MackPaid = MackPaid,
    MackIncurred = MackIncurred
  )
}

# ====================== MCL SUMMARY ======================

summary_mcl <- function(result) {
  Paid <- as.matrix(result$Paid)
  Incurred <- as.matrix(result$Incurred)
  n <- ncol(result$MCLPaid)
  m <- nrow(result$MCLPaid)

  getCurrent <- function(.x) {
    rev(.x[row(as.matrix(.x)) == (nrow(.x) + 1 - col(as.matrix(.x)))])
  }

  LatestPaid <- getCurrent(Paid)
  LatestIncurred <- getCurrent(Incurred)
  UltimatePaid <- result$MCLPaid[, n]
  UltimateIncurred <- result$MCLIncurred[, n]

  Totals <- data.frame(
    Paid = c(sum(LatestPaid, na.rm = TRUE), sum(UltimatePaid, na.rm = TRUE)),
    Incurred = c(sum(LatestIncurred, na.rm = TRUE), sum(UltimateIncurred, na.rm = TRUE))
  )
  Totals["P/I Ratio"] <- Totals$Paid / Totals$Incurred
  rownames(Totals) <- c("Latest:", "Ultimate:")

  list(Totals = Totals)
}
