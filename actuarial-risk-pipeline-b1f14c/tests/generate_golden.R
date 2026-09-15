
# Generate golden reference values using the actuar R package.
# Writes /tmp/golden.json for comparison by test_state.py.

library(actuar)

# --- Discretization of Gamma(2,1) on (0,22) step 0.5 ---
disc_upper   <- discretize(pgamma(x, 2, 1), method = "upper",
                           from = 0, to = 22, step = 0.5)
disc_lower   <- discretize(pgamma(x, 2, 1), method = "lower",
                           from = 0, to = 22, step = 0.5)
disc_rounding <- discretize(pgamma(x, 2, 1), method = "rounding",
                            from = 0, to = 22, step = 0.5)
disc_unbiased <- discretize(pgamma(x, 2, 1), method = "unbiased",
                            from = 0, to = 22, step = 0.5,
                            lev = levgamma(x, 2, 1))

# --- Panjer recursion: Poisson(10) + unbiased Gamma(2,1) ---
Fs <- aggregateDist("recursive", model.freq = "poisson",
                    model.sev = disc_unbiased, lambda = 10,
                    x.scale = 0.5)

agg_mean    <- mean(Fs)
agg_cdf_10  <- Fs(10)
agg_cdf_20  <- Fs(20)
agg_cdf_30  <- Fs(30)
agg_cdf_40  <- Fs(40)

# --- Risk measures ---
var_vals <- VaR(Fs, c(0.90, 0.95, 0.99))
cte_vals <- CTE(Fs, c(0.90, 0.95, 0.99))

# --- Beekman ruin bounds: Pareto(4,4), geometric(1/6) ---
f.L <- discretize(ppareto(x, 4, 4), from = 0, to = 200,
                  step = 1, method = "lower")
f.U <- discretize(ppareto(x, 4, 4), from = 0, to = 200,
                  step = 1, method = "upper")
F.L <- aggregateDist(method = "recursive", model.freq = "geometric",
                     model.sev = f.L, prob = 1/6)
F.U <- aggregateDist(method = "recursive", model.freq = "geometric",
                     model.sev = f.U, prob = 1/6)

u_vals <- seq(0, 50, by = 5)
psi_lower <- 1 - F.U(u_vals)   # lower bound on ruin prob
psi_upper <- 1 - F.L(u_vals)   # upper bound on ruin prob

# --- Write JSON ---
format_val <- function(x) {
  if (length(x) > 1) {
    paste0("[", paste(sprintf("%.15e", x), collapse = ", "), "]")
  } else if (is.na(x)) {
    "null"
  } else {
    sprintf("%.15e", x)
  }
}

golden <- list(
  discretization = list(
    upper = disc_upper,
    lower = disc_lower,
    rounding = disc_rounding,
    unbiased = disc_unbiased
  ),
  aggregate = list(
    mean = agg_mean,
    cdf_at_10 = unname(agg_cdf_10),
    cdf_at_20 = unname(agg_cdf_20),
    cdf_at_30 = unname(agg_cdf_30),
    cdf_at_40 = unname(agg_cdf_40)
  ),
  risk_measures = list(
    var_90 = unname(var_vals[1]),
    var_95 = unname(var_vals[2]),
    var_99 = unname(var_vals[3]),
    cte_90 = unname(cte_vals[1]),
    cte_95 = unname(cte_vals[2]),
    cte_99 = unname(cte_vals[3])
  ),
  ruin_bounds = list(
    lower = psi_lower,
    upper = psi_upper
  )
)

lines <- "{"
secs <- names(golden)
for (i in seq_along(secs)) {
  sec_name <- secs[i]
  sec <- golden[[sec_name]]
  lines <- c(lines, paste0('  "', sec_name, '": {'))
  items <- names(sec)
  for (j in seq_along(items)) {
    item_name <- items[j]
    val <- format_val(sec[[item_name]])
    comma <- if (j < length(items)) "," else ""
    lines <- c(lines, paste0('    "', item_name, '": ', val, comma))
  }
  sec_comma <- if (i < length(secs)) "}," else "}"
  lines <- c(lines, paste0("  ", sec_comma))
}
lines <- c(lines, "}")
writeLines(lines, "/tmp/golden.json")
cat("Golden values written to /tmp/golden.json\n")
