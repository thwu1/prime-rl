#!/usr/bin/env Rscript

# Growth Assessment Engine
# Computes LMS-based z-scores and percentiles across growth charts

suppressPackageStartupMessages({
  library(jsonlite)
})

# ============================================================================
# LMS Core Functions
# ============================================================================

lms_zscore <- function(x, L, M, S) {
  if (is.na(x) || is.na(L) || is.na(M) || is.na(S)) return(NA_real_)
  if (M <= 0 || S <= 0 || x <= 0) return(NA_real_)
  z <- ((x / M)^L - 1) / (L * S)
  return(z)
}

lms_value <- function(z, L, M, S) {
  if (is.na(z) || is.na(L) || is.na(M) || is.na(S)) return(NA_real_)
  x <- M * (1 + L * S * z)^(1 / L)
  return(x)
}

zscore_to_percentile <- function(z) {
  if (is.na(z)) return(NA_real_)
  return(pnorm(z, lower.tail = FALSE))
}

# ============================================================================
# Data Loading and Interpolation
# ============================================================================

load_lms_data <- function(csv_path, chart_name, measure_name, gender_code) {
  all_data <- read.csv(csv_path, stringsAsFactors = FALSE)

  gender_full <- ifelse(gender_code == "m", "male", "female")
  subset_data <- all_data[all_data$chart == chart_name &
                          all_data$measure == measure_name &
                          all_data$gender == gender_full, ]

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

  L <- approx(ages, lms_data$L, xout = age, method = "constant")$y
  M <- approx(ages, lms_data$M, xout = age, method = "constant")$y
  S <- approx(ages, lms_data$S, xout = age, method = "constant")$y

  return(list(L = L, M = M, S = S))
}

# ============================================================================
# Age Conversion
# ============================================================================

pma_to_who_months <- function(pma_weeks) {
  corrected_months <- (pma_weeks - 40) / 4
  return(corrected_months)
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

  result <- list(
    value = value,
    measure_type = measure_type,
    sex = sex,
    pma_weeks = pma_weeks,
    z_score = NA_real_,
    percentile = NA_real_,
    chart_used = NA_character_
  )

  # Uses WHO chart for all patients
  who_months <- pma_to_who_months(pma_weeks)
  who_data <- load_lms_data(charts_csv, "who_2006_infant", measure_type, sex)
  who_lms <- interpolate_lms(who_months, who_data)

  if (!is.null(who_lms)) {
    result$z_score <- lms_zscore(value, who_lms$L, who_lms$M, who_lms$S)
    result$chart_used <- "who_2006_infant"
  }

  result$percentile <- zscore_to_percentile(result$z_score)
  return(result)
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

  return(list(
    patient_id = patient$id,
    ga_birth = patient$ga_birth,
    sex = patient$sex,
    assessments = assessments,
    crossings = crossings
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
