# fetal_biometry.R - Obstetric biometry analysis pipeline
# Implements Hadlock regression equations for estimated fetal weight (EFW),
# gestational age dating from ultrasound biometry, growth percentile
# classification using the Hadlock 1991 model, and reference chart auditing.
#

# ============================================================
# EFW Estimation Formulas
# Biometric measurements in centimeters, weight output in grams
# ============================================================

efw_hadlock_ac <- function(ac) {
  # Hadlock AC-only formula
  # Uses the natural-log form of the regression
  ln_efw <- 2.695 + 0.253 * ac - 0.00275 * ac^2
  10^ln_efw
}

efw_hadlock1 <- function(ac, fl) {
  # Hadlock 1 (AC, FL)
  log10_efw <- 1.304 + 0.05281 * ac + 0.1938 * fl - 0.004 * ac * fl
  10^log10_efw
}

efw_hadlock2 <- function(ac, bpd, fl) {
  # Hadlock 2 (AC, BPD, FL)
  log10_efw <- 1.335 - 0.0034 * ac * fl + 0.0316 * bpd + 0.0457 * ac + 0.1623 * fl
  10^log10_efw
}

efw_hadlock3 <- function(ac, hc, fl) {
  # Hadlock 3 (AC, HC, FL)
  log10_efw <- 1.326 - 0.00326 * ac * fl + 0.0438 * hc + 0.0107 * ac + 0.158 * fl
  10^log10_efw
}

efw_hadlock4 <- function(ac, hc, bpd, fl) {
  # Hadlock 4 (AC, HC, BPD, FL)
  log10_efw <- 1.3596 + 0.0064 * hc + 0.0424 * ac + 0.174 * fl +
    0.00061 * bpd * ac - 0.00386 * ac * fl
  10^log10_efw
}

# ============================================================
# Gestational Age Dating Formulas
# ============================================================

ga_from_crl <- function(crl_mm) {
  # Hadlock 1992 CRL dating - 4th degree polynomial
  # Input: CRL in millimeters
  crl_cm <- crl_mm
  ga_weeks <- exp(1.684969 + 0.315646 * crl_cm - 0.049306 * crl_cm^2 +
    0.004057 * crl_cm^3 - 0.000120456 * crl_cm^4)
  ga_weeks
}

ga_from_bpd <- function(bpd_cm) {
  # Hadlock BPD dating
  9.54 + 1.482 * bpd_cm + 0.1676 * bpd_cm^2
}

ga_from_hc <- function(hc_cm) {
  # Hadlock HC dating
  8.96 + 0.540 * hc_cm + 0.0003 * hc_cm^3
}

ga_from_fl <- function(fl_cm) {
  # Hadlock FL dating
  10.35 + 2.460 * fl_cm + 0.170 * fl_cm^2
}

ga_from_ac <- function(ac_cm) {
  # Hadlock AC dating
  8.14 + 0.753 * ac_cm + 0.0036 * ac_cm^2
}

composite_ga <- function(crl_mm = NA, bpd_cm = NA, hc_cm = NA,
                         fl_cm = NA, ac_cm = NA) {
  # Compute composite GA from all available dating parameters
  estimates <- c(
    if (!is.na(crl_mm)) ga_from_crl(crl_mm) else NA,
    if (!is.na(bpd_cm)) ga_from_bpd(bpd_cm) else NA,
    if (!is.na(hc_cm)) ga_from_hc(hc_cm) else NA,
    if (!is.na(fl_cm)) ga_from_fl(fl_cm) else NA,
    if (!is.na(ac_cm)) ga_from_ac(ac_cm) else NA
  )

  if (all(is.na(estimates))) return(NA)
  mean(estimates)
}

# ============================================================
# Hadlock 1991 Growth Model
# Mean EFW = exp(0.578 + 0.332*WGA - 0.00354*WGA^2)
# Log-normal distribution with constant SD on log scale
# ============================================================

hadlock_mean_efw <- function(wga) {
  exp(0.578 + 0.332 * wga - 0.00354 * wga^2)
}

hadlock_sd_log <- 0.012

compute_percentile <- function(efw, wga) {
  # Compute growth percentile using log-normal model
  mu_log <- log(hadlock_mean_efw(wga))
  z <- (log(efw) - mu_log) / hadlock_sd_log
  pnorm(z) * 100
}

classify_growth <- function(percentile) {
  if (is.na(percentile)) return(NA_character_)
  if (percentile < 10) return("SGA")
  if (percentile > 90) return("LGA")
  return("AGA")
}

# ============================================================
# Published Reference Chart (Hadlock 1991)
# EFW in grams by gestational age and percentile
# ============================================================

published_chart <- data.frame(
  WGA = 10:40,
  p3  = c(26,34,43,55,70,88,110,136,167,205,248,299,359,426,503,
          589,685,791,908,1034,1169,1313,1465,1622,1783,1946,2110,
          2271,2427,2576,2714),
  p10 = c(29,37,48,61,77,97,121,150,185,227,275,331,398,471,556,
          652,758,876,1004,1145,1294,1453,1621,1794,1973,2154,2335,
          2513,2686,2851,3004),
  p50 = c(35,45,58,73,93,117,146,181,223,273,331,399,478,568,670,
          785,913,1055,1210,1379,1559,1751,1953,2162,2377,2595,2813,
          3028,3236,3435,3619),
  p90 = c(41,53,68,85,109,137,171,212,261,319,387,467,559,665,784,
          918,1068,1234,1416,1613,1824,2049,2285,2530,2781,3036,3291,
          3543,3786,4019,4234),
  p97 = c(44,56,73,91,116,146,183,226,279,341,414,499,598,710,838,
          981,1141,1319,1513,1724,1649,2189,2441,2703,2971,3244,3516,
          3785,4045,4294,4524)
)

audit_chart <- function(threshold = 0.10) {
  # Compare published chart values against equation-derived values.
  # Flag entries where relative difference exceeds threshold.
  # Uses the Hadlock 1991 growth model parameters.
  errors <- list()
  for (i in 1:nrow(published_chart)) {
    wga <- published_chart$WGA[i]
    for (pct_name in c("p3", "p10", "p50", "p90", "p97")) {
      pct_val <- as.numeric(sub("p", "", pct_name)) / 100
      equation_val <- round(exp(log(hadlock_mean_efw(wga)) +
                                  qnorm(pct_val) * hadlock_sd_log))
      published_val <- published_chart[[pct_name]][i]

      if (abs(equation_val - published_val) / equation_val > threshold) {
        errors <- c(errors, list(list(
          wga = wga,
          column = pct_name,
          published = published_val,
          equation_derived = equation_val
        )))
      }
    }
  }
  errors
}
