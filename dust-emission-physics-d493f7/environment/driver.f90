program dust_driver
  use dust_physics
  implicit none

  double precision :: Dp, rho_p, rho_a, ustar_in
  double precision :: clay_frac, silt_frac, sand_frac
  double precision :: w_vol, z0_in, z0s
  double precision :: lambda_r, h_eff, f_w
  integer :: bedrock_flag
  logical :: is_bedrock

  double precision :: ust0, w_grav_pct, fm, Rp
  double precision :: ustar_t, ustar_soil, sep
  double precision :: alpha_mb95, FH, FV_k14
  double precision :: z0_foro, f_erod, k_gamma
  double precision :: size_fracs(N_BINS)
  double precision :: bin_emissions(N_BINS)
  integer :: rc, i

  character(len=256) :: input_file
  character(len=20) :: key
  integer :: ios

  if (command_argument_count() < 1) then
    write(*,*) 'Usage: dust_driver <input_file>'
    stop 1
  end if
  call get_command_argument(1, input_file)

  open(unit=10, file=trim(input_file), status='old', iostat=ios)
  if (ios /= 0) then
    write(*,*) 'Error: cannot open ', trim(input_file)
    stop 1
  end if

  read(10,*) Dp
  read(10,*) rho_p
  read(10,*) rho_a
  read(10,*) ustar_in
  read(10,*) clay_frac
  read(10,*) silt_frac
  read(10,*) sand_frac
  read(10,*) w_vol
  read(10,*) z0_in
  read(10,*) z0s
  read(10,*) lambda_r
  read(10,*) h_eff
  read(10,*) bedrock_flag
  read(10,*) f_w
  close(10)

  is_bedrock = (bedrock_flag /= 0)

  ! Compute individual routine diagnostics
  ust0 = threshold_ustar(Dp, rho_p, rho_a)
  w_grav_pct = gravimetric_moisture(w_vol, sand_frac, f_w)
  fm = fecan_moisture_correction(w_grav_pct, clay_frac * 100.0d0)
  Rp = drag_partition_mackinnon(z0_in, z0s)
  ustar_soil = Rp * ustar_in
  ustar_t = ust0 * fm
  alpha_mb95 = mb95_v2h_ratio(clay_frac, 2.0d-4)
  sep = soil_erodibility_potential(clay_frac, silt_frac, sand_frac)
  FH = white79_saltation_flux(rho_a, ustar_soil, ustar_t)
  f_erod = erodibility_factor(z0_in, is_bedrock)
  k_gamma = clay_frac
  FV_k14 = k14_vertical_flux(ustar_soil, ustar_t, rho_a, f_erod, k_gamma)
  z0_foro = foroutan_roughness_length(lambda_r, h_eff)

  ! Compute size fractions
  do i = 1, N_BINS
    size_fracs(i) = kok2011_size_fraction(BIN_BOUNDS(i), BIN_BOUNDS(i+1))
  end do

  ! Compute coupled per-bin emissions
  call compute_cell_emission(rho_p, rho_a, ustar_in, &
       clay_frac, silt_frac, sand_frac, &
       w_vol, z0_in, z0s, is_bedrock, f_w, &
       bin_emissions, rc)

  ! Output individual diagnostics
  write(*,'(A,1X,ES22.14)') 'threshold_ustar', ust0
  write(*,'(A,1X,ES22.14)') 'grav_moisture_pct', w_grav_pct
  write(*,'(A,1X,ES22.14)') 'moisture_factor', fm
  write(*,'(A,1X,ES22.14)') 'drag_partition', Rp
  write(*,'(A,1X,ES22.14)') 'ustar_soil', ustar_soil
  write(*,'(A,1X,ES22.14)') 'ustar_threshold', ustar_t
  write(*,'(A,1X,ES22.14)') 'mb95_ratio', alpha_mb95
  write(*,'(A,1X,ES22.14)') 'sep', sep
  write(*,'(A,1X,ES22.14)') 'white79_flux', FH
  write(*,'(A,1X,ES22.14)') 'erodibility', f_erod
  write(*,'(A,1X,ES22.14)') 'k14_flux', FV_k14
  write(*,'(A,1X,ES22.14)') 'foroutan_z0', z0_foro

  ! Output size fractions
  do i = 1, N_BINS
    write(key, '(A,I1)') 'size_frac_', i
    write(*,'(A,1X,ES22.14)') trim(key), size_fracs(i)
  end do

  ! Output per-bin emissions
  do i = 1, N_BINS
    write(key, '(A,I1)') 'bin_emission_', i
    write(*,'(A,1X,ES22.14)') trim(key), bin_emissions(i)
  end do

end program dust_driver
