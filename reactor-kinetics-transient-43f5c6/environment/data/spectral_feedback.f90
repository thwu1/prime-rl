! =============================================================
!  Spectral feedback module — temperature-dependent reactivity
!  corrections from multigroup transport perturbation theory.
!
!  The second-order coefficients model Doppler broadening and
!  spectral hardening effects fitted from reference C5G7-class
!  lattice calculations over the range 500–2500 K.
!
!  All subroutines use ISO_C_BINDING for C-callable interfaces.
! =============================================================

module spectral_feedback
  use iso_c_binding
  implicit none

  ! Second-order spectral correction coefficients [dk/k / K^2]
  real(c_double), parameter :: KAPPA_F  = -6.5d-8    ! fuel Doppler 2nd order
  real(c_double), parameter :: KAPPA_M  = -2.7d-7    ! moderator density 2nd order
  real(c_double), parameter :: KAPPA_FM =  3.5d-8    ! fuel-moderator spectral coupling

contains

  ! ---------------------------------------------------------
  !  compute_feedback: total reactivity feedback with spectral
  !  correction.  First-order (linear) + second-order terms.
  !
  !  rho_fb = alpha_f * dT_f + alpha_m * dT_m
  !         + KAPPA_F  * dT_f^2
  !         + KAPPA_M  * dT_m^2
  !         + KAPPA_FM * dT_f * dT_m
  ! ---------------------------------------------------------
  subroutine compute_feedback(T_f, T_m, T_f_ref, T_m_ref, &
                              alpha_f, alpha_m, rho_fb)     &
      bind(C, name="compute_feedback")

    real(c_double), intent(in), value :: T_f, T_m
    real(c_double), intent(in), value :: T_f_ref, T_m_ref
    real(c_double), intent(in), value :: alpha_f, alpha_m
    real(c_double), intent(out) :: rho_fb

    real(c_double) :: dT_f, dT_m

    dT_f = T_f - T_f_ref
    dT_m = T_m - T_m_ref

    rho_fb = alpha_f * dT_f + alpha_m * dT_m  &
           + KAPPA_F  * dT_f * dT_f            &
           + KAPPA_M  * dT_m * dT_m            &
           + KAPPA_FM * dT_f * dT_m

  end subroutine compute_feedback

  ! ---------------------------------------------------------
  !  get_spectral_coefficients: retrieve the three second-order
  !  coefficients so callers can inspect them.
  ! ---------------------------------------------------------
  subroutine get_spectral_coefficients(kf, km, kfm) &
      bind(C, name="get_spectral_coefficients")

    real(c_double), intent(out) :: kf, km, kfm

    kf  = KAPPA_F
    km  = KAPPA_M
    kfm = KAPPA_FM

  end subroutine get_spectral_coefficients

end module spectral_feedback
