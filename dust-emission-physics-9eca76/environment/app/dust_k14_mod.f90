! dust_k14_mod.f90
! Kok et al. (2014) dust emission scheme
! Based on Kok et al. (2014), Atmos. Chem. Phys., 14, 13023-13041
! doi:10.5194/acp-14-13023-2014
!

module dust_k14_mod
  use dust_physics_mod, only: GRAV, VON_KARMAN, RHO_PARTICLE, RHO_WATER, &
                               A_N, GAMMA_COH, N_TEXTURES, DP_SIZES, EROPOT, &
                               N_LANDTYPES, LAMBDA_S_TABLE, H_S_TABLE, H_V_TABLE
  implicit none
  private

  ! ---- Kok et al. (2014) scheme-specific constants ----
  ! Table 1 of Kok et al. (2014)
  real, parameter, public :: RHO_A0 = 1.225          ! standard air density [kg/m^3]
  real, parameter, public :: U_ST0 = 0.16             ! standardized threshold [m/s]
  real, parameter, public :: C_D0 = 4.4e-5            ! base emission coefficient [kg s/m^5]
  real, parameter, public :: C_E_K14 = 2.0            ! exponential decay constant [-]
  real, parameter, public :: C_A_K14 = 2.7            ! power law exponent constant [-]

  ! Representative soil aggregate diameter per soil type [m]
  ! Following Dc_soil in GOCART K14 for simplified 4-type classification
  ! 1=sand, 2=loam, 3=sandy_clay_loam, 4=clay
  real, parameter, public :: DC_SOIL(4) = &
    (/ 500.0e-6, 210.0e-6, 125.0e-6, 50.0e-6 /)

  ! Smooth surface roughness length per soil type [m]
  ! MacKinnon et al. (2004), Kok et al. (2014)
  real, parameter, public :: Z0S_TABLE(4) = &
    (/ 3.3e-5, 5.0e-5, 5.0e-5, 1.0e-4 /)

  public :: compute_k14_cell

contains

  ! ================================================================
  ! Clay-silt erodibility parameter k_gamma
  ! Ito and Kok (2017), doi:10.5194/acp-17-3991-2017, Eq. 4:
  !   k_gamma = exp(0.831 * f_cs - 0.0203)
  ! where f_cs = clay_fraction + silt_fraction (both as mass
  ! fractions in [0,1]).
  ! ================================================================
  real function k14_clay_silt_param(clay_f, silt_f)
    real, intent(in) :: clay_f, silt_f
    ! TODO: implement
    k14_clay_silt_param = 0.0
  end function

  ! ================================================================
  ! MacKinnon roughness drag partition R
  ! MacKinnon et al. (2004), used in Kok et al. (2014) Sect. 2.1:
  !   R = 1.0 - log(z0 / z0s) / log(0.7 * (122.55 / z0s)^0.8)
  ! where z0 is the aerodynamic roughness length [m] and z0s is the
  ! smooth roughness length for the soil type [m].
  ! Clamp result to [0.001, 1.0].
  ! ================================================================
  real function k14_roughness_partition(z0, z0s)
    real, intent(in) :: z0   ! aerodynamic roughness [m]
    real, intent(in) :: z0s  ! smooth roughness [m]
    ! TODO: implement
    k14_roughness_partition = 0.0
  end function

  ! ================================================================
  ! K14 dust emission coefficient C_d
  ! Kok et al. (2014), Eq. 5:
  !   C_d = C_d0 * exp(-C_e * (u_st / u_st0 - 1))
  ! where the standardized threshold friction velocity is:
  !   u_st = u_t * sqrt(rho_air / rho_a0)
  ! u_t is the moisture-corrected threshold friction velocity [m/s],
  ! and rho_air the local air density [kg/m^3].
  ! ================================================================
  real function k14_emission_coeff(u_t, rho_air)
    real, intent(in) :: u_t     ! moisture-corrected threshold [m/s]
    real, intent(in) :: rho_air ! air density [kg/m^3]
    ! TODO: implement
    k14_emission_coeff = 0.0
  end function

  ! ================================================================
  ! K14 vertical dust emission flux
  ! Kok et al. (2014), Eq. 1:
  !   F_d = C_d * f_erod * k_gamma * (rho_air / u_st) *
  !         (u^2 - u_t^2) * (u / u_t)^(C_a * u_st / u_st0)
  ! where:
  !   u     = aeolian friction velocity = R * u_star  [m/s]
  !   u_t   = moisture-corrected threshold [m/s]
  !   u_st  = u_t * sqrt(rho_air / rho_a0)  [m/s]
  !   f_erod = soil erodibility fraction [0,1]
  !   k_gamma = clay-silt erodibility parameter [-]
  !   C_d   = emission coefficient [kg s/m^5]
  ! Returns 0 when u <= u_t.
  ! ================================================================
  real function k14_vertical_flux(u, u_t, rho_air, f_erod, k_gamma, C_d_val)
    real, intent(in) :: u, u_t, rho_air, f_erod, k_gamma, C_d_val
    ! TODO: implement
    k14_vertical_flux = 0.0
  end function

  ! ================================================================
  ! Compute K14 dust emission for a single grid cell.
  !
  ! Reuses surface roughness (Eqs. 6-8 of Foroutan 2017) and Fecan
  ! moisture correction (Eqs. 3-4) from the FENGSHA module, but
  ! applies K14-specific parameterizations:
  !   - MacKinnon drag partition R (instead of Raupach double partition)
  !   - Kok emission coefficient C_d
  !   - K14 vertical flux formula (instead of White saltation + Lu-Shao)
  !   - Clay-silt erodibility parameter k_gamma
  !   - Representative soil aggregate diameter per soil type
  !
  ! Uses the same Shao-Lu (2000) threshold friction velocity as FENGSHA,
  ! applied to the representative aggregate diameter DC_SOIL for the
  ! given soil_type, with Fecan moisture correction.
  !
  ! Output mapping (unified format with FENGSHA):
  !   out_ustar = friction velocity from log profile
  !   out_uts0  = Shao-Lu threshold for 75 um reference particle
  !   out_fm    = Fecan moisture correction factor
  !   out_fr    = MacKinnon drag partition R
  !   out_z0    = surface roughness length
  !   out_sep   = k_gamma (clay-silt erodibility parameter)
  !   out_hflux = aeolian friction velocity u = R * u_star
  !   out_alpha = C_d emission coefficient
  !   out_vflux = K14 vertical dust flux
  !   out_emission = (1 - veg_frac) * out_vflux
  ! ================================================================
  subroutine compute_k14_cell( &
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

    ! TODO: Implement K14 cell computation.
    ! This subroutine shares surface roughness and Fecan moisture
    ! physics with FENGSHA but applies K14-specific emission
    ! parameterizations using the functions defined above.
    ! Uses DC_SOIL and Z0S_TABLE indexed by soil_type.

    out_ustar = 0.0
    out_uts0 = 0.0
    out_fm = 0.0
    out_fr = 0.0
    out_z0 = 0.0
    out_sep = 0.0
    out_hflux = 0.0
    out_alpha = 0.0
    out_vflux = 0.0
    out_emission = 0.0

  end subroutine

end module
