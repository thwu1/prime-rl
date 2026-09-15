# Batch computation of all CV risk scores

source("/app/R/accaha.R")
source("/app/R/frs.R")
source("/app/R/frs_simple.R")
source("/app/R/mesa.R")
source("/app/R/mesa_cac.R")

compute_all_risks <- function(df) {
  n <- nrow(df)

  accaha_risk <- numeric(n)
  frs_risk <- numeric(n)
  frs_simple_risk <- numeric(n)
  mesa_risk <- numeric(n)
  mesa_cac_risk <- numeric(n)

  for (i in 1:n) {
    row <- df[i, ]

    accaha_risk[i] <- tryCatch(
      ascvd_10y_accaha(
        race = row$race, gender = row$gender, age = row$age,
        totchol = row$totchol, hdl = row$hdl, sbp = row$sbp,
        bp_med = row$bp_med, smoker = row$smoker, diabetes = row$diabetes
      ),
      error = function(e) NA
    )

    frs_risk[i] <- tryCatch(
      ascvd_10y_frs(
        gender = row$gender, age = row$age,
        hdl = row$hdl, totchol = row$totchol, sbp = row$sbp,
        bp_med = row$bp_med, smoker = row$smoker, diabetes = row$diabetes
      ),
      error = function(e) NA
    )

    frs_simple_risk[i] <- tryCatch(
      ascvd_10y_frs_simple(
        gender = row$gender, age = row$age,
        sbp = row$sbp,
        bp_med = row$bp_med, smoker = row$smoker, diabetes = row$diabetes
      ),
      error = function(e) NA
    )

    mesa_risk[i] <- tryCatch(
      chd_10y_mesa(
        race = row$race, gender = row$gender, age = row$age,
        totchol = row$totchol, hdl = row$hdl, lipid_med = row$lipid_med,
        sbp = row$sbp, bp_med = row$bp_med, smoker = row$smoker,
        diabetes = row$diabetes, fh_heartattack = row$fh_heartattack
      ),
      error = function(e) NA
    )

    mesa_cac_risk[i] <- tryCatch(
      chd_10y_mesa_cac(
        race = row$race, gender = row$gender, age = row$age,
        totchol = row$totchol, hdl = row$hdl, lipid_med = row$lipid_med,
        sbp = row$sbp, bp_med = row$bp_med, smoker = row$smoker,
        diabetes = row$diabetes, fh_heartattack = row$fh_heartattack
      ),
      error = function(e) NA
    )
  }

  df$accaha_risk <- accaha_risk
  df$frs_risk <- frs_risk
  df$frs_simple_risk <- frs_simple_risk
  df$mesa_risk <- mesa_risk
  df$mesa_cac_risk <- mesa_cac_risk

  return(df)
}
