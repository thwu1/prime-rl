###############################################################################
# kernels.R - BRDF kernel functions for MCD43A1 albedo computation (FIXED)
#
# RossThick-LiSparseReciprocal BRDF Model
# Polynomial integration coefficients from Lucht et al. (2000)
###############################################################################


###############################################################################
# BSA polynomial coefficients (Black-Sky Albedo)
###############################################################################

# Isotropic kernel
g0_iso <- 1.0
g1_iso <- 0.0
g2_iso <- 0.0

# RossThick kernel (volumetric scattering)
g0_vol <- -0.007574
g1_vol <- -0.070987   # FIX: was +0.070987 (missing negative sign)
g2_vol <- 0.307588

# LiSparseReciprocal kernel (geometric-optical scattering)
g0_geo <- -1.284909
g1_geo <- -0.166314
g2_geo <- 0.041840

###############################################################################
# WSA coefficients (White-Sky Albedo)
###############################################################################

w_iso <- 1.0
w_vol <- 0.189184
w_geo <- -1.377622

###############################################################################
# Albedo computation functions
###############################################################################

compute_bsa <- function(f_iso, f_vol, f_geo, sza_deg) {
  # FIX: Convert solar zenith angle from degrees to radians
  sza_rad <- sza_deg * pi / 180
  bsa <- f_iso * (g0_iso + g1_iso * sza_rad^2 + g2_iso * sza_rad^3) +
         f_vol * (g0_vol + g1_vol * sza_rad^2 + g2_vol * sza_rad^3) +
         f_geo * (g0_geo + g1_geo * sza_rad^2 + g2_geo * sza_rad^3)
  return(bsa)
}

compute_wsa <- function(f_iso, f_vol, f_geo) {
  wsa <- f_iso * w_iso + f_vol * w_vol + f_geo * w_geo
  return(wsa)
}

diffuse_fraction <- function(tau, sza_deg, band) {
  mu <- cos(sza_deg * pi / 180)
  coeff <- switch(band, vis = 3.14, nir = 1.75, shortwave = 2.44)
  return(1 - exp(-tau * coeff / mu))
}

compute_bluesky <- function(wsa, bsa, skyl) {
  # FIX: Correct formula is WSA*skyl + BSA*(1-skyl)
  # Was: bsa*skyl + wsa*(1-skyl)
  return(wsa * skyl + bsa * (1 - skyl))
}

###############################################################################
# RossThick kernel evaluation (volumetric scattering)
###############################################################################

ross_thick_kernel <- function(vza_rad, sza_rad, raa_rad) {
  cos_vza <- cos(vza_rad)
  cos_sza <- cos(sza_rad)
  sin_vza <- sin(vza_rad)
  sin_sza <- sin(sza_rad)
  cos_raa <- cos(raa_rad)

  # Phase angle
  cos_xi <- cos_vza * cos_sza + sin_vza * sin_sza * cos_raa
  cos_xi <- max(-1.0, min(1.0, cos_xi))
  xi <- acos(cos_xi)
  sin_xi <- sin(xi)

  # RossThick kernel: normalized so integral is simple
  ross_element <- (pi / 2 - xi) * cos_xi + sin_xi
  denom <- cos_vza + cos_sza
  if (abs(denom) < 1e-20) denom <- 1e-20
  return(ross_element / denom)
}

###############################################################################
# LiSparse-Reciprocal kernel evaluation (geometric-optical scattering)
###############################################################################

li_sparse_recip_kernel <- function(vza_rad, sza_rad, raa_rad, HB = 2.0, BR = 1.0) {
  NEARLY_ZERO <- 1e-20

  # Original tangents
  tan_vza <- tan(vza_rad)
  tan_sza <- tan(sza_rad)

  # B/R transformation for ellipsoidal crown shape
  tan_vza_p <- BR * tan_vza
  tan_sza_p <- BR * tan_sza

  # Transformed angles (absolute value for stability)
  vza_p <- atan(abs(tan_vza_p))
  sza_p <- atan(abs(tan_sza_p))

  cos_vza_p <- cos(vza_p)
  sin_vza_p <- sin(vza_p)
  cos_sza_p <- cos(sza_p)
  sin_sza_p <- sin(sza_p)
  cos_raa <- cos(raa_rad)
  sin_raa <- sin(raa_rad)

  if (cos_vza_p == 0) cos_vza_p <- NEARLY_ZERO
  if (cos_sza_p == 0) cos_sza_p <- NEARLY_ZERO

  # Phase angle in transformed coordinates
  cos_xi_p <- cos_vza_p * cos_sza_p + sin_vza_p * sin_sza_p * cos_raa
  cos_xi_p <- max(-1.0, min(1.0, cos_xi_p))

  # Distance between projected centers
  D_sq <- tan_vza_p^2 + tan_sza_p^2 - 2 * tan_vza_p * tan_sza_p * cos_raa
  if (D_sq < 0) D_sq <- 0
  D <- sqrt(D_sq)

  # sec sum (1/cos_vza' + 1/cos_sza')
  temp <- 1.0 / cos_vza_p + 1.0 / cos_sza_p

  # H/B overlap computation
  cost_arg <- HB * sqrt(D^2 + tan_vza_p^2 * tan_sza_p^2 * sin_raa^2) / temp
  cost_arg <- max(-1.0, min(1.0, cost_arg))

  t_var <- acos(cost_arg)
  sint <- sin(t_var)
  overlap <- (1.0 / pi) * (t_var - sint * cost_arg) * temp
  if (overlap < 0) overlap <- 0

  # LiSparse Reciprocal kernel
  Li <- overlap - temp + 0.5 * (1 + cos_xi_p) / cos_vza_p / cos_sza_p
  return(Li)
}

###############################################################################
# NBAR computation via full kernel evaluation
###############################################################################

compute_nbar <- function(f_iso, f_vol, f_geo, sza_deg) {
  sza_rad <- sza_deg * pi / 180

  # Evaluate kernels at nadir view (VZA=0, RAA=0) for given SZA
  k_vol <- ross_thick_kernel(0.0, sza_rad, 0.0)
  k_geo <- li_sparse_recip_kernel(0.0, sza_rad, 0.0)

  # Evaluate kernels at nadir-nadir reference point for normalization
  k_vol_0 <- ross_thick_kernel(0.0, 0.0, 0.0)
  k_geo_0 <- li_sparse_recip_kernel(0.0, 0.0, 0.0)

  # Normalized kernels (zero at nadir-nadir)
  k_vol_norm <- k_vol - k_vol_0
  k_geo_norm <- k_geo - k_geo_0

  # NBAR = f_iso * 1.0 + f_vol * K_vol_norm + f_geo * K_geo_norm
  return(f_iso + f_vol * k_vol_norm + f_geo * k_geo_norm)
}
