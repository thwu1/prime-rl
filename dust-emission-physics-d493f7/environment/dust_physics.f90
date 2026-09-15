module dust_physics
  ! ============================================================
  ! Mineral dust emission physics module
  !
  ! Implements routines from:
  !   - Shao & Lu (2000): threshold friction velocity
  !   - Fecan et al. (1999): soil moisture correction
  !   - MacKinnon et al. (2004): drag partition
  !   - Marticorena & Bergametti (1995): V/H flux ratio
  !   - White (1979): horizontal saltation flux
  !   - Kok et al. (2014): K14 vertical dust flux
  !   - Kok (2011): emitted dust size distribution
  !   - Foroutan et al. (2017): aeolian surface roughness
  !   - Laurent et al. (2008): erodibility factor
  !   - Zender: gravimetric soil moisture conversion
  ! ============================================================
  implicit none
  private

  public :: threshold_ustar, fecan_moisture_correction, &
            drag_partition_mackinnon, mb95_v2h_ratio, &
            white79_saltation_flux, k14_vertical_flux, &
            foroutan_roughness_length, gravimetric_moisture, &
            erodibility_factor, soil_erodibility_potential, &
            kok2011_size_fraction, compute_cell_emission

  integer, parameter, public :: N_BINS = 5
  double precision, parameter, public :: GRAV = 9.81d0
  double precision, parameter, public :: VON_KARMAN = 0.4d0

  ! Shao & Lu (2000) constants
  double precision, parameter :: A_N = 0.0123d0
  double precision, parameter :: GAMMA_COHESION = 1.65d-4  ! kg/s^2

  ! Kok et al. (2014) constants
  double precision, parameter :: RHO_A0 = 1.225d0
  double precision, parameter :: U_ST0_MIN = 0.16d0
  double precision, parameter :: C_D0 = 4.4d-5
  double precision, parameter :: C_E_K14 = 2.0d0
  double precision, parameter :: C_A_K14 = 2.7d0

  ! Kok (2011) size distribution constants
  double precision, parameter :: D_S_KOK = 3.4d-6     ! median diameter [m]
  double precision, parameter :: SIGMA_S = 3.0d0       ! geometric std dev [-]
  double precision, parameter :: LAMBDA_K = 12.0d-6    ! side crack propagation length [m]

  ! Bin boundaries [m] (diameter), GOCART2G standard
  double precision, parameter, public :: BIN_BOUNDS(6) = &
    (/ 0.2d-6, 2.0d-6, 3.6d-6, 6.0d-6, 12.0d-6, 20.0d-6 /)

  ! Characteristic saltation diameter [m]
  double precision, parameter :: D_CHAR = 75.0d-6

contains

  ! ============================================================
  ! Threshold friction velocity on dry smooth bare surface
  ! Shao & Lu (2000), Eq. (2) in Foroutan et al. (2017):
  !   u*t0(D) = sqrt( A_N * (rho_p*g*D/rho_a + Gamma/(rho_a*D)) )
  ! where D = particle diameter, rho_p = particle density,
  ! rho_a = air density, Gamma = interparticle cohesive force
  ! constant (1.65e-4 kg/s^2).
  ! ============================================================
  double precision function threshold_ustar(Dp, rho_p, rho_a) result(ust0)
    double precision, intent(in) :: Dp     ! particle diameter [m]
    double precision, intent(in) :: rho_p  ! particle density [kg/m3]
    double precision, intent(in) :: rho_a  ! air density [kg/m3]

    ust0 = 0.0d0

  end function threshold_ustar

  ! ============================================================
  ! Soil moisture correction factor
  ! Fecan et al. (1999), Eq. (3)-(4) in Foroutan et al. (2017):
  !   f_m = 1.0                                   if w <= w'
  !   f_m = sqrt(1 + 1.21 * (w - w')^0.68)        if w > w'
  ! where w is gravimetric soil moisture [%] and
  !   w' = 0.0014 * (%clay)^2 + 0.17 * (%clay)    [%]
  ! ============================================================
  double precision function fecan_moisture_correction(w_grav_pct, clay_pct) result(fm)
    double precision, intent(in) :: w_grav_pct  ! gravimetric moisture [%]
    double precision, intent(in) :: clay_pct    ! clay content [%]
    double precision :: w_prime

    w_prime = 0.0014d0 * clay_pct + 0.17d0 * clay_pct

    if (w_grav_pct <= w_prime) then
      fm = 1.0d0
    else
      fm = sqrt(1.0d0 + 1.21d0 * (w_grav_pct - w_prime)**0.68d0)
    end if

  end function fecan_moisture_correction

  ! ============================================================
  ! Drag partition correction (MacKinnon et al. 2004)
  ! Ratio of soil friction velocity to total friction velocity:
  !   R = 1 - ln(z0/z0s) / ln(0.7 * (122.55/z0s)^0.8)
  ! Valid for z0 > z0s > 0. Result clamped to [0, 1].
  ! ============================================================
  double precision function drag_partition_mackinnon(z0, z0s) result(R)
    double precision, intent(in) :: z0   ! aerodynamic roughness [m]
    double precision, intent(in) :: z0s  ! smooth roughness [m]

    if (z0 > z0s .and. z0s > 0.0d0) then
      R = 1.0d0 - log(z0/z0s) / log(0.7d0 * (0.1d0/z0s)**0.8d0)
    else
      R = 1.0d0
    end if
    R = max(0.0d0, min(R, 1.0d0))

  end function drag_partition_mackinnon

  ! ============================================================
  ! MB95 vertical-to-horizontal flux ratio
  ! Marticorena & Bergametti (1995):
  !   alpha = 10^(13.4*clay_frac - 6.0)   for clay_frac <= 0.2
  !   alpha = max_ratio                    for clay_frac > 0.2
  ! ============================================================
  double precision function mb95_v2h_ratio(clay_frac, max_ratio) result(alpha)
    double precision, intent(in) :: clay_frac   ! clay fraction [0-1]
    double precision, intent(in) :: max_ratio   ! maximum ratio
    double precision, parameter :: CLAY_THRESH = 0.2d0

    if (clay_frac > CLAY_THRESH) then
      alpha = max_ratio
    else
      alpha = 10.0d0**(13.4d0 * clay_frac - 6.0d0)
    end if

  end function mb95_v2h_ratio

  ! ============================================================
  ! White (1979) horizontal saltation flux, single particle size
  ! Eq. (10) in Foroutan et al. (2017):
  !   F_H = c*(rho_a/g)*(u* + u*t)*(u*^2 - u*t^2)   if u* > u*t
  !       = 0                                          otherwise
  ! c = 1.0 (Darmenova et al. 2009). Units: [kg/m/s]
  ! ============================================================
  double precision function white79_saltation_flux(rho_a, ustar, ustar_t) result(FH)
    double precision, intent(in) :: rho_a    ! air density [kg/m3]
    double precision, intent(in) :: ustar    ! friction velocity [m/s]
    double precision, intent(in) :: ustar_t  ! threshold friction velocity [m/s]

    if (ustar > ustar_t) then
      FH = (rho_a / GRAV) * ustar * (ustar**2 - ustar_t**2)
    else
      FH = 0.0d0
    end if

  end function white79_saltation_flux

  ! ============================================================
  ! Kok et al. (2014) vertical dust flux
  ! Eq. in K14 supplement:
  !   F_V = C_d * f_erod * k_gamma * rho_a
  !       * ((u*^2 - u_t^2)/u_st) * (u*/u_t)^(C_a*f_ust)
  ! where:
  !   u_st  = max(u_t * sqrt(rho_a/rho_a0), U_ST0_MIN)
  !   f_ust = (u_st - U_ST0_MIN) / U_ST0_MIN
  !   C_d   = C_D0 * exp(-C_E * f_ust)
  ! ============================================================
  double precision function k14_vertical_flux(ustar, ustar_t, rho_a, f_erod, k_gamma) result(FV)
    double precision, intent(in) :: ustar    ! soil friction velocity [m/s]
    double precision, intent(in) :: ustar_t  ! threshold friction velocity [m/s]
    double precision, intent(in) :: rho_a    ! air density [kg/m3]
    double precision, intent(in) :: f_erod   ! erodibility [0-1]
    double precision, intent(in) :: k_gamma  ! clay/silt factor
    double precision :: u_st, f_ust, C_d

    if (ustar > ustar_t .and. f_erod > 0.0d0) then
      u_st = ustar_t * sqrt(rho_a / RHO_A0)
      u_st = max(u_st, U_ST0_MIN)
      f_ust = (u_st - U_ST0_MIN) / U_ST0_MIN
      C_d = C_D0 * exp(-C_E_K14 * u_st)
      FV = C_d * f_erod * k_gamma * rho_a &
           * ((ustar**2 - ustar_t**2) / u_st) &
           * (ustar / ustar_t)**(C_A_K14 * f_ust)
    else
      FV = 0.0d0
    end if

  end function k14_vertical_flux

  ! ============================================================
  ! Aeolian surface roughness (Foroutan et al. 2017, Eq. 8)
  ! Derived from field/laboratory data (King et al. 2005,
  ! Marticorena et al. 2006, Hebrard et al. 2012):
  !   z0/h = 0.96 * lambda^1.07     for lambda < 0.2
  !   z0/h = 0.083 * lambda^(-0.46) for lambda >= 0.2
  ! Returns z0 [m].
  ! ============================================================
  double precision function foroutan_roughness_length(lambda, h_eff) result(z0)
    double precision, intent(in) :: lambda  ! roughness density [-]
    double precision, intent(in) :: h_eff   ! element height [m]
    double precision :: z0_over_h

    if (lambda < 0.2d0) then
      z0_over_h = 0.083d0 * lambda**(-0.46d0)
    else
      z0_over_h = 0.96d0 * lambda**(1.07d0)
    end if
    z0 = z0_over_h * h_eff

  end function foroutan_roughness_length

  ! ============================================================
  ! Convert volumetric to gravimetric soil moisture [%]
  ! Following Zender (GOCART implementation):
  !   Q_s = 0.489 - 0.126*f_sand   (soil porosity)
  !   rho_bulk = rho_s * (1 - Q_s)
  !   w_grav% = 100 * f_w * rho_w/rho_bulk * w_vol
  ! ============================================================
  double precision function gravimetric_moisture(w_vol, f_sand, f_w) result(w_pct)
    double precision, intent(in) :: w_vol   ! volumetric moisture [m3/m3]
    double precision, intent(in) :: f_sand  ! sand fraction [0-1]
    double precision, intent(in) :: f_w     ! scaling for top 1cm
    double precision, parameter :: RHO_W = 1000.0d0
    double precision, parameter :: RHO_S = 2500.0d0
    double precision :: Q_s, rho_bulk

    Q_s = 0.489d0 - 0.126d0 * f_sand
    rho_bulk = RHO_S * (1.0d0 - Q_s)
    w_pct = 100.0d0 * f_w * (RHO_W / rho_bulk) * w_vol

  end function gravimetric_moisture

  ! ============================================================
  ! Erodibility factor (Laurent et al. 2008)
  ! From GOCART K14 implementation:
  !   f_erod = 1.0                                for z0 <= 3e-5
  !   f_erod = 0.7304 - 0.0804*log10(100*z0)      for 3e-5 < z0 < z0_max
  !   f_erod = 0.0                                for z0 >= z0_max
  !   f_erod = 0.0                                for bedrock
  ! z0_max = 5e-3 m. Result clamped to >= 0.
  ! ============================================================
  double precision function erodibility_factor(z0, is_bedrock) result(f_erod)
    double precision, intent(in) :: z0
    logical, intent(in)          :: is_bedrock
    double precision, parameter :: Z0_MAX = 5.0d-3

    f_erod = 1.0d0

  end function erodibility_factor

  ! ============================================================
  ! Soil erodibility potential (FENGSHA/CMAQ)
  !   SEP = 0.08*clay + 1.00*silt + 0.12*sand
  ! ============================================================
  double precision function soil_erodibility_potential(clay, silt, sand) result(sep)
    double precision, intent(in) :: clay, silt, sand  ! fractions [0-1]
    sep = 0.08d0 * clay + 1.00d0 * silt + 0.12d0 * sand
  end function soil_erodibility_potential

  ! ============================================================
  ! Kok (2011) emitted dust mass size fraction
  ! PNAS, 108(3):1016-1021, doi:10.1073/pnas.1014798108
  !
  ! Returns the fraction of emitted dust mass in the diameter
  ! range [D_low, D_high].
  !
  ! The volume size distribution per unit ln(D) is:
  !   dV/dlnD = (1/c_v) * [1 + erf(ln(D/D_s)/(sqrt(2)*sigma_s))]
  !             * exp(-(D/lambda)^3)
  !
  ! Converting to per-unit-D and computing mass fraction:
  !   g(D) = (1/D) * [1 + erf(ln(D/D_s)/(sqrt(2)*sigma_s))]
  !          * exp(-(D/lambda)^3)
  !   f = integral_{D_low}^{D_high} g(D) dD
  !       / integral_{D_min}^{D_max} g(D) dD
  !
  ! where D_min = BIN_BOUNDS(1), D_max = BIN_BOUNDS(6).
  ! Parameters: D_S_KOK, SIGMA_S, LAMBDA_K (module constants).
  ! ============================================================
  double precision function kok2011_size_fraction(D_low, D_high) result(frac)
    double precision, intent(in) :: D_low   ! lower bin boundary [m]
    double precision, intent(in) :: D_high  ! upper bin boundary [m]

    frac = 0.0d0

  end function kok2011_size_fraction

  ! ============================================================
  ! Compute per-bin dust emission for a single grid cell
  !
  ! Orchestrates the module's physics routines to compute the
  ! total K14 vertical dust flux for a single grid cell, then
  ! distributes across N_BINS size bins using the Kok (2011)
  ! emitted dust size distribution.
  !
  ! Uses D_CHAR as the characteristic saltation diameter for
  ! threshold friction velocity, k_gamma = clay_frac, and
  ! applies moisture correction, drag partition, and erodibility.
  !
  ! Returns zero emissions for sub-threshold or bedrock cells.
  ! ============================================================
  subroutine compute_cell_emission(rho_p, rho_a, ustar_in, &
      clay_frac, silt_frac, sand_frac, &
      w_vol, z0, z0s, is_bedrock, f_w, &
      emissions, rc)
    double precision, intent(in) :: rho_p       ! particle density [kg/m3]
    double precision, intent(in) :: rho_a       ! air density [kg/m3]
    double precision, intent(in) :: ustar_in    ! friction velocity [m/s]
    double precision, intent(in) :: clay_frac   ! clay fraction [0-1]
    double precision, intent(in) :: silt_frac   ! silt fraction [0-1]
    double precision, intent(in) :: sand_frac   ! sand fraction [0-1]
    double precision, intent(in) :: w_vol       ! volumetric moisture [m3/m3]
    double precision, intent(in) :: z0          ! aerodynamic roughness [m]
    double precision, intent(in) :: z0s         ! smooth roughness [m]
    logical, intent(in)          :: is_bedrock
    double precision, intent(in) :: f_w         ! moisture scaling factor
    double precision, intent(out) :: emissions(N_BINS)
    integer, intent(out) :: rc

    emissions = 0.0d0
    rc = 0

  end subroutine compute_cell_emission

end module dust_physics
