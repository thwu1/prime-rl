module thermal_mod
  use, intrinsic :: iso_c_binding
  implicit none
contains

  subroutine compute_conductivity(n, frac, kt_dry, kf_dry, &
       vwc, kw, ki, uwc, kt_out, kf_out) bind(c, name='compute_conductivity')
    integer(c_int), intent(in), value :: n
    real(c_double), intent(in) :: frac(n), kt_dry(n), kf_dry(n)
    real(c_double), intent(in), value :: vwc, kw, ki, uwc
    real(c_double), intent(out) :: kt_out, kf_out

    real(c_double) :: Kd_t, Kd_f
    integer :: i

    ! Weighted soil dry thermal conductivity
    Kd_t = 0.0d0
    Kd_f = 0.0d0
    do i = 1, n
      Kd_t = Kd_t + kt_dry(i) * frac(i)
      Kd_f = Kd_f + kf_dry(i) * frac(i)
    end do

    ! Water/ice phase correction
    kt_out = Kd_t + kw * vwc
    kf_out = Kd_f + ki * (vwc - uwc) + kw * uwc

  end subroutine compute_conductivity


  subroutine compute_heat_capacity(n, frac, sheat, bdens, &
       vwc, ct_out, cf_out) bind(c, name='compute_heat_capacity')
    integer(c_int), intent(in), value :: n
    real(c_double), intent(in) :: frac(n), sheat(n), bdens(n)
    real(c_double), intent(in), value :: vwc
    real(c_double), intent(out) :: ct_out, cf_out

    real(c_double) :: w_hc, w_bd, Cdry
    integer :: i

    w_hc = 0.0d0
    w_bd = 0.0d0
    do i = 1, n
      w_hc = w_hc + sheat(i) * frac(i)
      w_bd = w_bd + bdens(i) * frac(i)
    end do
    Cdry = w_hc * w_bd

    ct_out = Cdry + 4190.0d0 * vwc
    cf_out = Cdry + 2025.0d0 * vwc

  end subroutine compute_heat_capacity

end module thermal_mod
