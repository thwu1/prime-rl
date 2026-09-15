! packed_bed.f90 - Packed bed thermal-hydraulic correlations
! Compiled to shared library for use via Python ctypes interface
!
! Provides Ergun pressure drop and Wakao-Kaguei heat transfer
! correlations for randomly packed spherical particle beds.

module packed_bed_mod
  use iso_c_binding
  implicit none
  contains

  ! Ergun equation for pressure gradient through packed bed [Pa/m]
  ! Combines viscous (Blake-Kozeny) and inertial (Burke-Plummer) terms
  subroutine ergun_dp(n, rho, vs, mu, dp_peb, eps, dp_dz) bind(C, name="ergun_dp")
    integer(c_int), intent(in), value :: n
    real(c_double), intent(in) :: rho(n), vs(n), mu(n)
    real(c_double), intent(in), value :: dp_peb, eps
    real(c_double), intent(out) :: dp_dz(n)

    real(c_double) :: one_minus_eps, eps_cubed

    one_minus_eps = 1.0d0 - eps
    eps_cubed = eps**3

    dp_dz = 180.0d0 * mu * vs * one_minus_eps**2 / (dp_peb**2 * eps_cubed) &
          + 1.75d0 * rho * vs**2 * one_minus_eps / (dp_peb * eps_cubed)
  end subroutine ergun_dp


  ! Wakao-Kaguei correlation for Nusselt number in packed beds
  ! Nu = 2 + 1.1 * Re^0.6 * Pr^(1/3)
  ! Valid for 15 < Re < 8500, 0.7 < Pr < 1.0
  subroutine wakao_nu(n, re_arr, pr_arr, nu_arr) bind(C, name="wakao_nu")
    integer(c_int), intent(in), value :: n
    real(c_double), intent(in) :: re_arr(n), pr_arr(n)
    real(c_double), intent(out) :: nu_arr(n)

    nu_arr = 2.0d0 + 1.1d0 * re_arr**0.6d0 * pr_arr**(1.0d0/3.0d0)
  end subroutine wakao_nu

end module packed_bed_mod
