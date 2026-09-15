# ACC/AHA 2013 Pooled Cohort Equations - 10-year ASCVD risk
# Reference: Goff et al., JACC 2014
#
# FIXES APPLIED:
# 1. log(age)^2 instead of log(age^2) for ln_age_squared term
# 2. Corrected sbp_treated / sbp_untreated assignment

ascvd_10y_accaha <- function(race = "white", gender, age, totchol,
                              hdl, sbp, bp_med, smoker, diabetes) {
  if (!gender %in% c("male", "female")) {
    stop("gender must be either 'male' or 'female'")
  }

  age <- ifelse(!is.numeric(age) | age < 20 | age > 79, NA, age)
  totchol <- ifelse(!is.numeric(totchol) | totchol < 130 | totchol > 320, NA, totchol)
  hdl <- ifelse(!is.numeric(hdl) | hdl < 20 | hdl > 100, NA, hdl)
  sbp <- ifelse(!is.numeric(sbp) | sbp < 90 | sbp > 200, NA, sbp)

  coef_table <- read.csv("/app/data/accaha_coef.csv", stringsAsFactors = FALSE)
  race <- ifelse(race %in% c("white", "aa"), race, "white")
  coef <- coef_table[coef_table$race == race & coef_table$gender == gender, ]

  # FIX: bp_med == 1 means treated, bp_med == 0 means untreated
  sbp_treated <- ifelse(bp_med == 1, sbp, 1)
  sbp_untreated <- ifelse(bp_med == 0, sbp, 1)

  # FIX: log(age)^2 is (ln(age))^2, NOT log(age^2) which equals 2*ln(age)
  indv_sum <- log(age) * coef$ln_age +
    log(age)^2 * coef$ln_age_squared +
    log(totchol) * coef$ln_totchol +
    log(age) * log(totchol) * coef$ln_age_totchol +
    log(hdl) * coef$ln_hdl +
    log(age) * log(hdl) * coef$ln_age_hdl +
    log(sbp_treated) * coef$ln_treated_sbp +
    log(sbp_treated) * log(age) * coef$ln_age_treated_sbp +
    log(sbp_untreated) * coef$ln_untreated_sbp +
    log(sbp_untreated) * log(age) * coef$ln_age_untreated_sbp +
    smoker * coef$smoker +
    smoker * log(age) * coef$ln_age_smoker +
    diabetes * coef$diabetes

  risk_score <- round((1 - (coef$baseline_survival^
    exp(indv_sum - coef$group_mean))) * 100, 2)

  ifelse(risk_score < 1, 1, risk_score)
}
