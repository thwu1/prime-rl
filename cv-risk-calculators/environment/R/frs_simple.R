# Framingham 2008 ASCVD risk score (no lab / BMI-based)
# Reference: D'Agostino et al., Circulation 2008
#
# Uses BMI instead of cholesterol measurements for risk estimation.
# Coefficients are in /app/data/frs_simple_coef.csv

ascvd_10y_frs_simple <- function(gender, age, bmi, sbp,
                                  bp_med, smoker, diabetes) {
  # TODO: implement this calculator
  # Should follow the same general approach as the lab-based Framingham
  # calculator in frs.R, but using BMI-based coefficients.
  return(NA)
}
