#!/usr/bin/env Rscript
# run_pipeline.R - Process patient biometry data through the analysis pipeline
#

source("/app/fetal_biometry.R")
source("/app/doppler_surveillance.R")

# Read patient data
patients <- read.csv("/app/patients.csv", stringsAsFactors = FALSE)

results <- list()
results$patients <- list()

for (i in 1:nrow(patients)) {
  p <- patients[i, ]
  patient_result <- list()
  patient_result$id <- p$patient_id

  # -------------------------------------------------------
  # Compute EFW using all applicable Hadlock formula variants
  # -------------------------------------------------------
  efw <- list()

  if (!is.na(p$ac_cm)) {
    efw$hadlock_ac <- round(efw_hadlock_ac(p$ac_cm), 1)
  }

  if (!is.na(p$ac_cm) && !is.na(p$fl_cm)) {
    efw$hadlock1 <- round(efw_hadlock1(p$ac_cm, p$fl_cm), 1)
  }

  if (!is.na(p$ac_cm) && !is.na(p$bpd_cm) && !is.na(p$fl_cm)) {
    efw$hadlock2 <- round(efw_hadlock2(p$ac_cm, p$bpd_cm, p$fl_cm), 1)
  }

  if (!is.na(p$ac_cm) && !is.na(p$hc_cm) && !is.na(p$fl_cm)) {
    efw$hadlock3 <- round(efw_hadlock3(p$ac_cm, p$hc_cm, p$fl_cm), 1)
  }

  if (!is.na(p$ac_cm) && !is.na(p$hc_cm) && !is.na(p$bpd_cm) && !is.na(p$fl_cm)) {
    efw$hadlock4 <- round(efw_hadlock4(p$ac_cm, p$hc_cm, p$bpd_cm, p$fl_cm), 1)
  }

  patient_result$efw <- efw

  # -------------------------------------------------------
  # Compute composite gestational age dating
  # -------------------------------------------------------
  patient_result$composite_ga_weeks <- round(composite_ga(
    crl_mm = p$crl_mm,
    bpd_cm = p$bpd_cm,
    hc_cm  = p$hc_cm,
    fl_cm  = p$fl_cm,
    ac_cm  = p$ac_cm
  ), 2)

  # -------------------------------------------------------
  # Compute growth percentile using best available EFW estimate
  # Preference order: Hadlock 4 > 3 > 2 > 1 > AC-only
  # -------------------------------------------------------
  best_efw <- NA
  if (!is.null(efw$hadlock4)) best_efw <- efw$hadlock4
  else if (!is.null(efw$hadlock3)) best_efw <- efw$hadlock3
  else if (!is.null(efw$hadlock2)) best_efw <- efw$hadlock2
  else if (!is.null(efw$hadlock1)) best_efw <- efw$hadlock1
  else if (!is.null(efw$hadlock_ac)) best_efw <- efw$hadlock_ac

  if (!is.na(best_efw) && !is.na(p$known_ga_weeks)) {
    patient_result$growth_percentile <- round(
      compute_percentile(best_efw, p$known_ga_weeks), 2)
    patient_result$classification <- classify_growth(
      patient_result$growth_percentile)
  } else {
    patient_result$growth_percentile <- NA
    patient_result$classification <- NA
  }

  # -------------------------------------------------------
  # Doppler waveform analysis
  # -------------------------------------------------------
  if (!is.na(p$ua_psv) && !is.na(p$ua_edv) && !is.na(p$ua_mean_v)) {
    ua_indices <- compute_doppler_indices(p$ua_psv, p$ua_edv, p$ua_mean_v)
  } else {
    ua_indices <- NULL
  }

  if (is.list(ua_indices)) {
    # Compute MCA indices if available
    mca_pi <- NA
    if (!is.na(p$mca_psv) && !is.na(p$mca_edv) && !is.na(p$mca_mean_v)) {
      mca_indices <- compute_doppler_indices(p$mca_psv, p$mca_edv, p$mca_mean_v)
      if (is.list(mca_indices)) {
        mca_pi <- mca_indices$pi
      }
    }

    cpr_val <- compute_cpr(mca_pi, ua_indices$pi)

    # Compute UA PI z-score against reference norms
    ua_zscore <- compute_ua_pi_zscore(ua_indices$pi, p$known_ga_weeks)

    patient_result$doppler <- list(
      ua_sd  = ua_indices$sd,
      ua_ri  = ua_indices$ri,
      ua_pi  = ua_indices$pi,
      mca_pi = mca_pi,
      cpr    = if (!is.na(cpr_val)) round(cpr_val, 3) else NA,
      aedf   = ua_indices$aedf,
      redf   = ua_indices$redf,
      ua_pi_zscore = if (!is.na(ua_zscore)) round(ua_zscore, 2) else NA
    )
  } else {
    patient_result$doppler <- NA
  }

  # -------------------------------------------------------
  # Amniotic fluid index assessment
  # -------------------------------------------------------
  if (!is.na(p$afi_mm)) {
    afi_pct <- compute_afi_percentile(p$afi_mm, p$known_ga_weeks)
    patient_result$afi <- list(
      value_mm       = p$afi_mm,
      percentile     = if (!is.na(afi_pct)) round(afi_pct, 2) else NA,
      classification = classify_afi(afi_pct)
    )
  } else {
    patient_result$afi <- NA
  }

  results$patients[[i]] <- patient_result
}

# -------------------------------------------------------
# Audit the published reference chart
# -------------------------------------------------------
chart_errors <- audit_chart()
results$chart_audit <- list(
  errors_found = chart_errors,
  total_errors = length(chart_errors)
)

# Write results to JSON
library(jsonlite)
json_output <- toJSON(results, auto_unbox = TRUE, pretty = TRUE, na = "null")
writeLines(json_output, "/app/results.json")
cat("Pipeline complete. Results written to /app/results.json\n")
