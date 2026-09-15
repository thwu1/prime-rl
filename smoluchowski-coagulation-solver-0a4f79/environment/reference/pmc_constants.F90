! Copyright (C) 2005-2012 Nicole Riemer and Matthew West
! Licensed under the GNU General Public License version 2 or (at your
! option) any later version. See the file COPYING for details.

!> \file
!> The pmc_constants module.

!> Physical and mathematical constants used throughout PartMC.
module pmc_constants

  implicit none

  !> Kind parameter for double precision.
  integer, parameter :: dp = kind(0.d0)

  !> Physical and mathematical constants.
  type :: const_t
     !> Pi.
     real(kind=dp) :: pi = 3.14159265358979323846d0
     !> Boltzmann constant (J/K).
     real(kind=dp) :: boltzmann = 1.38065d-23
     !> Avogadro's number (1/mol).
     real(kind=dp) :: avagadro = 6.02214076d23
     !> Universal gas constant (J/(mol K)).
     real(kind=dp) :: univ_gas_const = 8.31446d0
     !> Molecular weight of air (kg/mol).
     real(kind=dp) :: air_molec_weight = 28.97d-3
  end type const_t

  !> Pre-constructed constants instance.
  type(const_t), parameter :: const = const_t()

end module pmc_constants
