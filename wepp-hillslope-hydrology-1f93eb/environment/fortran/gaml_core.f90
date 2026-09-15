! gaml_core.f90 — GAML infiltration numerical routines
! Provides C-interoperable subroutines for use via Python ctypes.
!

module gaml_core
  use iso_c_binding
  implicit none

contains

  ! Compute the auxiliary function G(F) = F - Ns_td * ln(1 + F / Ns_td)
  subroutine gaml_g_func(F, Ns_td, result) bind(C, name="gaml_g_func")
    real(c_double), intent(in) :: F, Ns_td
    real(c_double), intent(out) :: result

    if (F <= 0.0d0) then
      result = 0.0d0
    else
      result = F - Ns_td * log(1.0d0 + F / Ns_td)
    end if
  end subroutine gaml_g_func

  ! Solve G(F) = target_G for F using Newton-Raphson iteration
  subroutine gaml_solve_f(target_G, Ns_td, F_guess, tol, max_iter, F_result) &
      bind(C, name="gaml_solve_f")
    real(c_double), intent(in) :: target_G, Ns_td, F_guess, tol
    integer(c_int), intent(in) :: max_iter
    real(c_double), intent(out) :: F_result

    real(c_double) :: F_val, gval, gprime, dF, F_new
    integer :: i

    F_val = max(F_guess, 1.0d-12)
    do i = 1, max_iter
      if (F_val <= 0.0d0) then
        gval = -target_G
      else
        gval = F_val - Ns_td * log(1.0d0 + F_val / Ns_td) - target_G
      end if
      gprime = F_val / (F_val + Ns_td)
      if (abs(gprime) < 1.0d-15) exit
      dF = gval / gprime
      F_new = F_val - dF
      if (F_new <= 0.0d0) F_new = F_val / 2.0d0
      if (abs(F_new - F_val) < tol) then
        F_result = F_new
        return
      end if
      F_val = F_new
    end do
    F_result = F_val
  end subroutine gaml_solve_f

  ! Compute infiltration rate: f = Ke * (1 + Ns_td / F_cum)
  subroutine gaml_infil_rate(Ke, Ns_td, F_cum, rate) bind(C, name="gaml_infil_rate")
    real(c_double), intent(in) :: Ke, Ns_td, F_cum
    real(c_double), intent(out) :: rate

    if (F_cum <= 1.0d-12) then
      rate = 1.0d12
    else
      rate = Ke * (1.0d0 + Ns_td / F_cum)
    end if
  end subroutine gaml_infil_rate

end module gaml_core
