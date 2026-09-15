
source("/app/risk_pipeline.R")

# --- Parameters ---
gamma_shape <- 2
gamma_rate <- 1
gamma_from <- 0
gamma_to <- 22
gamma_step <- 0.5
poisson_lambda <- 10

pareto_shape <- 4
pareto_scale <- 4
pareto_from <- 0
pareto_to <- 200
pareto_step <- 1
geom_prob <- 1 / 6

# --- Stage 1: Discretization of Gamma(2,1) ---
cdf_gamma <- function(x) pgamma_cdf(x, gamma_shape, gamma_rate)
lev_gamma <- function(x) levgamma(x, gamma_shape, gamma_rate)

disc_upper <- discretize_dist(cdf_gamma, gamma_from, gamma_to, gamma_step, "upper")
disc_lower <- discretize_dist(cdf_gamma, gamma_from, gamma_to, gamma_step, "lower")
disc_rounding <- discretize_dist(cdf_gamma, gamma_from, gamma_to, gamma_step, "rounding")
disc_unbiased <- discretize_dist(cdf_gamma, gamma_from, gamma_to, gamma_step, "unbiased", lev_gamma)

# --- Stage 2: Panjer recursion with Poisson(10) ---
agg <- panjer_recursion(disc_unbiased, "poisson", list(lambda = poisson_lambda),
                        x_scale = gamma_step)

# --- Stage 3: Risk measures ---
var_90 <- compute_var(agg$knots, agg$pmf, 0.90)
var_95 <- compute_var(agg$knots, agg$pmf, 0.95)
var_99 <- compute_var(agg$knots, agg$pmf, 0.99)
cte_90 <- compute_cte(agg$knots, agg$pmf, 0.90)
cte_95 <- compute_cte(agg$knots, agg$pmf, 0.95)
cte_99 <- compute_cte(agg$knots, agg$pmf, 0.99)

# --- Stage 4: Beekman ruin bounds ---
cdf_pareto <- function(x) ppareto_cdf(x, pareto_shape, pareto_scale)
ruin <- beekman_ruin_bounds(cdf_pareto, pareto_from, pareto_to, pareto_step, geom_prob)

# --- Helper: lookup CDF at a specific knot value ---
get_cdf_val <- function(agg, target) {
  idx <- which(abs(agg$knots - target) < 1e-10)[1]
  if (is.na(idx)) return(NA_real_)
  agg$cdf[idx]
}

# --- Assemble results ---
results <- list(
  discretization = list(
    upper = disc_upper,
    lower = disc_lower,
    rounding = disc_rounding,
    unbiased = disc_unbiased
  ),
  aggregate = list(
    mean = sum(agg$knots * agg$pmf),
    cdf_at_10 = get_cdf_val(agg, 10),
    cdf_at_20 = get_cdf_val(agg, 20),
    cdf_at_30 = get_cdf_val(agg, 30),
    cdf_at_40 = get_cdf_val(agg, 40)
  ),
  risk_measures = list(
    var_90 = var_90,
    var_95 = var_95,
    var_99 = var_99,
    cte_90 = cte_90,
    cte_95 = cte_95,
    cte_99 = cte_99
  ),
  ruin_bounds = list(
    lower = ruin$lower,
    upper = ruin$upper
  )
)

# --- Write JSON using base R ---
format_val <- function(x) {
  if (length(x) > 1) {
    paste0("[", paste(sprintf("%.15e", x), collapse = ", "), "]")
  } else if (is.na(x)) {
    "null"
  } else {
    sprintf("%.15e", x)
  }
}

lines <- "{"
secs <- names(results)
for (i in seq_along(secs)) {
  sec_name <- secs[i]
  sec <- results[[sec_name]]
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
writeLines(lines, "/app/results.json")
cat("Results written to /app/results.json\n")
