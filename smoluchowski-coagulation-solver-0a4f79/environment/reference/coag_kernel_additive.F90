! Copyright (C) 2005-2012 Nicole Riemer and Matthew West
! Licensed under the GNU General Public License version 2 or (at your
! option) any later version. See the file COPYING for details.

!> \file
!> The pmc_coag_kernel_additive module.
!!
!! Additive coagulation kernel: K(v1, v2) = beta1 * (v1 + v2)
!! where beta1 is a scaling coefficient specified in the scenario
!! configuration.

module pmc_coag_kernel_additive

  use pmc_constants
  implicit none

contains

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  !> Exact analytical solution for the additive kernel with an
  !> exponential initial size distribution.
  !!
  !! Initial condition (same as constant kernel):
  !!   n(v, 0) = (N0 / v_mu) * exp(-v / v_mu)
  !! where v_mu = (4 pi / 3) R^3.
  !!
  !! Rescaled time and auxiliary variable:
  !!   tau = N0 * v_mu * beta1 * t
  !!   T   = 1 - exp(-tau)
  !!
  !! Evolved distribution:
  !!   n(v, t) = (N0 / v) * (1 - T) / sqrt(T)
  !!             * exp(-(1 + T) * v / v_mu)
  !!             * I_1(2 * (v / v_mu) * sqrt(T))
  !!
  !! where I_1(x) is the modified Bessel function of the first kind,
  !! order 1. For large arguments the asymptotic approximation
  !!   I_1(x) ~ exp(x) / sqrt(2 pi x)
  !! is used to avoid overflow.
  !!
  !! Parameters:
  !!   num_conc            = N0 (#/m^3)
  !!   radius_at_mean_vol  = R (m)
  !!   additive_coeff      = beta1, the kernel scaling coefficient
  subroutine soln_additive_exp(time, num_conc, radius_at_mean_vol, &
       additive_coeff, v, nn)

    !> Current time (s).
    real(kind=dp), intent(in) :: time
    !> Initial number concentration N0 (#/m^3).
    real(kind=dp), intent(in) :: num_conc
    !> Radius at the mean volume, R (m).
    real(kind=dp), intent(in) :: radius_at_mean_vol
    !> Additive kernel coefficient beta1.
    real(kind=dp), intent(in) :: additive_coeff
    !> Particle volume (m^3).
    real(kind=dp), intent(in) :: v
    !> Number density n(v, t) (dN/dv, in #/(m^3 m^3)).
    real(kind=dp), intent(out) :: nn

    real(kind=dp) :: tau, T, rat_v, b, x, mean_vol

    mean_vol = (4.0d0 / 3.0d0) * const%pi * radius_at_mean_vol**3

    if (time == 0d0) then
       nn = num_conc / mean_vol * exp(-v / mean_vol)
    else
       tau = num_conc * mean_vol * additive_coeff * time
       T = 1d0 - exp(-tau)
       rat_v = v / mean_vol
       x = 2d0 * rat_v * sqrt(T)
       if (x < 500d0) then
          call bessi1(x, b)
          nn = num_conc / v * (1d0 - T) / sqrt(T) &
               * exp(-((1d0 + T) * rat_v)) * b
       else
          ! Asymptotic form for large Bessel argument:
          ! I_1(x) ~ exp(x) / sqrt(2 pi x)
          nn = num_conc / v * (1d0 - T) / sqrt(T) &
               * exp((2d0*sqrt(T) - T - 1d0) * rat_v) &
               / sqrt(4d0 * const%pi * rat_v * sqrt(T))
       end if
    end if

  end subroutine soln_additive_exp

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  !> Modified Bessel function of the first kind, I_1(x).
  !!
  !! Uses rational polynomial minimax approximation for numerical
  !! evaluation. Reference: W. J. Cody and L. Stoltz,
  !! CALCI1 routine, based on Blair & Edwards (AECL-4928, 1974).
  !!
  !! For |x| < 15: 15-term polynomial in x^2.
  !! For |x| >= 15: 8-term rational approximation multiplied by
  !! exp(x)/sqrt(x).
  subroutine bessi1(x, r)

    real(kind=dp), intent(in) :: x
    real(kind=dp), intent(out) :: r

    call calci1(x, r, 1)

  end subroutine bessi1

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  !> CALCI1: compute I_1(x) or exp(-|x|)*I_1(x).
  !!
  !! jint = 1: return I_1(x)
  !! jint = 2: return exp(-|x|) * I_1(x)
  subroutine calci1(arg, result, jint)

    real(kind=dp), intent(in) :: arg
    real(kind=dp), intent(out) :: result
    integer, intent(in) :: jint

    real(kind=dp) :: a, b, sump, sumq, x, xx
    integer :: j

    real(kind=dp), parameter :: one5 = 15.0d0
    real(kind=dp), parameter :: exp40 = 2.353852668370199854d17
    real(kind=dp), parameter :: forty = 40.0d0
    real(kind=dp), parameter :: rec15 = 6.6666666666666666666d-2
    real(kind=dp), parameter :: two25 = 225.0d0
    real(kind=dp), parameter :: xsmall = 5.55d-17
    real(kind=dp), parameter :: xinf = 1.79d308
    real(kind=dp), parameter :: xmax = 713.987d0
    real(kind=dp), parameter :: pbar = 3.98437500d-01

    real(kind=dp) :: p(15), q(5), pp(8), qq(6)

    data p/-1.9705291802535139930d-19,-6.5245515583151902910d-16, &
           -1.1928788903603238754d-12,-1.4831904935994647675d-09, &
           -1.3466829827635152875d-06,-9.1746443287817501309d-04, &
           -4.7207090827310162436d-01,-1.8225946631657315931d+02, &
           -5.1894091982308017540d+04,-1.0588550724769347106d+07, &
           -1.4828267606612366099d+09,-1.3357437682275493024d+11, &
           -6.9876779648010090070d+12,-1.7732037840791591320d+14, &
           -1.4577180278143463643d+15/
    data q/-4.0076864679904189921d+03, 7.4810580356655069138d+06, &
           -8.0059518998619764991d+09, 4.8544714258273622913d+12, &
           -1.3218168307321442305d+15/
    data pp/-6.0437159056137600000d-02, 4.5748122901933459000d-01, &
            -4.2843766903304806403d-01, 9.7356000150886612134d-02, &
            -3.2457723974465568321d-03,-3.6395264712121795296d-04, &
             1.6258661867440836395d-05,-3.6347578404608223492d-07/
    data qq/-3.8806586721556593450d+00, 3.2593714889036996297d+00, &
            -8.5017476463217924408d-01, 7.4212010813186530069d-02, &
            -2.2835624489492512649d-03, 3.7510433111922824643d-05/

    x = abs(arg)

    if (x < xsmall) then
       result = 0.5d0 * x
    else if (x < one5) then
       xx = x * x
       sump = p(1)
       do j = 2, 15
          sump = sump * xx + p(j)
       end do
       xx = xx - two25
       sumq = ((((xx + q(1)) * xx + q(2)) * xx + q(3)) * xx + q(4)) &
            * xx + q(5)
       result = (sump / sumq) * x
       if (jint == 2) result = result * exp(-x)
    else if (jint == 1 .and. xmax < x) then
       result = xinf
    else
       xx = 1.0d0 / x - rec15
       sump = ((((((pp(1) * xx + pp(2)) * xx + pp(3)) * xx + pp(4)) &
            * xx + pp(5)) * xx + pp(6)) * xx + pp(7)) * xx + pp(8)
       sumq = (((((xx + qq(1)) * xx + qq(2)) * xx + qq(3)) * xx + qq(4)) &
            * xx + qq(5)) * xx + qq(6)
       result = sump / sumq
       if (jint /= 1) then
          result = (result + pbar) / sqrt(x)
       else
          if (xmax - one5 < x) then
             a = exp(x - forty)
             b = exp40
          else
             a = exp(x)
             b = 1.0d0
          end if
          result = ((result * a + pbar * a) / sqrt(x)) * b
       end if
    end if

    if (arg < 0.0d0) result = -result

  end subroutine calci1

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

end module pmc_coag_kernel_additive
