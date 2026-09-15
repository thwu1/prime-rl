! main.f90 - COMPLETE version with K14 dispatch
! Driver program for multi-scheme dust emission computation
!
! Reads scheme name and scenario data from stdin, dispatches to the
! selected scheme, and writes diagnostic output to stdout.
!

program dust_emission_driver
  use dust_physics_mod, only: compute_emission_cell
  use dust_k14_mod, only: compute_k14_cell
  implicit none

  character(len=20) :: scheme
  integer :: n_cells, i, ios
  real :: wind_10m, rho_air, soil_moist_vol
  real :: clay_f, silt_f, sand_f, veg_frac
  integer :: land_type, soil_type

  ! Output variables
  real :: out_ustar, out_uts0, out_fm, out_fr
  real :: out_z0, out_sep, out_hflux, out_alpha
  real :: out_vflux, out_emission

  ! Read scheme name
  read(*, '(A)', iostat=ios) scheme
  if (ios /= 0) then
    write(0, '(A)') 'Error: could not read scheme name'
    stop 1
  end if

  ! Read number of cells
  read(*, *, iostat=ios) n_cells
  if (ios /= 0) then
    write(0, '(A)') 'Error: could not read number of cells'
    stop 1
  end if

  ! Write header
  write(*, '(A)') 'cell_id u_star u_ts0 f_moist f_rough z0 ' // &
                   'sep h_flux alpha v_flux emission'

  do i = 1, n_cells
    read(*, *, iostat=ios) wind_10m, rho_air, soil_moist_vol, &
               clay_f, silt_f, sand_f, veg_frac, &
               land_type, soil_type

    if (ios /= 0) then
      write(0, '(A,I4)') 'Error reading cell ', i
      stop 1
    end if

    if (trim(scheme) == 'fengsha') then
      call compute_emission_cell( &
          wind_10m, rho_air, soil_moist_vol, &
          clay_f, silt_f, sand_f, veg_frac, &
          land_type, soil_type, &
          out_ustar, out_uts0, out_fm, out_fr, &
          out_z0, out_sep, out_hflux, out_alpha, &
          out_vflux, out_emission)

    else if (trim(scheme) == 'k14') then
      call compute_k14_cell( &
          wind_10m, rho_air, soil_moist_vol, &
          clay_f, silt_f, sand_f, veg_frac, &
          land_type, soil_type, &
          out_ustar, out_uts0, out_fm, out_fr, &
          out_z0, out_sep, out_hflux, out_alpha, &
          out_vflux, out_emission)

    else
      write(0, '(A,A)') 'Error: unknown scheme ', trim(scheme)
      stop 1
    end if

    write(*, '(I4, 10(1X, ES15.8))') i, &
        out_ustar, out_uts0, out_fm, out_fr, &
        out_z0, out_sep, out_hflux, out_alpha, &
        out_vflux, out_emission

  end do

end program
