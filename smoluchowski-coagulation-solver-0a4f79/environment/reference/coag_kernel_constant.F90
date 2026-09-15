! Copyright (C) 2005-2012 Nicole Riemer and Matthew West
! Licensed under the GNU General Public License version 2 or (at your
! option) any later version. See the file COPYING for details.

!> \file
!> The pmc_coag_kernel_constant module.
!!
!! Constant coagulation kernel: K(v1, v2) = beta_0 (size-independent).

module pmc_coag_kernel_constant

  use pmc_constants
  implicit none

  !> Fixed kernel rate constant (m^3/s).
  !! This value is used in the PartMC test scenarios.
  real(kind=dp), parameter :: beta_0 = 0.25d0 / (60d0 * 2d8)

contains

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  !> Exact analytical solution for the constant kernel with an
  !> exponential initial size distribution.
  !!
  !! Given initial number concentration N0 and mean radius R,
  !! define the mean volume v_mu = (4 pi / 3) R^3.
  !!
  !! Initial condition (exponential in volume):
  !!   n(v, 0) = (N0 / v_mu) * exp(-v / v_mu)
  !!
  !! Rescaled time:
  !!   tau = N0 * beta_0 * t
  !!
  !! With lambda = 1 the evolved distribution is:
  !!   n(v, t) = (4 N0) / (v_mu * (tau + 2)^2)
  !!             * exp(-2 (v / v_mu) / (tau + 2) * exp(-lambda*tau)
  !!                   - lambda * tau)
  !!
  !! This subroutine evaluates n(v, t) for a single volume v.
  subroutine soln_constant_exp(time, num_conc, radius_at_mean_vol, &
       v, nn)

    !> Current time (s).
    real(kind=dp), intent(in) :: time
    !> Initial number concentration N0 (#/m^3).
    real(kind=dp), intent(in) :: num_conc
    !> Radius at the mean volume, R (m).
    real(kind=dp), intent(in) :: radius_at_mean_vol
    !> Particle volume (m^3).
    real(kind=dp), intent(in) :: v
    !> Number density n(v, t) (dN/dv, in #/(m^3 m^3)).
    real(kind=dp), intent(out) :: nn

    real(kind=dp) :: tau, rat_v, mean_vol
    real(kind=dp), parameter :: lambda = 1d0

    mean_vol = (4.0d0 / 3.0d0) * const%pi * radius_at_mean_vol**3
    rat_v = v / mean_vol

    if (time == 0d0) then
       nn = num_conc / mean_vol * exp(-rat_v)
    else
       tau = num_conc * beta_0 * time
       nn = 4d0 * num_conc / (mean_vol * (tau + 2d0)**2d0) &
            * exp(-2d0 * rat_v / (tau + 2d0) * exp(-lambda * tau) &
                  - lambda * tau)
    end if

  end subroutine soln_constant_exp

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

end module pmc_coag_kernel_constant
