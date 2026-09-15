# Modified Robertson Chemical Kinetics - deSolve compiled C model driver
#

library(deSolve)

# --- Compile and load the C shared library ---
system("cd /app && R CMD SHLIB robertson.c")
dyn.load("/app/robertson.so")

# --- Parameters ---
parms <- c(k1 = 0.04, k2 = 1e4, k3 = 3e7)

# --- Initial conditions ---
yini <- c(y1 = 1.0, y2 = 0.0, y3 = 0.0)

# --- Output times (must include event times) ---
times <- sort(unique(c(0, 0.4 * 10^(0:8), 500, 2000)))

# --- Forcing function data ---
forc_data <- read.csv("/app/forcing_data.csv")
forc_table <- as.matrix(forc_data)

# --- Event data frame: add reactant to y1 ---
event_data <- data.frame(
  var    = c("y1", "y1"),
  time   = c(500, 2000),
  value  = c(0.2, 0.3),
  method = c("add", "add")
)

# --- Solve the system ---
out <- ode(
  y         = yini,
  times     = times,
  func      = "derivs",
  parms     = parms,
  dllname   = "robertson",
  initfunc  = "initmod",
  jacfunc   = "jac",
  jactype   = "fullusr",
  initforc  = "initforc",
  forcings  = list(forc_table),
  events    = list(data = event_data),
  atol      = c(1e-8, 1e-14, 1e-8),
  rtol      = 1e-8,
  nout      = 1,
  outnames  = "Sum"
)

# --- Write results ---
result_df <- data.frame(
  time = out[, "time"],
  y1   = out[, "y1"],
  y2   = out[, "y2"],
  y3   = out[, "y3"]
)
write.csv(result_df, "/app/results.csv", row.names = FALSE)

# --- Cleanup ---
dyn.unload("/app/robertson.so")

cat("Simulation complete. Results written to /app/results.csv\n")
