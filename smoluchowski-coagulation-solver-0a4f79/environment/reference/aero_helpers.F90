! Aerosol geometry helpers (simplified from PartMC pmc_aero_data module).
!
! In the full PartMC codebase these functions take an aero_data_t argument
! for species-dependent properties and fractal dimension. For spherical,
! non-fractal, single-species particles the computations reduce to the
! pure-geometry forms shown here.

module pmc_aero_helpers

  use pmc_constants
  implicit none

contains

  !> Convert particle volume (m^3) to geometric radius (m).
  !! r = (3 v / (4 pi))^(1/3)
  pure function vol2rad(v) result(r)
    real(kind=dp), intent(in) :: v
    real(kind=dp) :: r
    r = (3.0d0 * v / (4.0d0 * const%pi))**(1.0d0 / 3.0d0)
  end function vol2rad

  !> Convert geometric radius (m) to particle volume (m^3).
  !! v = (4/3) pi r^3
  pure function rad2vol(r) result(v)
    real(kind=dp), intent(in) :: r
    real(kind=dp) :: v
    v = (4.0d0 / 3.0d0) * const%pi * r**3
  end function rad2vol

  !> Mobility radius for spherical, non-fractal particles.
  !!
  !! For spherical particles (do_fractal = .false. in PartMC config),
  !! the mobility radius equals the geometric radius:
  !!   mobility_rad(v) = vol2rad(v)
  !!
  !! This function appears in the Brownian kernel source as
  !! aero_data_vol_to_mobility_rad(aero_data, v, temp, pressure).
  !! The temp and pressure arguments are unused for spheres.
  pure function mobility_rad(v) result(r)
    real(kind=dp), intent(in) :: v
    real(kind=dp) :: r
    r = vol2rad(v)
  end function mobility_rad

end module pmc_aero_helpers
