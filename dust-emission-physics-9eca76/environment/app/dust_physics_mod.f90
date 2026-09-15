! dust_physics_mod.f90
! FENGSHA windblown dust emission physics module
! Based on the CMAQ v5.4 implementation following:
!   Foroutan et al. (2017), J. Adv. Model. Earth Syst., 9, 585-608
!   doi:10.1002/2016MS000823
!

module dust_physics_mod
  implicit none
  private

  ! ---- Physical constants ----
  real, parameter, public :: GRAV = 9.81            ! gravitational acceleration [m/s^2]
  real, parameter, public :: VON_KARMAN = 0.4       ! von Karman constant
  real, parameter, public :: RHO_PARTICLE = 2650.0  ! soil particle density [kg/m^3]
  real, parameter, public :: RHO_WATER = 1000.0     ! water density [kg/m^3]
  real, parameter, public :: RHO_BULK_LS = 1000.0   ! bulk density for Lu-Shao V/H ratio [kg/m^3]

  ! Shao-Lu (2000) threshold velocity parameters
  real, parameter, public :: A_N = 0.0123           ! threshold parameter [-]
  real, parameter, public :: GAMMA_COH = 1.65e-4    ! interparticle cohesion [kg/s^2]

  ! Saltation constant
  real, parameter, public :: WHITE_C = 1.0          ! White (1979) constant [-]

  ! ---- Soil texture categories ----
  integer, parameter, public :: N_TEXTURES = 4
  ! Mean mass median diameters [m]
  ! Chatenet et al. (1996), Menut et al. (2013), Table 2 of Foroutan (2017)
  real, parameter, public :: DP_SIZES(N_TEXTURES) = &
    (/ 690.0e-6, 210.0e-6, 125.0e-6, 2.0e-6 /)

  ! Erodibility potentials mapped to texture categories
  ! CMAQ convention: clay=0.08, silt=1.00, sand=0.12
  ! Order: coarse_sand, fine_med_sand, silt, clay
  real, parameter, public :: EROPOT(N_TEXTURES) = (/ 0.12, 0.12, 1.00, 0.08 /)

  ! ---- Drag partition parameters ----
  ! Raupach et al. (1993), Xi and Sokolik (2015)
  ! Eq. (5) of Foroutan et al. (2017)
  real, parameter :: SIG_V = 1.45
  real, parameter :: M_V_PARAM = 0.16
  real, parameter :: BETA_V = 202.0
  real, parameter :: SIG_S = 1.0
  real, parameter :: M_S_PARAM = 0.5
  real, parameter :: BETA_S = 90.0

  ! ---- Land type parameters ----
  ! 1=shrubland, 2=shrubgrass, 3=barren, 4=cropland
  ! Table 1 of Foroutan et al. (2017), Darmenova et al. (2009)
  integer, parameter, public :: N_LANDTYPES = 4
  real, parameter, public :: LAMBDA_S_TABLE(N_LANDTYPES) = &
    (/ 0.03, 0.04, 0.0001, 0.15 /)
  real, parameter, public :: H_S_TABLE(N_LANDTYPES) = &
    (/ 0.02, 0.02, 0.02, 0.02 /)
  ! Vegetation heights (July values from Table 1)
  real, parameter, public :: H_V_TABLE(N_LANDTYPES) = &
    (/ 0.10, 0.12, 0.10, 0.50 /)

  ! ---- Lu-Shao (1999) vertical flux ratio parameters ----
  ! By parent soil type: 1=sand, 2=loam, 3=sandy_clay_loam, 4=clay
  ! Following Kang et al. (2011) as implemented in CMAQ
  integer, parameter, public :: N_SOILTYPES = 4
  real, parameter, public :: P_PLASTIC(N_SOILTYPES) = &
    (/ 5000.0, 10000.0, 10000.0, 30000.0 /)
  real, parameter, public :: C_ALPHA_LS(N_SOILTYPES) = &
    (/ 0.001, 0.0006, 0.0006, 0.0002 /)
  real, parameter, public :: F_FINE(N_SOILTYPES) = &
    (/ 0.06, 0.18, 0.32, 0.72 /)
  real, parameter, public :: C_BETA_LS(N_SOILTYPES) = &
    (/ 2.09, 2.09, 2.09, 2.09 /)

  public :: compute_emission_cell

contains

  ! ================================================================
  ! Ideal threshold friction velocity u*_t0 (Shao and Lu, 2000)
  ! Eq. (2) of Foroutan et al. (2017):
  !   u*_t0(D) = sqrt( A_N * (rho_p * g * D / rho_a + Gamma / (rho_a * D)) )
  ! ================================================================
  real function threshold_fric_vel(dp, rho_a)
    real, intent(in) :: dp     ! particle diameter [m]
    real, intent(in) :: rho_a  ! air density [kg/m^3]

    threshold_fric_vel = sqrt(A_N * (RHO_PARTICLE * GRAV * dp / rho_a))
  end function

  ! ================================================================
  ! Soil moisture correction factor f_m (Fecan et al., 1999)
  ! Eqs. (3)-(4) of Foroutan et al. (2017):
  !   w' = 0.0014 * (%clay)^2 + 0.17 * (%clay)
  !   f_m = 1.0                                    if w <= w'
  !   f_m = sqrt(1.0 + 1.21 * (w - w')^0.68)      if w >  w'
  ! where w and w' are gravimetric soil moisture in percent.
  ! ================================================================
  real function moisture_factor(w_grav_pct, clay_pct)
    real, intent(in) :: w_grav_pct  ! gravimetric soil moisture [%]
    real, intent(in) :: clay_pct    ! clay content [%]
    real :: w_prime

    w_prime = 0.14 * clay_pct * clay_pct + 0.17 * clay_pct

    if (w_grav_pct <= w_prime) then
      moisture_factor = 1.0
    else
      moisture_factor = sqrt(1.0 + 1.21 * (w_grav_pct - w_prime)**0.68)
    end if
  end function

  ! ================================================================
  ! Double drag partitioning correction f_r
  ! Eq. (5) of Foroutan et al. (2017):
  !   f_r = sqrt( (1 - sig_V*m_V*lam_V) * (1 + beta_V*m_V*lam_V) *
  !               (1 - sig_S*m_S*lam_S/(1-Av)) * (1 + beta_S*m_S*lam_S/(1-Av)) )
  ! Returns 10.0 (maximum suppression) if the argument is <= 1.
  ! ================================================================
  real function drag_partition(lambda_v, lambda_s_val, veg_frac)
    real, intent(in) :: lambda_v, lambda_s_val, veg_frac
    real :: fr_sq, veg_free

    veg_free = max(1.0 - veg_frac, 0.01)

    fr_sq = (1.0 + SIG_V * M_V_PARAM * lambda_v)  &
          * (1.0 + BETA_V * M_V_PARAM * lambda_v)  &
          * (1.0 - SIG_S * M_S_PARAM * lambda_s_val / veg_free) &
          * (1.0 + BETA_S * M_S_PARAM * lambda_s_val / veg_free)

    if (fr_sq > 1.0) then
      drag_partition = sqrt(fr_sq)
    else
      drag_partition = 10.0
    end if
  end function

  ! ================================================================
  ! Surface roughness length z0 (Foroutan et al., 2017)
  ! Eq. (8) of Foroutan et al. (2017):
  !   z0 / h = 0.96 * lambda^1.07      for lambda <  0.2
  !   z0 / h = 0.083 * lambda^(-0.46)  for lambda >= 0.2
  ! where lambda is the total roughness density and h is the
  ! effective roughness element height.
  ! ================================================================
  real function surface_roughness(lambda_total, h_eff)
    real, intent(in) :: lambda_total, h_eff

    if (lambda_total < 0.045) then
      surface_roughness = 0.96 * lambda_total**1.07 * h_eff
    else
      surface_roughness = 0.083 * lambda_total**0.46 * h_eff
    end if
  end function

  ! ================================================================
  ! Horizontal saltation flux per particle size (White, 1979)
  ! Eq. (10) of Foroutan et al. (2017):
  !   F_H = c * (rho_a / g) * u*^3 * (1 - u*t/u*) * (1 + u*t/u*)^2
  ! Equivalently: c * (rho_a / g) * (u* + u*t) * (u*^2 - u*t^2)
  ! Returns 0 when u* <= u*t.
  ! ================================================================
  real function horiz_flux(ustar, ut, rho_a)
    real, intent(in) :: ustar, ut, rho_a

    if (ustar > ut) then
      horiz_flux = WHITE_C * (rho_a / GRAV) * ustar**3 &
                 * (1.0 - ut / ustar) * (1.0 + ut / ustar)
    else
      horiz_flux = 0.0
    end if
  end function

  ! ================================================================
  ! Vertical-to-horizontal flux ratio alpha (Lu and Shao, 1999)
  ! Eq. (13) of Foroutan et al. (2017):
  !   alpha = C_alpha * g * f * rho_b / (2*p) *
  !           (0.24 + C_beta * u* * sqrt(rho_p / p))
  ! where p is the plastic pressure, f the fine particle fraction,
  ! and C_alpha, C_beta are constants depending on soil type.
  ! ================================================================
  real function vert_horiz_ratio(soil_type, ustar)
    integer, intent(in) :: soil_type
    real, intent(in) :: ustar
    integer :: st
    real :: ca, ff, pp, cb

    st = max(1, min(soil_type, N_SOILTYPES))
    ca = C_ALPHA_LS(st)
    ff = F_FINE(st)
    pp = P_PLASTIC(st)
    cb = C_BETA_LS(st)

    vert_horiz_ratio = ca * GRAV * ff * (RHO_BULK_LS / 2.0) / pp * 0.24
  end function

  ! ================================================================
  ! Vegetation roughness density lambda_V
  ! Eq. (6) of Foroutan et al. (2017), Shao et al. (1996):
  !   lambda_V = -0.35 * ln(1 - A_V)
  ! where A_V is the vegetation cover fraction.
  ! ================================================================
  real function veg_roughness_density(veg_frac)
    real, intent(in) :: veg_frac
    real :: vf

    vf = max(min(veg_frac, 0.95), 0.005)
    veg_roughness_density = -0.35 * log(1.0 - vf)
  end function

  ! ================================================================
  ! Convert volumetric to gravimetric soil moisture
  ! Following Zender convention (GOCART/CMAQ):
  !   w_grav = w_vol * rho_water / (rho_p * (1 - Q_s))
  ! where Q_s = 0.489 - 0.126 * sand_frac is the porosity.
  ! ================================================================
  real function vol_to_grav_moisture(w_vol, sand_frac)
    real, intent(in) :: w_vol, sand_frac

    vol_to_grav_moisture = w_vol * RHO_WATER / &
                          (RHO_PARTICLE * (1.0 - (0.489 - 0.126 * sand_frac)))
  end function

  ! ================================================================
  ! Main: compute dust emission for a single grid cell
  ! ================================================================
  subroutine compute_emission_cell( &
      wind_10m, rho_air, soil_moist_vol, &
      clay_f, silt_f, sand_f, veg_frac, &
      land_type, soil_type, &
      out_ustar, out_uts0, out_fm, out_fr, &
      out_z0, out_sep, out_hflux, out_alpha, &
      out_vflux, out_emission)

    real, intent(in) :: wind_10m, rho_air, soil_moist_vol
    real, intent(in) :: clay_f, silt_f, sand_f, veg_frac
    integer, intent(in) :: land_type, soil_type
    real, intent(out) :: out_ustar, out_uts0, out_fm, out_fr
    real, intent(out) :: out_z0, out_sep, out_hflux, out_alpha
    real, intent(out) :: out_vflux, out_emission

    real :: lambda_v, lambda_s_val, lambda_total
    real :: h_eff, z0, ustar
    real :: w_grav, w_grav_pct, clay_pct
    real :: fm, fr, sep
    real :: soil_fracs(N_TEXTURES)
    real :: ut, hflux_total, alpha
    real :: veg_free
    integer :: lt, n

    lt = max(1, min(land_type, N_LANDTYPES))

    ! Split 3-component fractions into 4 texture categories
    soil_fracs(1) = sand_f / 2.0     ! coarse sand
    soil_fracs(2) = sand_f / 2.0     ! fine-medium sand
    soil_fracs(3) = silt_f           ! silt
    soil_fracs(4) = clay_f           ! clay

    ! Vegetation roughness density (Shao et al. 1996, Eq. 6)
    lambda_v = veg_roughness_density(veg_frac)
    lambda_s_val = LAMBDA_S_TABLE(lt)
    lambda_total = lambda_v + lambda_s_val

    ! Effective roughness height (Eq. 9 of Foroutan 2017)
    h_eff = (H_V_TABLE(lt) * lambda_v + H_S_TABLE(lt) * lambda_s_val) &
          / lambda_total

    ! Surface roughness (Foroutan 2017, Eq. 8)
    z0 = surface_roughness(lambda_total, h_eff)
    z0 = max(z0, 1.0e-6)

    ! Friction velocity from log wind profile (Eq. 7)
    ustar = VON_KARMAN * wind_10m / log(10.0 / z0)

    ! Convert volumetric to gravimetric moisture
    w_grav = vol_to_grav_moisture(soil_moist_vol, sand_f)
    w_grav_pct = w_grav * 100.0
    clay_pct = clay_f * 100.0

    ! Soil moisture correction (Fecan 1999, Eqs. 3-4)
    fm = moisture_factor(w_grav_pct, clay_pct)

    ! Drag partition correction (Eq. 5)
    fr = drag_partition(lambda_v, lambda_s_val, veg_frac)

    ! Reference threshold for optimal saltation size (75 um)
    out_uts0 = threshold_fric_vel(75.0e-6, rho_air)

    ! Soil erodibility potential (CMAQ convention)
    sep = clay_f * 0.08 + silt_f * 1.00 + sand_f * 0.12

    ! Total horizontal saltation flux over all particle sizes
    hflux_total = 0.0
    do n = 1, N_TEXTURES
      ut = threshold_fric_vel(DP_SIZES(n), rho_air) * fm * fr
      hflux_total = hflux_total + &
        horiz_flux(ustar, ut, rho_air) * soil_fracs(n) * sep
    end do

    ! Vertical-to-horizontal ratio (Lu-Shao 1999, Eq. 13)
    alpha = vert_horiz_ratio(soil_type, ustar)

    ! Vertical flux
    out_vflux = alpha * hflux_total

    ! Final emission with vegetation cover reduction (Eq. 14)
    veg_free = max(1.0 - veg_frac, 0.0)
    out_emission = veg_free * out_vflux

    ! Store diagnostics
    out_ustar = ustar
    out_fm = fm
    out_fr = fr
    out_z0 = z0
    out_sep = sep
    out_hflux = hflux_total
    out_alpha = alpha

  end subroutine

end module
