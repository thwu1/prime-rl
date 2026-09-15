#!/usr/bin/env Rscript
#
# Parameter validation helper for tests

library(jsonlite)
source("/app/pk_simulator.R")

results <- list()

# Body composition
results$lbm_male_170_70 <- james_lbm(170, 70, "m")
results$lbm_female_155_55 <- james_lbm(155, 55, "f")
results$lbm_female_165_65 <- james_lbm(165, 65, "f")
results$ffm_ref_male <- alsallami_ffm(35, 170, 70, "m")

# Schnider (40yo, 70kg, 170cm, male)
sp <- schnider_params(40, 70, 170, "m")
results$schnider_v1 <- sp$v1
results$schnider_v2 <- sp$v2
results$schnider_k10 <- sp$k10
results$schnider_k12 <- sp$k12
results$schnider_k21 <- sp$k21
results$schnider_k31 <- sp$k31

# Marsh (70kg)
mp <- marsh_params(70)
results$marsh_v1 <- mp$v1
results$marsh_k10 <- mp$k10

# Eleveld at reference point - female (35yo, 70kg, 170cm)
ep_f <- eleveld_propofol_params(35, 70, 170, "f")
results$eleveld_female_k10 <- ep_f$k10

# Eleveld at reference point - male (35yo, 70kg, 170cm)
ep_m <- eleveld_propofol_params(35, 70, 170, "m")
results$eleveld_male_k10 <- ep_m$k10

# Minto (50yo, 65kg, 165cm, female)
mtp <- minto_params(50, 65, 165, "f")
results$minto_ke0 <- mtp$ke0
results$minto_v1 <- mtp$v1
results$minto_cl1 <- mtp$k10 * mtp$v1

cat(toJSON(results, auto_unbox = TRUE))
