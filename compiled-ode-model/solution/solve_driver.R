# Extended Robertson Reaction System — Solver with Benchmark
#

library(deSolve)

# Compile and load the C model
system("cd /app && R CMD SHLIB robertson_ext.c")
dyn.load("/app/robertson_ext.so")

# ── Parameters ──────────────────────────────────────────────────────
parms <- c(k1 = 0.04, k2 = 1e4, k3 = 3e7, k4 = 1e-3)
yini  <- c(y1 = 1.0, y2 = 0.0, y3 = 0.0, y4 = 0.0)
times <- sort(unique(c(0, 0.4 * 10^(0:8), 500, 2000)))

# ── Forcing data ────────────────────────────────────────────────────
forc_data  <- read.csv("/app/forcing_data.csv")
forc_table <- as.matrix(forc_data)

# ── Events: ADD material to y1 ──────────────────────────────────────
event_data <- data.frame(
  var    = c("y1", "y1"),
  time   = c(500, 2000),
  value  = c(0.2, 0.3),
  method = c("add", "add")
)

# ── Common arguments for all solver calls ───────────────────────────
common <- list(
  y        = yini,
  times    = times,
  func     = "derivs",
  parms    = parms,
  dllname  = "robertson_ext",
  initfunc = "initmod",
  initforc = "initforc",
  forcings = list(forc_table),
  events   = list(data = event_data),
  nout     = 1,
  outnames = "Sum"
)

# ── Benchmark: run 3 configurations ────────────────────────────────
run_config <- function(extra_args) {
  tryCatch({
    out  <- do.call(ode, c(common, extra_args))
    ist  <- attr(out, "istate")
    list(out = out, nsteps = ist[2], nfevls = ist[3], njevls = ist[4])
  }, error = function(e) {
    list(out = NULL, nsteps = NA, nfevls = NA, njevls = NA)
  })
}

# Config 1: lsoda with internal (numerical) Jacobian
cfg1 <- run_config(list(
  method = "lsoda",
  atol   = c(1e-8, 1e-14, 1e-8, 1e-8),
  rtol   = 1e-8
))

# Config 2: lsoda with analytical Jacobian
cfg2 <- run_config(list(
  method  = "lsoda",
  jacfunc = "jac",
  jactype = "fullusr",
  atol    = c(1e-8, 1e-14, 1e-8, 1e-8),
  rtol    = 1e-8
))

# Config 3: vode (BDF, always stiff) with analytical Jacobian
cfg3 <- run_config(list(
  method  = "vode",
  jacfunc = "jac",
  jactype = "fullusr",
  atol    = c(1e-8, 1e-14, 1e-8, 1e-8),
  rtol    = 1e-8
))

configs <- list(
  lsoda_numjac = cfg1,
  lsoda_anajac = cfg2,
  vode_anajac  = cfg3
)

# ── Write benchmark CSV ────────────────────────────────────────────
bench_df <- data.frame(
  solver = names(configs),
  nsteps = sapply(configs, function(x) x$nsteps),
  nfevls = sapply(configs, function(x) x$nfevls),
  njevls = sapply(configs, function(x) x$njevls),
  row.names = NULL
)
write.csv(bench_df, "/app/benchmark.csv", row.names = FALSE)
cat("Benchmark results:\n")
print(bench_df)

# ── Select best: lowest nfevls among successful runs ───────────────
best_name   <- NULL
best_nfevls <- Inf
for (nm in names(configs)) {
  cfg <- configs[[nm]]
  if (!is.null(cfg$out) && !is.na(cfg$nfevls) && cfg$nfevls < best_nfevls) {
    best_name   <- nm
    best_nfevls <- cfg$nfevls
  }
}
if (is.null(best_name)) stop("All solver configurations failed")

cat(sprintf("\nSelected solver: %s (nfevls = %d)\n", best_name, best_nfevls))

best_out <- configs[[best_name]]$out

# ── Write results CSV ──────────────────────────────────────────────
result_df <- data.frame(
  time = best_out[, "time"],
  y1   = best_out[, "y1"],
  y2   = best_out[, "y2"],
  y3   = best_out[, "y3"],
  y4   = best_out[, "y4"]
)
write.csv(result_df, "/app/results.csv", row.names = FALSE)

dyn.unload("/app/robertson_ext.so")
cat("Results written to /app/results.csv\n")
