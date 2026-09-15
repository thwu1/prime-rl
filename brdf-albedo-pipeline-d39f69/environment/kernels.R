###############################################################################
# kernels.R - BRDF kernel functions for MCD43A1 albedo computation
#
# RossThick-LiSparseReciprocal BRDF Model
# Polynomial integration coefficients from Lucht et al. (2000)
#
# References:
#   Lucht, W., C.B. Schaaf, and A.H. Strahler (2000)
#   Schaaf, C.B. et al. (2002)
#   Wanner, W., X. Li, and A.H. Strahler (1995)
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
g1_vol <- 0.070987
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
  # Black-Sky Albedo (Directional-Hemispherical Reflectance)
  # Uses polynomial approximation of the angular integral
  bsa <- f_iso * (g0_iso + g1_iso * sza_deg^2 + g2_iso * sza_deg^3) +
         f_vol * (g0_vol + g1_vol * sza_deg^2 + g2_vol * sza_deg^3) +
         f_geo * (g0_geo + g1_geo * sza_deg^2 + g2_geo * sza_deg^3)
  return(bsa)
}

compute_wsa <- function(f_iso, f_vol, f_geo) {
  # White-Sky Albedo (Bihemispherical Reflectance)
  wsa <- f_iso * w_iso + f_vol * w_vol + f_geo * w_geo
  return(wsa)
}

diffuse_fraction <- function(tau, sza_deg, band) {
  # Diffuse skylight fraction based on optical depth, SZA, and band
  mu <- cos(sza_deg * pi / 180)
  coeff <- switch(band, vis = 3.14, nir = 1.75, shortwave = 2.44)
  return(1 - exp(-tau * coeff / mu))
}

compute_bluesky <- function(wsa, bsa, skyl) {
  # Blue-sky (actual) albedo: interpolation between BSA and WSA
  return(bsa * skyl + wsa * (1 - skyl))
}

compute_nbar <- function(f_iso, f_vol, f_geo, sza_deg) {
  # NBAR (Nadir BRDF-Adjusted Reflectance)
  # Evaluate the RossThick-LiSparseReciprocal BRDF at nadir view
  # for the given solar zenith angle.
  #
  # NBAR(SZA) = f_iso * K_iso_norm(0, SZA, 0)
  #           + f_vol * K_vol_norm(0, SZA, 0)
  #           + f_geo * K_geo_norm(0, SZA, 0)
  #
  # Kernels normalized to 0 at (VZA=0, SZA=0, RAA=0).
  # K_iso = 1.0 everywhere.
  # MODIS parameters: HB=2.0, BR=1.0
  return(NA)
}
