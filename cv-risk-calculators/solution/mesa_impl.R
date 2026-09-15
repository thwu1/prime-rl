# MESA 2015 10-year CHD risk score (without CAC)
# Reference: McClelland et al., JACC 2015
#
# IMPLEMENTED: Full MESA CHD calculator using linear predictors

chd_10y_mesa <- function(race = "white", gender, age, totchol, hdl,
                          lipid_med, sbp, bp_med, smoker, diabetes,
                          fh_heartattack) {
  if (!race %in% c("aa", "white", "chinese", "hispanic")) {
    stop("race must be 'aa', 'white', 'chinese', or 'hispanic'")
  }

  if (!gender %in% c("male", "female")) {
    stop("gender must be either 'male' or 'female'")
  }

  coef <- read.csv("/app/data/mesa_coef.csv", stringsAsFactors = FALSE)

  race_chinese <- ifelse(race == "chinese", 1, 0)
  race_aa <- ifelse(race == "aa", 1, 0)
  race_hispanic <- ifelse(race == "hispanic", 1, 0)
  gender_male <- ifelse(gender == "male", 1, 0)

  indv_sum <- age * coef$age +
    gender_male * coef$gender_male +
    race_chinese * coef$race_chinese +
    race_aa * coef$race_aa +
    race_hispanic * coef$race_hispanic +
    diabetes * coef$diabetes +
    smoker * coef$smoker +
    totchol * coef$totchol +
    hdl * coef$hdl +
    lipid_med * coef$lipid_med +
    sbp * coef$sbp +
    bp_med * coef$bp_med +
    fh_heartattack * coef$fh_heartattack

  risk_score <- round((1 - (coef$baseline_survival^
    exp(indv_sum))) * 100, 2)

  ifelse(risk_score < 1, 1, ifelse(risk_score > 30, 30, risk_score))
}
