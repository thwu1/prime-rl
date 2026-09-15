!===============================================================
! main.f90 - Driver program for Pekeris waveguide solver
!===============================================================

program pekeris_main
  use pekeris_mod
  implicit none

  double precision, allocatable :: ranges(:), tl_incoh(:), tl_coh(:)
  double precision :: dr
  integer :: i
  character(len=256) :: config_file

  if (command_argument_count() >= 1) then
    call get_command_argument(1, config_file)
  else
    config_file = 'waveguide.cfg'
  end if

  call read_config(trim(config_file))

  write(*,'(A)')           '=== Pekeris Waveguide Normal Mode Solver ==='
  write(*,'(A,F10.2,A)')   'Frequency:    ', freq, ' Hz'
  write(*,'(A,F10.2,A)')   'Water depth:  ', water_depth, ' m'
  write(*,'(A,F10.2,A)')   'Water c:      ', c_water, ' m/s'
  write(*,'(A,F10.4,A)')   'Water rho:    ', rho_water, ' g/cm^3'
  write(*,'(A,F10.2,A)')   'Bottom c:     ', c_bottom, ' m/s'
  write(*,'(A,F10.4,A)')   'Bottom rho:   ', rho_bottom, ' g/cm^3'
  write(*,'(A,F10.6,A)')   'k_water:      ', kw, ' 1/m'
  write(*,'(A,F10.6,A)')   'k_bottom:     ', kb, ' 1/m'

  call find_modes()

  write(*,'(A,I4)')        'Modes found:  ', nmodes

  if (nmodes == 0) then
    write(*,*) 'No modes found. Exiting.'
    stop
  end if

  call write_modes('modes.dat')

  allocate(ranges(n_ranges), tl_incoh(n_ranges), tl_coh(n_ranges))

  if (n_ranges > 1) then
    dr = (rng_max_km - rng_min_km) / dble(n_ranges - 1)
  else
    dr = 0.0d0
  end if

  do i = 1, n_ranges
    ranges(i) = rng_min_km + dble(i - 1) * dr
  end do

  call compute_incoherent_tl(ranges, tl_incoh, n_ranges)
  call write_tl('tl_incoherent.dat', ranges, tl_incoh, n_ranges)

  call compute_coherent_tl(ranges, tl_coh, n_ranges)
  call write_tl('tl_coherent.dat', ranges, tl_coh, n_ranges)

  call compute_pressure_field(ranges, n_ranges, 'pressure_field.dat')

  write(*,'(A)') 'Output: modes.dat, tl_incoherent.dat, tl_coherent.dat, pressure_field.dat'

  deallocate(ranges, tl_incoh, tl_coh)
  if (allocated(modal_kr)) &
    deallocate(modal_kr, modal_gamma, modal_delta, modal_alpha, modal_vg)

end program pekeris_main
