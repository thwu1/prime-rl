# MESA 2015 10-year CHD risk score (without CAC)
# Reference: McClelland et al., JACC 2015
#
# Uses traditional risk factors with race/ethnicity as dummy variables.
# Coefficients are in /app/data/mesa_coef.csv

chd_10y_mesa <- function(race = "white", gender, age, totchol, hdl,
                          lipid_med, sbp, bp_med, smoker, diabetes,
                          fh_heartattack) {
  # TODO: implement this calculator
  # Refer to mesa_cac.R for the structural pattern.
  return(NA)
}
