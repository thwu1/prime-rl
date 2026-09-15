! thermo_eval.f90
! NASA 7-coefficient thermodynamic polynomial evaluator
! Provides C-callable routines via iso_c_binding for use with ctypes/FFI
!
! Each routine takes:
!   a(7)  - polynomial coefficients (array, passed by reference)
!   b1    - first integration constant (scalar, passed by value)
!   b2    - second integration constant (scalar, passed by value)
!   T     - temperature in Kelvin (scalar, passed by value)
!

module thermo_eval
  use iso_c_binding, only: c_double
  implicit none
  private
  public :: thermo_cp_over_r, thermo_h_over_rt, thermo_s_over_r
  public :: thermo_g_over_rt, thermo_eval_all

contains

  !> Cp/R from 7-coefficient NASA polynomial
  function thermo_cp_over_r(a, b1, b2, T) result(val) &
      bind(C, name="thermo_cp_over_r")
    real(c_double), intent(in) :: a(7)
    real(c_double), value, intent(in) :: b1, b2, T
    real(c_double) :: val
    real(c_double) :: T2
    T2 = T * T
    val = a(1)/(T2) + a(2)/T + a(3) + a(4)*T &
        + a(5)*T2 + a(6)*T2*T + a(7)*T2*T2
  end function

  !> H/(RT) from 7-coefficient NASA polynomial with integration constant b1
  function thermo_h_over_rt(a, b1, b2, T) result(val) &
      bind(C, name="thermo_h_over_rt")
    real(c_double), intent(in) :: a(7)
    real(c_double), value, intent(in) :: b1, b2, T
    real(c_double) :: val
    real(c_double) :: T2
    T2 = T * T
    val = -a(1)/(T2) + a(2)*log(T)/T + a(3) &
        + a(4)*T/2.0d0 + a(5)*T2/3.0d0 &
        + a(6)*T2*T/4.0d0 + a(7)*T2*T2/5.0d0 + b1/T
  end function

  !> S/R at standard pressure (1 bar) from 7-coefficient polynomial with b2
  function thermo_s_over_r(a, b1, b2, T) result(val) &
      bind(C, name="thermo_s_over_r")
    real(c_double), intent(in) :: a(7)
    real(c_double), value, intent(in) :: b1, b2, T
    real(c_double) :: val
    real(c_double) :: T2
    T2 = T * T
    val = -a(1)/(2.0d0*T2) - a(2)/T + a(3)*log(T) &
        + a(4)*T + a(5)*T2/2.0d0 &
        + a(6)*T2*T/3.0d0 + a(7)*T2*T2/4.0d0 + b2
  end function

  !> Dimensionless standard Gibbs function G/(RT) = H/(RT) - S/R
  function thermo_g_over_rt(a, b1, b2, T) result(val) &
      bind(C, name="thermo_g_over_rt")
    real(c_double), intent(in) :: a(7)
    real(c_double), value, intent(in) :: b1, b2, T
    real(c_double) :: val
    val = thermo_h_over_rt(a, b1, b2, T) - thermo_s_over_r(a, b1, b2, T)
  end function

  !> Evaluate all four properties in a single call (reduces FFI overhead)
  !> Output arguments cp_r, h_rt, s_r, g_rt are passed by reference
  subroutine thermo_eval_all(a, b1, b2, T, cp_r, h_rt, s_r, g_rt) &
      bind(C, name="thermo_eval_all")
    real(c_double), intent(in)  :: a(7)
    real(c_double), value, intent(in)  :: b1, b2, T
    real(c_double), intent(out) :: cp_r, h_rt, s_r, g_rt
    cp_r = thermo_cp_over_r(a, b1, b2, T)
    h_rt = thermo_h_over_rt(a, b1, b2, T)
    s_r  = thermo_s_over_r(a, b1, b2, T)
    g_rt = h_rt - s_r
  end subroutine

end module thermo_eval
