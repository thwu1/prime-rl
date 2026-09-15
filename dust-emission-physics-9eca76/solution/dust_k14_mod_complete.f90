! dust_k14_mod.f90 - COMPLETE implementation
! Kok et al. (2014) dust emission scheme
! Based on Kok et al. (2014), Atmos. Chem. Phys., 14, 13023-13041
! doi:10.5194/acp-14-13023-2014
!

module dust_k14_mod
  use dust_physics_mod, only: GRAV, VON_KARMAN, RHO_PARTICLE, RHO_WATER, &
                               A_N, GAMMA_COH, N_TEXTURES, DP_SIZES, EROPOT, &
                               N_LANDTYPES, LAMBDA_S_TABLE, H_S_TABLE, H_V_TABLE, &
                               threshold_fric_vel, moisture_factor, &
                               veg_roughness_density, surface_roughness, &
                               vol_to_grav_moisture
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
  ! Ito and Kok (2017), Eq. 4:
  !   k_gamma = exp(0.831 * f_cs - 0.0203)
  ! ================================================================
  real function k14_clay_silt_param(clay_f, silt_f)
    real, intent(in) :: clay_f, silt_f
    real :: f_cs

    f_cs = clay_f + silt_f
    k14_clay_silt_param = exp(0.831 * f_cs - 0.0203)
  end function

  ! ================================================================
  ! MacKinnon roughness drag partition R
  ! MacKinnon et al. (2004):
  !   R = 1.0 - log(z0 / z0s) / log(0.7 * (122.55 / z0s)^0.8)
  ! Clamped to [0.001, 1.0].
  ! ================================================================
  real function k14_roughness_partition(z0, z0s)
    real, intent(in) :: z0, z0s
    real :: R

    R = 1.0 - log(z0 / z0s) / log(0.7 * (122.55 / z0s)**0.8)
    k14_roughness_partition = max(0.001, min(R, 1.0))
  end function

  ! ================================================================
  ! K14 dust emission coefficient C_d
  ! Kok et al. (2014), Eq. 5:
  !   C_d = C_d0 * exp(-C_e * (u_st / u_st0 - 1))
  ! ================================================================
  real function k14_emission_coeff(u_t, rho_air)
    real, intent(in) :: u_t, rho_air
    real :: u_st

    u_st = u_t * sqrt(rho_air / RHO_A0)
    k14_emission_coeff = C_D0 * exp(-C_E_K14 * (u_st / U_ST0 - 1.0))
  end function

  ! ================================================================
  ! K14 vertical dust emission flux
  ! Kok et al. (2014), Eq. 1:
  !   F_d = C_d * f_erod * k_gamma * (rho_air / u_st) *
  !         (u^2 - u_t^2) * (u / u_t)^(C_a * u_st / u_st0)
  ! Returns 0 when u <= u_t.
  ! ================================================================
  real function k14_vertical_flux(u, u_t, rho_air, f_erod, k_gamma, C_d_val)
    real, intent(in) :: u, u_t, rho_air, f_erod, k_gamma, C_d_val
    real :: u_st, f_ust

    if (u <= u_t) then
      k14_vertical_flux = 0.0
    else
      u_st = u_t * sqrt(rho_air / RHO_A0)
      f_ust = u_st / U_ST0
      k14_vertical_flux = C_d_val * f_erod * k_gamma * (rho_air / u_st) &
                         * (u**2 - u_t**2) &
                         * (u / u_t)**(C_A_K14 * f_ust)
    end if
  end function

  ! ================================================================
  ! Compute K14 dust emission for a single grid cell.
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

    real :: lambda_v, lambda_s_val, lambda_total
    real :: h_eff, z0, ustar
    real :: w_grav, w_grav_pct, clay_pct
    real :: fm, k_gamma, z0s, R, u_aeolian
    real :: dp_rep, u_t0, u_t, C_d_val, f_erod
    real :: veg_free
    integer :: lt, st

    lt = max(1, min(land_type, N_LANDTYPES))
    st = max(1, min(soil_type, 4))

    ! Surface roughness (shared with FENGSHA)
    lambda_v = veg_roughness_density(veg_frac)
    lambda_s_val = LAMBDA_S_TABLE(lt)
    lambda_total = lambda_v + lambda_s_val
    h_eff = (H_V_TABLE(lt) * lambda_v + H_S_TABLE(lt) * lambda_s_val) &
          / lambda_total
    z0 = surface_roughness(lambda_total, h_eff)
    z0 = max(z0, 1.0e-6)

    ! Friction velocity from log wind profile
    ustar = VON_KARMAN * wind_10m / log(10.0 / z0)

    ! Moisture correction (shared with FENGSHA)
    w_grav = vol_to_grav_moisture(soil_moist_vol, sand_f)
    w_grav_pct = w_grav * 100.0
    clay_pct = clay_f * 100.0
    fm = moisture_factor(w_grav_pct, clay_pct)

    ! K14-specific computations
    k_gamma = k14_clay_silt_param(clay_f, silt_f)
    z0s = Z0S_TABLE(st)
    R = k14_roughness_partition(z0, z0s)
    u_aeolian = R * ustar

    ! Representative threshold for soil type
    dp_rep = DC_SOIL(st)
    u_t0 = threshold_fric_vel(dp_rep, rho_air)
    u_t = u_t0 * fm

    ! Emission coefficient
    C_d_val = k14_emission_coeff(u_t, rho_air)

    ! Erodibility (same formula as FENGSHA SEP)
    f_erod = clay_f * 0.08 + silt_f * 1.00 + sand_f * 0.12

    ! K14 vertical flux
    out_vflux = k14_vertical_flux(u_aeolian, u_t, rho_air, &
                                  f_erod, k_gamma, C_d_val)

    ! Vegetation reduction
    veg_free = max(1.0 - veg_frac, 0.0)
    out_emission = veg_free * out_vflux

    ! Output mapping
    out_ustar = ustar
    out_uts0 = threshold_fric_vel(75.0e-6, rho_air)
    out_fm = fm
    out_fr = R
    out_z0 = z0
    out_sep = k_gamma
    out_hflux = u_aeolian
    out_alpha = C_d_val

  end subroutine

end module
