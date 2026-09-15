#!/usr/bin/env Rscript

# Growth Assessment Engine (FIXED)
# Computes LMS-based z-scores and percentiles across growth charts
# with preterm chart routing, transition blending, and growth velocity

suppressPackageStartupMessages({
  library(jsonlite)
})

# ============================================================================
# LMS Core Functions
# ============================================================================

lms_zscore <- function(x, L, M, S) {
  if (is.na(x) || is.na(L) || is.na(M) || is.na(S)) return(NA_real_)
  if (M <= 0 || S <= 0 || x <= 0) return(NA_real_)
  # FIX: Handle L=0 special case
  if (abs(L) < 1e-10) {
    return(log(x / M) / S)
  }
  z <- ((x / M)^L - 1) / (L * S)
  return(z)
}

lms_value <- function(z, L, M, S) {
  if (is.na(z) || is.na(L) || is.na(M) || is.na(S)) return(NA_real_)
  if (abs(L) < 1e-10) {
    return(M * exp(S * z))
  }
  x <- M * (1 + L * S * z)^(1 / L)
  return(x)
}

zscore_to_percentile <- function(z) {
  if (is.na(z)) return(NA_real_)
  # FIX: Use lower tail (default), not upper tail
  return(pnorm(z))
}

# ============================================================================
# Data Loading and Interpolation
# ============================================================================

load_lms_data <- function(csv_path, chart_name, measure_name, gender_code) {
  all_data <- read.csv(csv_path, stringsAsFactors = FALSE)

  # FIX: Use gender_code directly — CSV data uses "m"/"f", not "male"/"female"
  subset_data <- all_data[all_data$chart == chart_name &
                          all_data$measure == measure_name &
                          all_data$gender == gender_code, ]

  if (nrow(subset_data) == 0) {
    return(NULL)
  }

  subset_data <- subset_data[order(subset_data$age), ]
  return(subset_data[, c("age", "age_units", "L", "M", "S")])
}

interpolate_lms <- function(age, lms_data) {
  if (is.null(lms_data) || nrow(lms_data) == 0) return(NULL)

  ages <- lms_data$age

  if (age < min(ages) || age > max(ages)) return(NULL)

  # FIX: Use linear interpolation instead of step-function
  L <- approx(ages, lms_data$L, xout = age, method = "linear")$y
  M <- approx(ages, lms_data$M, xout = age, method = "linear")$y
  S <- approx(ages, lms_data$S, xout = age, method = "linear")$y

  return(list(L = L, M = M, S = S))
}

# ============================================================================
# Chart Routing and Transition
# ============================================================================

pma_to_who_months <- function(pma_weeks) {
  # FIX: Correct conversion using 30.4375 days/month
  corrected_months <- (pma_weeks - 40) * 7 / 30.4375
  return(corrected_months)
}

blend_zscores <- function(z_fenton, z_who, pma_weeks) {
  if (is.na(z_fenton) && is.na(z_who)) return(NA_real_)
  if (is.na(z_fenton)) return(z_who)
  if (is.na(z_who)) return(z_fenton)

  if (pma_weeks <= 40) return(z_fenton)
  if (pma_weeks >= 50) return(z_who)

  # WHO weight increases from 0 at PMA=40 to 1 at PMA=50
  w_who <- (pma_weeks - 40) / 10
  w_fenton <- 1 - w_who

  return(w_fenton * z_fenton + w_who * z_who)
}

# ============================================================================
# Growth Assessment
# ============================================================================

assess_measurement <- function(measurement, data_dir) {
  sex <- measurement$sex
  measure_type <- measurement$measure_type
  value <- measurement$value
  ga_birth <- measurement$ga_birth
  pma_weeks <- measurement$pma_weeks

  charts_csv <- file.path(data_dir, "charts_long.csv")
  fenton_csv <- file.path(data_dir, "fenton2013.csv")

  result <- list(
    value = value,
    measure_type = measure_type,
    sex = sex,
    pma_weeks = pma_weeks,
    z_score = NA_real_,
    percentile = NA_real_,
    chart_used = NA_character_
  )

  if (ga_birth < 37 && pma_weeks <= 50) {
    # Preterm pathway: Fenton 2013, possibly blended with WHO
    fenton_data <- load_lms_data(fenton_csv, "fenton_2013", measure_type, sex)
    fenton_lms <- interpolate_lms(pma_weeks, fenton_data)

    z_fenton <- NA_real_
    if (!is.null(fenton_lms)) {
      z_fenton <- lms_zscore(value, fenton_lms$L, fenton_lms$M, fenton_lms$S)
    }

    if (pma_weeks >= 40) {
      # Transition zone: also compute WHO z-score and blend
      who_months <- pma_to_who_months(pma_weeks)
      who_data <- load_lms_data(charts_csv, "who_2006_infant", measure_type, sex)
      who_lms <- interpolate_lms(who_months, who_data)

      z_who <- NA_real_
      if (!is.null(who_lms)) {
        z_who <- lms_zscore(value, who_lms$L, who_lms$M, who_lms$S)
      }

      result$z_score <- blend_zscores(z_fenton, z_who, pma_weeks)
      result$chart_used <- "fenton_who_blend"
    } else {
      result$z_score <- z_fenton
      result$chart_used <- "fenton_2013"
    }
  } else {
    # Term or post-term pathway: use WHO 2006 infant chart
    who_months <- pma_to_who_months(pma_weeks)
    who_data <- load_lms_data(charts_csv, "who_2006_infant", measure_type, sex)
    who_lms <- interpolate_lms(who_months, who_data)

    if (!is.null(who_lms)) {
      result$z_score <- lms_zscore(value, who_lms$L, who_lms$M, who_lms$S)
      result$chart_used <- "who_2006_infant"
    }
  }

  result$percentile <- zscore_to_percentile(result$z_score)
  return(result)
}

# ============================================================================
# Growth Velocity
# ============================================================================

compute_velocities <- function(assessments) {
  velocities <- list()

  types <- unique(sapply(assessments, function(a) a$measure_type))

  for (mtype in types) {
    type_assessments <- Filter(function(a) a$measure_type == mtype, assessments)

    if (length(type_assessments) < 2) next

    for (i in 2:length(type_assessments)) {
      z_prev <- type_assessments[[i - 1]]$z_score
      z_curr <- type_assessments[[i]]$z_score
      pma_prev <- type_assessments[[i - 1]]$pma_weeks
      pma_curr <- type_assessments[[i]]$pma_weeks

      if (is.na(z_prev) || is.na(z_curr)) next

      delta_pma <- pma_curr - pma_prev
      if (delta_pma <= 0) next

      delta_z <- z_curr - z_prev
      delta_z_per_week <- delta_z / delta_pma

      flag <- "normal"
      if (delta_z_per_week < -0.1) {
        flag <- "rapid_loss"
      } else if (delta_z_per_week > 0.1) {
        flag <- "rapid_gain"
      }

      velocities[[length(velocities) + 1]] <- list(
        measure_type = mtype,
        from_pma = pma_prev,
        to_pma = pma_curr,
        delta_z = delta_z,
        delta_z_per_week = delta_z_per_week,
        flag = flag
      )
    }
  }

  return(velocities)
}

# ============================================================================
# Patient Processing
# ============================================================================

process_patient <- function(patient, data_dir) {
  assessments <- list()

  for (i in seq_along(patient$measurements)) {
    m <- patient$measurements[[i]]
    m$ga_birth <- patient$ga_birth
    m$sex <- patient$sex
    assessment <- assess_measurement(m, data_dir)
    assessments[[i]] <- assessment
  }

  crossings <- detect_crossings(assessments)
  velocities <- compute_velocities(assessments)

  return(list(
    patient_id = patient$id,
    ga_birth = patient$ga_birth,
    sex = patient$sex,
    assessments = assessments,
    crossings = crossings,
    velocities = velocities
  ))
}

detect_crossings <- function(assessments) {
  standard_z <- c(-1.88079, -1.28155, -0.67449, 0, 0.67449, 1.28155, 1.88079)
  standard_p <- c(3, 10, 25, 50, 75, 90, 97)

  crossings <- list()

  types <- unique(sapply(assessments, function(a) a$measure_type))

  for (mtype in types) {
    type_assessments <- Filter(function(a) a$measure_type == mtype, assessments)

    if (length(type_assessments) < 2) next

    for (i in 2:length(type_assessments)) {
      z_prev <- type_assessments[[i - 1]]$z_score
      z_curr <- type_assessments[[i]]$z_score

      if (is.na(z_prev) || is.na(z_curr)) next

      for (j in seq_along(standard_z)) {
        sz <- standard_z[j]
        if ((z_prev < sz && z_curr >= sz) || (z_prev >= sz && z_curr < sz)) {
          crossings[[length(crossings) + 1]] <- list(
            measure_type = mtype,
            from_pma = type_assessments[[i - 1]]$pma_weeks,
            to_pma = type_assessments[[i]]$pma_weeks,
            percentile_crossed = standard_p[j],
            direction = ifelse(z_curr > z_prev, "up", "down")
          )
        }
      }
    }
  }

  return(crossings)
}

# ============================================================================
# Main Entry Point
# ============================================================================

main <- function() {
  args <- commandArgs(trailingOnly = TRUE)

  if (length(args) < 3) {
    cat("Usage: Rscript growth_engine.R <data_dir> <input.json> <output.json>\n")
    quit(status = 1)
  }

  data_dir <- args[1]
  input_file <- args[2]
  output_file <- args[3]

  patients <- fromJSON(input_file, simplifyVector = FALSE)

  all_results <- list()
  for (i in seq_along(patients)) {
    all_results[[i]] <- process_patient(patients[[i]], data_dir)
  }

  output_json <- toJSON(all_results, auto_unbox = TRUE, pretty = TRUE, na = "null")
  writeLines(output_json, output_file)

  cat("Growth assessment complete. Results written to", output_file, "\n")
}

if (length(commandArgs(trailingOnly = TRUE)) >= 3) {
  main()
}
