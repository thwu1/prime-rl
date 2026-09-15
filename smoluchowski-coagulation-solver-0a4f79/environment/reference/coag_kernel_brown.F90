! Copyright (C) 2005-2011 Nicole Riemer and Matthew West
! Copyright (C) 2007 Richard Easter
! Licensed under the GNU General Public License version 2 or (at your
! option) any later version. See the file COPYING for details.

!> \file
!> The pmc_coag_kernel_brown module.
!!
!! Brownian coagulation kernel in the transition regime for spherical
!! aerosol particles. Combines continuum and free-molecular diffusion
!! regimes via an interpolation formula.
!!
!! The kernel depends on temperature, pressure, and the densities and
!! volumes of the two interacting particles. For spherical, non-fractal
!! particles the mobility radius equals the geometric radius (see
!! aero_helpers.F90).

module pmc_coag_kernel_brown

  use pmc_constants
  implicit none

contains

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  !> Compute the Brownian coagulation kernel for two spherical particles.
  !!
  !! Inputs are particle volumes and densities plus ambient temperature
  !! and pressure. Output is the coagulation kernel in m^3/s.
  !!
  !! Variable glossary:
  !!   rhoair     = air density (kg/m^3)
  !!   viscosd    = dynamic viscosity of air (kg/(m s))
  !!   viscosk    = kinematic viscosity of air (m^2/s)
  !!   gasspeed   = mean thermal velocity of air molecules (m/s)
  !!   gasfreepath = mean free path of air molecules (m)
  !!   knud       = Knudsen number Kn = gasfreepath / Rme
  !!   cunning    = Cunningham slip-flow correction factor
  !!   diffus     = particle Brownian diffusion coefficient (m^2/s)
  !!   speedsq    = square of particle mean thermal speed (m^2/s^2)
  !!   freepath   = particle mean free path (m)
  !!   deltasq    = square of the delta correction parameter
  subroutine kernel_brown_helper(vol_i, den_i, vol_j, den_j, &
       temp, pressure, bckernel)

    !> Volume of first particle (m^3).
    real(kind=dp), intent(in) :: vol_i
    !> Density of first particle (kg/m^3).
    real(kind=dp), intent(in) :: den_i
    !> Volume of second particle (m^3).
    real(kind=dp), intent(in) :: vol_j
    !> Density of second particle (kg/m^3).
    real(kind=dp), intent(in) :: den_j
    !> Temperature (K).
    real(kind=dp), intent(in) :: temp
    !> Pressure (Pa).
    real(kind=dp), intent(in) :: pressure
    !> Coagulation kernel (m^3/s).
    real(kind=dp), intent(out) :: bckernel

    real(kind=dp) :: cunning, deltasq_i, deltasq_j, &
         diffus_i, diffus_j, diffus_sum, freepath, gasfreepath, &
         gasspeed, knud, rad_i, rad_j, rad_sum, rhoair, &
         speedsq_i, speedsq_j, tmp1, tmp2, viscosd, viscosk, &
         Rme_i, Rme_j

    ! --- air thermodynamic properties ---

    rhoair = (pressure * const%air_molec_weight) / &
         (const%univ_gas_const * temp)

    viscosd = 1.8325d-05 * (416.16d0 / (temp + 120d0)) * &
         (temp / 296.16d0)**1.5d0
    viscosk = viscosd / rhoair

    gasspeed = sqrt((8.0d0 * const%boltzmann * temp * const%avagadro) / &
         (const%pi * const%air_molec_weight))
    gasfreepath = 2d0 * viscosk / gasspeed

    ! --- particle i properties ---

    ! geometric radius: r = (3 v / (4 pi))^(1/3)
    rad_i = (3.0d0 * vol_i / (4.0d0 * const%pi))**(1.0d0 / 3.0d0)
    ! mobility radius = geometric radius for spherical particles
    Rme_i = rad_i

    knud      = gasfreepath / Rme_i
    cunning   = 1d0 + knud * (1.249d0 + 0.42d0 * exp(-0.87d0 / knud))
    diffus_i  = (const%boltzmann * temp * cunning) / &
         (6.0d0 * const%pi * Rme_i * viscosd)
    speedsq_i = 8d0 * const%boltzmann * temp / (const%pi * den_i * vol_i)
    freepath  = 8d0 * diffus_i / (const%pi * sqrt(speedsq_i))
    tmp1      = (2d0 * Rme_i + freepath)**3
    tmp2      = (4d0 * Rme_i**2 + freepath**2)**1.5d0
    deltasq_i = ((tmp1 - tmp2) / (6d0 * Rme_i * freepath) &
         - 2d0 * Rme_i)**2

    ! --- particle j properties ---

    rad_j = (3.0d0 * vol_j / (4.0d0 * const%pi))**(1.0d0 / 3.0d0)
    Rme_j = rad_j

    knud      = gasfreepath / Rme_j
    cunning   = 1d0 + knud * (1.249d0 + 0.42d0 * exp(-0.87d0 / knud))
    diffus_j  = (const%boltzmann * temp * cunning) / &
         (6.0d0 * const%pi * Rme_j * viscosd)
    speedsq_j = 8d0 * const%boltzmann * temp / (const%pi * den_j * vol_j)
    freepath  = 8d0 * diffus_j / (const%pi * sqrt(speedsq_j))
    tmp1      = (2d0 * Rme_j + freepath)**3
    tmp2      = (4d0 * Rme_j**2 + freepath**2)**1.5d0
    deltasq_j = ((tmp1 - tmp2) / (6d0 * Rme_j * freepath) &
         - 2d0 * Rme_j)**2

    ! --- combined kernel (transition-regime interpolation) ---

    rad_sum    = rad_i + rad_j
    diffus_sum = diffus_i + diffus_j
    tmp1       = rad_sum / (rad_sum + sqrt(deltasq_i + deltasq_j))
    tmp2       = 4d0 * diffus_sum / (rad_sum * sqrt(speedsq_i + speedsq_j))
    bckernel   = 4d0 * const%pi * rad_sum * diffus_sum / (tmp1 + tmp2)

  end subroutine kernel_brown_helper

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

end module pmc_coag_kernel_brown
