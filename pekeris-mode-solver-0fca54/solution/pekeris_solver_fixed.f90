!===============================================================
! pekeris_solver.f90 - Normal mode solver for Pekeris waveguide
!
! FIXED VERSION: All physics/numerics corrections applied and
! pressure field computation implemented.
!===============================================================

module pekeris_mod
  implicit none

  double precision, parameter :: PI = 3.14159265358979323846d0

  double precision :: freq, omega, water_depth
  double precision :: c_water, rho_water
  double precision :: c_bottom, rho_bottom, attn_bottom
  double precision :: src_depth, rcv_depth
  double precision :: rng_min_km, rng_max_km
  integer          :: n_ranges

  double precision :: kw, kb

  integer :: nmodes
  double precision, allocatable :: modal_kr(:), modal_gamma(:)
  double precision, allocatable :: modal_delta(:), modal_alpha(:)
  double precision, allocatable :: modal_vg(:)

contains

  subroutine read_config(cfgfile)
    character(len=*), intent(in) :: cfgfile
    character(len=512) :: line
    character(len=64)  :: key
    double precision   :: val
    integer            :: ios, iu

    iu = 10
    open(unit=iu, file=cfgfile, status='old', action='read', iostat=ios)
    if (ios /= 0) then
      write(*,'(A,A)') 'ERROR: Cannot open config file: ', trim(cfgfile)
      stop 1
    end if

    freq = 100.0d0;      water_depth = 100.0d0
    c_water = 1500.0d0;  rho_water = 1.0d0
    c_bottom = 1700.0d0; rho_bottom = 1.5d0; attn_bottom = 0.5d0
    src_depth = 36.0d0;  rcv_depth = 46.0d0
    rng_min_km = 1.0d0;  rng_max_km = 100.0d0; n_ranges = 200

    do
      read(iu, '(A)', iostat=ios) line
      if (ios /= 0) exit
      line = adjustl(line)
      if (len_trim(line) == 0) cycle
      if (line(1:1) == '#' .or. line(1:1) == '!') cycle

      read(line, *, iostat=ios) key, val
      if (ios /= 0) cycle

      select case(trim(key))
        case('frequency_hz');       freq = val
        case('water_depth_m');      water_depth = val
        case('water_speed_mps');    c_water = val
        case('water_density');      rho_water = val
        case('bottom_speed_mps');   c_bottom = val
        case('bottom_density');     rho_bottom = val
        case('bottom_attn_dbplam'); attn_bottom = val
        case('source_depth_m');     src_depth = val
        case('receiver_depth_m');   rcv_depth = val
        case('min_range_km');       rng_min_km = val
        case('max_range_km');       rng_max_km = val
        case('num_ranges');         n_ranges = nint(val)
      end select
    end do

    close(iu)

    omega = 2.0d0 * PI * freq
    kw = omega / c_water
    kb = omega / c_bottom

  end subroutine read_config

  ! FIX 1: Correct impedance matching condition
  ! rho_bottom * gamma * cos(gamma*H) + rho_water * delta * sin(gamma*H) = 0
  double precision function char_func(k_h)
    double precision, intent(in) :: k_h
    double precision :: gv, dv, gh

    gv = sqrt(kw**2 - k_h**2)
    dv = sqrt(k_h**2 - kb**2)
    gh = gv * water_depth

    char_func = rho_bottom * gv * cos(gh) + rho_water * dv * sin(gh)

  end function char_func

  subroutine count_and_bracket(n_found, bk_lo, bk_hi, max_modes)
    integer, intent(out)   :: n_found
    integer, intent(in)    :: max_modes
    double precision, intent(out) :: bk_lo(max_modes), bk_hi(max_modes)

    integer :: i, nscan
    double precision :: k_lo, k_hi, dk, k_prev, k_curr
    double precision :: f_prev, f_curr

    nscan = 100000
    k_lo = kb * 1.000001d0
    k_hi = kw * 0.999999d0
    dk = (k_hi - k_lo) / dble(nscan)

    n_found = 0
    k_prev = k_lo
    f_prev = char_func(k_lo)

    do i = 1, nscan
      k_curr = k_lo + dble(i) * dk
      f_curr = char_func(k_curr)

      if (f_prev * f_curr < 0.0d0) then
        n_found = n_found + 1
        if (n_found <= max_modes) then
          bk_lo(n_found) = k_prev
          bk_hi(n_found) = k_curr
        end if
      end if

      k_prev = k_curr
      f_prev = f_curr
    end do

  end subroutine count_and_bracket

  subroutine find_modes()
    integer, parameter :: MAX_MODES = 500
    integer :: m, iter, max_iter
    double precision :: bk_lo(MAX_MODES), bk_hi(MAX_MODES)
    double precision :: a, b, c_mid, fa, fc
    double precision :: tol

    max_iter = 300
    tol = 1.0d-15

    call count_and_bracket(nmodes, bk_lo, bk_hi, MAX_MODES)

    if (nmodes == 0) then
      write(*,*) 'WARNING: No propagating modes found'
      return
    end if

    allocate(modal_kr(nmodes), modal_gamma(nmodes), &
             modal_delta(nmodes), modal_alpha(nmodes), modal_vg(nmodes))

    do m = 1, nmodes
      a = bk_lo(m)
      b = bk_hi(m)
      fa = char_func(a)

      do iter = 1, max_iter
        c_mid = 0.5d0 * (a + b)
        fc = char_func(c_mid)

        if (abs(fc) < tol .or. abs(b - a) < tol * abs(c_mid)) exit

        if (fa * fc < 0.0d0) then
          b = c_mid
        else
          a = c_mid
          fa = fc
        end if
      end do

      modal_kr(m)    = 0.5d0 * (a + b)
      modal_gamma(m) = sqrt(kw**2 - modal_kr(m)**2)
      modal_delta(m) = sqrt(modal_kr(m)**2 - kb**2)
    end do

    call sort_modes()
    call compute_modal_attn()
    call compute_group_vel()

  end subroutine find_modes

  subroutine sort_modes()
    integer :: i, j
    double precision :: t

    do i = 1, nmodes - 1
      do j = i + 1, nmodes
        if (modal_kr(j) > modal_kr(i)) then
          t = modal_kr(i);    modal_kr(i) = modal_kr(j);    modal_kr(j) = t
          t = modal_gamma(i); modal_gamma(i) = modal_gamma(j); modal_gamma(j) = t
          t = modal_delta(i); modal_delta(i) = modal_delta(j); modal_delta(j) = t
        end if
      end do
    end do
  end subroutine sort_modes

  ! FIX 2: Normalization includes bottom half-space contribution
  double precision function mode_norm(m)
    integer, intent(in) :: m
    double precision :: g, d, gH

    g  = modal_gamma(m)
    d  = modal_delta(m)
    gH = g * water_depth

    mode_norm = water_depth / 2.0d0 - sin(2.0d0 * gH) / (4.0d0 * g) &
              + (rho_water / rho_bottom) * sin(gH)**2 / (2.0d0 * d)

  end function mode_norm

  double precision function phi(m, z)
    integer, intent(in) :: m
    double precision, intent(in) :: z
    double precision :: nrm

    nrm = mode_norm(m)
    if (nrm <= 0.0d0) then
      phi = 0.0d0
    else
      phi = sin(modal_gamma(m) * z) / sqrt(nrm)
    end if
  end function phi

  subroutine compute_modal_attn()
    integer :: m
    double precision :: alpha_np, lambda_b, nrm

    lambda_b = c_bottom / freq
    alpha_np = attn_bottom / (20.0d0 * log10(exp(1.0d0)) * lambda_b)

    do m = 1, nmodes
      nrm = mode_norm(m)
      if (nrm <= 0.0d0) then
        modal_alpha(m) = 0.0d0
      else
        modal_alpha(m) = alpha_np * (rho_water / rho_bottom) * &
                         sin(modal_gamma(m) * water_depth)**2 / &
                         (modal_delta(m) * nrm)
      end if
    end do
  end subroutine compute_modal_attn

  ! FIX 4: Update kw and kb when evaluating dispersion relation
  ! at perturbed frequencies for group velocity computation
  subroutine compute_group_vel()
    integer :: m, iter, max_iter
    double precision :: df, omg_plus, omg_minus
    double precision :: kr_plus, kr_minus
    double precision :: a, b, c_mid, fa, fc, tol
    double precision :: kw_save, kb_save, omega_save

    df = freq * 1.0d-4
    max_iter = 200
    tol = 1.0d-14

    kw_save = kw
    kb_save = kb
    omega_save = omega

    do m = 1, nmodes

      ! --- Find eigenvalue at freq + df ---
      omg_plus = 2.0d0 * PI * (freq + df)
      omega = omg_plus
      kw = omega / c_water
      kb = omega / c_bottom

      a = modal_kr(m) * 0.995d0
      b = modal_kr(m) * 1.005d0
      if (a < kb * 1.000001d0) a = kb * 1.000001d0
      if (b > kw * 0.999999d0) b = kw * 0.999999d0

      kr_plus = modal_kr(m)
      if (b > a) then
        fa = char_func(a)
        do iter = 1, max_iter
          c_mid = 0.5d0 * (a + b)
          fc = char_func(c_mid)
          if (abs(fc) < tol .or. abs(b - a) < tol * abs(c_mid)) then
            kr_plus = c_mid
            exit
          end if
          if (fa * fc < 0.0d0) then
            b = c_mid
          else
            a = c_mid
            fa = fc
          end if
        end do
      end if

      ! --- Find eigenvalue at freq - df ---
      omg_minus = 2.0d0 * PI * (freq - df)
      omega = omg_minus
      kw = omega / c_water
      kb = omega / c_bottom

      a = modal_kr(m) * 0.995d0
      b = modal_kr(m) * 1.005d0
      if (a < kb * 1.000001d0) a = kb * 1.000001d0
      if (b > kw * 0.999999d0) b = kw * 0.999999d0

      kr_minus = modal_kr(m)
      if (b > a) then
        fa = char_func(a)
        do iter = 1, max_iter
          c_mid = 0.5d0 * (a + b)
          fc = char_func(c_mid)
          if (abs(fc) < tol .or. abs(b - a) < tol * abs(c_mid)) then
            kr_minus = c_mid
            exit
          end if
          if (fa * fc < 0.0d0) then
            b = c_mid
          else
            a = c_mid
            fa = fc
          end if
        end do
      end if

      if (abs(kr_plus - kr_minus) > 1.0d-20) then
        modal_vg(m) = (omg_plus - omg_minus) / (kr_plus - kr_minus)
      else
        modal_vg(m) = omega_save / modal_kr(m)
      end if
    end do

    omega = omega_save
    kw = kw_save
    kb = kb_save

  end subroutine compute_group_vel

  ! FIX 3: Include 1/kr factor in incoherent TL
  subroutine compute_incoherent_tl(ranges_km, tl_db, nr)
    integer, intent(in)          :: nr
    double precision, intent(in) :: ranges_km(nr)
    double precision, intent(out):: tl_db(nr)

    integer :: ir, m
    double precision :: r_m, psq, ps, pr, contrib

    do ir = 1, nr
      r_m = ranges_km(ir) * 1.0d3
      if (r_m < 1.0d0) r_m = 1.0d0

      psq = 0.0d0
      do m = 1, nmodes
        ps = phi(m, src_depth)
        pr = phi(m, rcv_depth)

        contrib = ps**2 * pr**2 * exp(-2.0d0 * modal_alpha(m) * r_m) &
                / (modal_kr(m) * r_m)
        psq = psq + contrib
      end do

      psq = psq / (8.0d0 * PI)

      if (psq > 0.0d0) then
        tl_db(ir) = -10.0d0 * log10(psq)
      else
        tl_db(ir) = 999.0d0
      end if
    end do
  end subroutine compute_incoherent_tl

  ! FIX 5: Correct Hankel function approximation for coherent TL
  ! H_0^(1)(x) ~ sqrt(2/(pi*x)) * exp(i*(x - pi/4))
  subroutine compute_coherent_tl(ranges_km, tl_db, nr)
    integer, intent(in)          :: nr
    double precision, intent(in) :: ranges_km(nr)
    double precision, intent(out):: tl_db(nr)

    integer :: ir, m
    double precision :: r_m, p_re, p_im, ps, pr, ampl, phase

    do ir = 1, nr
      r_m = ranges_km(ir) * 1.0d3
      if (r_m < 1.0d0) r_m = 1.0d0

      p_re = 0.0d0
      p_im = 0.0d0
      do m = 1, nmodes
        ps = phi(m, src_depth)
        pr = phi(m, rcv_depth)

        ampl = ps * pr * exp(-modal_alpha(m) * r_m) &
             / sqrt(8.0d0 * PI * modal_kr(m) * r_m)
        phase = modal_kr(m) * r_m - PI / 4.0d0

        p_re = p_re + ampl * cos(phase)
        p_im = p_im + ampl * sin(phase)
      end do

      if (p_re**2 + p_im**2 > 0.0d0) then
        tl_db(ir) = -10.0d0 * log10(p_re**2 + p_im**2)
      else
        tl_db(ir) = 999.0d0
      end if
    end do
  end subroutine compute_coherent_tl

  ! FIX 6: Implement proper coherent pressure field computation
  ! over a depth-range grid using modal summation with correct
  ! Hankel function asymptotics
  subroutine compute_pressure_field(ranges_km, nr, fname)
    integer, intent(in) :: nr
    double precision, intent(in) :: ranges_km(nr)
    character(len=*), intent(in) :: fname

    integer :: iu, iz, ir, m, nz, ios
    double precision :: z, r_m, g, ps, pr_z, nrm
    double precision :: ampl, phase, p_re, p_im, p_sq, tl_val

    nz = nint(water_depth)
    iu = 22
    open(unit=iu, file=fname, status='replace', action='write', iostat=ios)
    if (ios /= 0) then
      write(*,*) 'ERROR: Cannot write ', trim(fname)
      return
    end if

    write(iu, '(A)') '# depth_m  range_km  TL_dB'
    do iz = 1, nz
      z = dble(iz)
      do ir = 1, nr
        r_m = ranges_km(ir) * 1.0d3
        if (r_m < 1.0d0) r_m = 1.0d0

        p_re = 0.0d0
        p_im = 0.0d0
        do m = 1, nmodes
          g = modal_gamma(m)
          nrm = mode_norm(m)
          if (nrm <= 0.0d0) cycle
          ps = sin(g * src_depth) / sqrt(nrm)
          pr_z = sin(g * z) / sqrt(nrm)
          ampl = ps * pr_z * exp(-modal_alpha(m) * r_m) &
               / sqrt(8.0d0 * PI * modal_kr(m) * r_m)
          phase = modal_kr(m) * r_m - PI / 4.0d0
          p_re = p_re + ampl * cos(phase)
          p_im = p_im + ampl * sin(phase)
        end do

        p_sq = p_re**2 + p_im**2
        if (p_sq > 0.0d0) then
          tl_val = -10.0d0 * log10(p_sq)
        else
          tl_val = 999.0d0
        end if
        write(iu, '(F8.1, F12.4, F14.4)') z, ranges_km(ir), tl_val
      end do
    end do
    close(iu)
  end subroutine compute_pressure_field

  subroutine write_modes(fname)
    character(len=*), intent(in) :: fname
    integer :: m, ios, iu

    iu = 20
    open(unit=iu, file=fname, status='replace', action='write', iostat=ios)
    if (ios /= 0) then
      write(*,*) 'ERROR: Cannot write ', trim(fname)
      return
    end if

    write(iu, '(A, I6)') '# num_modes ', nmodes
    write(iu, '(A)') '# mode    kr(1/m)              phase_speed(m/s)' // &
                      '     group_speed(m/s)     attenuation(1/m)'

    do m = 1, nmodes
      write(iu, '(I6, 4ES22.14)') m, modal_kr(m), omega / modal_kr(m), &
                                   modal_vg(m), modal_alpha(m)
    end do

    close(iu)
  end subroutine write_modes

  subroutine write_tl(fname, ranges_km, tl_db, nr)
    character(len=*), intent(in) :: fname
    integer, intent(in) :: nr
    double precision, intent(in) :: ranges_km(nr), tl_db(nr)
    integer :: ir, ios, iu

    iu = 21
    open(unit=iu, file=fname, status='replace', action='write', iostat=ios)
    if (ios /= 0) then
      write(*,*) 'ERROR: Cannot write ', trim(fname)
      return
    end if

    write(iu, '(A)') '# range_km           tl_db'

    do ir = 1, nr
      write(iu, '(F12.4, F16.6)') ranges_km(ir), tl_db(ir)
    end do

    close(iu)
  end subroutine write_tl

end module pekeris_mod
