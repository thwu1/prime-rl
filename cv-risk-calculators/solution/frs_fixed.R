# Framingham 2008 ASCVD risk score (with lab measurement)
# Reference: D'Agostino et al., Circulation 2008
#
# FIX: Added group_mean centering in the exponent

ascvd_10y_frs <- function(gender, age, hdl, totchol, sbp,
                           bp_med, smoker, diabetes) {
  gender <- tolower(gender)
  gender <- ifelse(gender == "m", "male", gender)
  gender <- ifelse(gender == "f", "female", gender)

  if (!gender %in% c("male", "female")) {
    stop("gender must be either 'male' or 'female'")
  }

  if (!is.numeric(age)) {
    stop("age must be a valid numeric value")
  }

  age <- ifelse(age < 30 | age > 74, NA, age)

  coef <- read.csv("/app/data/frs_coef.csv", stringsAsFactors = FALSE)
  coef <- coef[coef$gender == gender, ]

  sbp_treated <- ifelse(bp_med == 1, sbp, 1)
  sbp_untreated <- ifelse(bp_med == 0, sbp, 1)

  indv_sum <- log(age) * coef$ln_age +
    log(hdl) * coef$ln_hdl +
    log(totchol) * coef$ln_totchol +
    log(sbp_treated) * coef$ln_treated_sbp +
    log(sbp_untreated) * coef$ln_untreated_sbp +
    smoker * coef$smoker +
    diabetes * coef$diabetes

  # FIX: subtract group_mean before exponentiating
  risk_score <- round((1 - (coef$baseline_survival^
    exp(indv_sum - coef$group_mean))) * 100, 2)

  ifelse(risk_score < 1, 1, risk_score)
}
