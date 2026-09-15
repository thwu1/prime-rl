###############################################################################
# brdf_pipeline.R - MODIS MCD43A1 BRDF to Albedo Processing Pipeline
#
# Processes raw kernel parameters from MCD43A1 to compute:
#   - Black-Sky Albedo (BSA)
#   - White-Sky Albedo (WSA)
#   - Blue-Sky (Actual) Albedo
#   - NBAR (Nadir BRDF-Adjusted Reflectance)
###############################################################################

library(jsonlite)
source("/app/kernels.R")

# Read configuration
config <- fromJSON("/app/config.json")

# Read input data
data <- read.csv("/app/data/input_params.csv", stringsAsFactors = FALSE)

cat("Read", nrow(data), "observations from input file\n")

###############################################################################
# Step 1: Remove observations with fill values
###############################################################################

data <- data[data$f_iso_raw != config$fill_value &
             data$f_vol_raw != config$fill_value &
             data$f_geo_raw != config$fill_value, ]

cat("After fill value filter:", nrow(data), "observations\n")

###############################################################################
# Step 2: Filter by quality flags
###############################################################################

data <- data[!(data$quality %in% config$valid_quality), ]

cat("After quality filter:", nrow(data), "observations\n")

###############################################################################
# Step 3: Convert raw parameters to physical units
###############################################################################

data$f_iso <- data$f_iso_raw
data$f_vol <- data$f_vol_raw
data$f_geo <- data$f_geo_raw

###############################################################################
# Step 4: Compute albedo products for each observation
###############################################################################

sza <- config$solar_zenith_angle
tau <- config$optical_depth

results <- data.frame(
  pixel_id = data$pixel_id,
  band = data$band,
  lat = data$lat,
  lon = data$lon,
  date = data$date,
  f_iso = data$f_iso,
  f_vol = data$f_vol,
  f_geo = data$f_geo,
  bsa = NA_real_,
  wsa = NA_real_,
  bluesky = NA_real_,
  nbar = NA_real_,
  stringsAsFactors = FALSE
)

for (i in 1:nrow(results)) {
  fi <- results$f_iso[i]
  fv <- results$f_vol[i]
  fg <- results$f_geo[i]
  band <- results$band[i]

  results$bsa[i] <- compute_bsa(fi, fv, fg, sza)
  results$wsa[i] <- compute_wsa(fi, fv, fg)

  skyl <- diffuse_fraction(tau, sza, band)
  results$bluesky[i] <- compute_bluesky(results$wsa[i], results$bsa[i], skyl)

  results$nbar[i] <- compute_nbar(fi, fv, fg, sza)
}

###############################################################################
# Step 5: Write output
###############################################################################

dir.create("/app/output", showWarnings = FALSE, recursive = TRUE)
write.csv(results, config$output_file, row.names = FALSE)

cat("Pipeline complete. Output written to:", config$output_file, "\n")
