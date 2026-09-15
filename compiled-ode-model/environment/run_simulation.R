# Robertson Chemical Kinetics - deSolve simulation driver

library(deSolve)

# Load the pre-compiled shared library
dyn.load("/app/robertson.so")

# Parameters
parms <- c(k1 = 0.04, k2 = 1e4, k3 = 3e7)

# Initial conditions
yini <- c(y1 = 1.0, y2 = 0.0, y3 = 0.0)

# Output times (must include event times)
times <- sort(unique(c(0, 0.4 * 10^(0:8), 500, 2000)))

# Read forcing data for rate modulation
forc_data <- read.csv("/app/forcing_data.csv")

# Events: inject additional reactant at specified times
event_data <- data.frame(
  var    = c("y1", "y1"),
  time   = c(500, 2000),
  value  = c(0.2, 0.3),
  method = c("replace", "replace")
)

# Solve the system
out <- ode(
  y         = yini,
  times     = times,
  func      = "derivs",
  parms     = parms,
  dllname   = "robertson",
  initfunc  = "initmod",
  nout      = 1,
  outnames  = "Sum",
  events    = list(data = event_data)
)

# Write results
result_df <- data.frame(
  time = out[, "time"],
  y1   = out[, "y1"],
  y2   = out[, "y2"],
  y3   = out[, "y3"]
)
write.csv(result_df, "/app/results.csv", row.names = FALSE)

cat("Simulation complete. Results written to /app/results.csv\n")

dyn.unload("/app/robertson.so")
