#!/usr/bin/env python3
"""
Fix all 11 bugs and implement 3 stubs in the obstetric biometry and
surveillance pipeline.

FETAL_BIOMETRY.R BUGS:
  1. ga_from_crl: crl_cm <- crl_mm must divide by 10 (mm -> cm conversion).
  2. efw_hadlock_ac: 10^ln_efw must be exp(ln_efw) (formula produces Ln, not Log10).
  3. efw_hadlock3: HC coeff (0.0107) and AC coeff (0.0438) are swapped.
  4. hadlock_sd_log: 0.012 must be 0.12 (published CV ~12%, not ~1.2%).
     This also fixes the chart audit, which uses hadlock_sd_log to compute
     equation-derived reference values.
  5. published_chart p97 at WGA=30: 1649 must be 1949 (transcription error).
  6. composite_ga mean(): must use na.rm = TRUE to handle missing parameters.

DOPPLER_SURVEILLANCE.R BUGS:
  7. compute_doppler_indices RI: (psv + edv) / psv must be (psv - edv) / psv.
  8. compute_cpr: ua_pi / mca_pi must be mca_pi / ua_pi.
  9. compute_doppler_indices AEDF guard: if (edv <= 0) return(NA) silently
     drops all Doppler data. Must detect AEDF/REDF, set flags, compute
     available indices, and set S/D to NA.
  10. arduini_ua_pi_mean: quadratic coefficient +0.000100 must be -0.000100
      (UA PI decreases with GA as placental resistance falls).

STUBS TO IMPLEMENT:
  11. compute_afi_percentile: log-normal fit to p5/p95 anchors with GA interp.
  12. classify_afi: oligohydramnios/polyhydramnios/normal from percentile.
  13. compute_ua_pi_zscore: z-score against Arduini & Rizzo reference polynomial.

"""

# ============================================================
# Fix fetal_biometry.R (6 bugs)
# ============================================================

with open('/app/fetal_biometry.R', 'r') as f:
    bio_code = f.read()

# Bug 1: CRL unit conversion (mm -> cm)
bio_code = bio_code.replace(
    'crl_cm <- crl_mm\n',
    'crl_cm <- crl_mm / 10\n'
)

# Bug 2: AC-only formula log base (10^ -> exp)
bio_code = bio_code.replace(
    '10^ln_efw',
    'exp(ln_efw)'
)

# Bug 3: Hadlock-3 HC/AC coefficient swap
bio_code = bio_code.replace(
    '1.326 - 0.00326 * ac * fl + 0.0438 * hc + 0.0107 * ac + 0.158 * fl',
    '1.326 - 0.00326 * ac * fl + 0.0107 * hc + 0.0438 * ac + 0.158 * fl'
)

# Bug 4: Growth model SD value (also fixes the chart audit which references this)
bio_code = bio_code.replace(
    'hadlock_sd_log <- 0.012',
    'hadlock_sd_log <- 0.12'
)

# Bug 5: Published chart transcription error at WGA=30, p97
bio_code = bio_code.replace(
    '1649,2189',
    '1949,2189'
)

# Bug 6: Composite GA NA handling
bio_code = bio_code.replace(
    'mean(estimates)',
    'mean(estimates, na.rm = TRUE)'
)

with open('/app/fetal_biometry.R', 'w') as f:
    f.write(bio_code)

print("Fixed 6 bugs in /app/fetal_biometry.R")

# ============================================================
# Fix doppler_surveillance.R (4 bugs + 3 stub implementations)
# ============================================================

with open('/app/doppler_surveillance.R', 'r') as f:
    dop_code = f.read()

# Bug 7 + Bug 9: Replace entire compute_doppler_indices function
# Fixes RI sign error AND AEDF/REDF guard
old_doppler_fn = '''compute_doppler_indices <- function(psv, edv, mean_v) {
  # Compute standard Doppler waveform indices from velocity measurements.
  # Returns a list with S/D ratio, resistance index, pulsatility index,
  # and AEDF/REDF flags.
  if (is.na(psv) || is.na(edv) || is.na(mean_v)) return(NULL)

  # Guard against non-positive end-diastolic flow
  if (edv <= 0) return(NA)

  sd_ratio <- psv / edv
  ri <- (psv + edv) / psv
  pi_val <- (psv - edv) / mean_v

  list(sd = round(sd_ratio, 3),
       ri = round(ri, 3),
       pi = round(pi_val, 3),
       aedf = FALSE,
       redf = FALSE)
}'''

new_doppler_fn = '''compute_doppler_indices <- function(psv, edv, mean_v) {
  # Compute standard Doppler waveform indices from velocity measurements.
  # Returns a list with S/D ratio, resistance index, pulsatility index,
  # and AEDF/REDF flags.
  if (is.na(psv) || is.na(edv) || is.na(mean_v)) return(NULL)

  # Detect absent or reversed end-diastolic flow
  aedf_flag <- (edv == 0)
  redf_flag <- (edv < 0)

  # S/D ratio: only defined for positive EDV
  sd_ratio <- if (edv > 0) round(psv / edv, 3) else NA

  # RI = (S - D) / S: always computable
  ri <- round((psv - edv) / psv, 3)

  # PI = (S - D) / Mean: always computable
  pi_val <- round((psv - edv) / mean_v, 3)

  list(sd = sd_ratio,
       ri = ri,
       pi = pi_val,
       aedf = aedf_flag,
       redf = redf_flag)
}'''

dop_code = dop_code.replace(old_doppler_fn, new_doppler_fn)

# Bug 8: CPR inversion
dop_code = dop_code.replace(
    'ua_pi / mca_pi',
    'mca_pi / ua_pi'
)

# Bug 10: Arduini & Rizzo UA PI mean polynomial sign error
dop_code = dop_code.replace(
    '+ 0.000100 * ga_weeks^2',
    '- 0.000100 * ga_weeks^2'
)

# Stub 11: Implement compute_afi_percentile
dop_code = dop_code.replace(
    'NA  # STUB: compute_afi_percentile implementation required',
    '''if (is.na(afi_mm) || is.na(ga_weeks)) return(NA)
  if (ga_weeks < 16 || ga_weeks > 42) return(NA)

  # Interpolate reference values for non-integer GA
  ga_lo <- floor(ga_weeks)
  ga_hi <- ceiling(ga_weeks)

  if (ga_lo == ga_hi) {
    idx <- which(afi_reference$ga_weeks == ga_lo)
    if (length(idx) == 0) return(NA)
    p5_val <- afi_reference$p5[idx]
    p95_val <- afi_reference$p95[idx]
  } else {
    idx_lo <- which(afi_reference$ga_weeks == ga_lo)
    idx_hi <- which(afi_reference$ga_weeks == ga_hi)
    if (length(idx_lo) == 0 || length(idx_hi) == 0) return(NA)
    frac <- ga_weeks - ga_lo
    p5_val <- afi_reference$p5[idx_lo] + frac * (afi_reference$p5[idx_hi] - afi_reference$p5[idx_lo])
    p95_val <- afi_reference$p95[idx_lo] + frac * (afi_reference$p95[idx_hi] - afi_reference$p95[idx_lo])
  }

  # Fit log-normal distribution using 5th and 95th percentile anchors
  z_crit <- qnorm(0.95)
  mu <- (log(p5_val) + log(p95_val)) / 2
  sigma <- (log(p95_val) - log(p5_val)) / (2 * z_crit)

  # Compute percentile of observed value
  z <- (log(afi_mm) - mu) / sigma
  pnorm(z) * 100'''
)

# Stub 12: Implement classify_afi
dop_code = dop_code.replace(
    'NA  # STUB: classify_afi implementation required',
    '''if (is.na(percentile)) return(NA_character_)
  if (percentile < 5) return("oligohydramnios")
  if (percentile > 95) return("polyhydramnios")
  return("normal")'''
)

# Stub 13: Implement compute_ua_pi_zscore
dop_code = dop_code.replace(
    'NA  # STUB: compute_ua_pi_zscore implementation required',
    '''if (is.na(observed_pi) || is.na(ga_weeks)) return(NA)
  if (ga_weeks < 20 || ga_weeks > 42) return(NA)

  ref_mean <- arduini_ua_pi_mean(ga_weeks)
  ref_sd <- arduini_ua_pi_sd(ga_weeks)
  if (ref_sd <= 0) return(NA)

  (observed_pi - ref_mean) / ref_sd'''
)

with open('/app/doppler_surveillance.R', 'w') as f:
    f.write(dop_code)

print("Fixed 4 bugs and implemented 3 stubs in /app/doppler_surveillance.R")
print("All fixes applied successfully.")
