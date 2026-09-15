!
! Polynomial root-finding benchmark using polyroots-fortran.
! Computes roots of P(x) = (x-1)^8 + 1e-4 using multiple methods,
! evaluates backward errors, and writes structured output.

program benchmark

  use iso_fortran_env, only: output_unit
  use polyroots_module, wp => polyroots_module_rk

  implicit none

  integer, parameter :: deg = 8
  real(wp) :: p(deg+1)
  real(wp) :: zr(deg), zi(deg), s(deg)
  complex(wp) :: r(deg)
  integer :: istatus, ounit
  real(wp) :: detil

  ! P(x) = (x-1)^8 + 1e-4
  ! Expanded: x^8 - 8x^7 + 28x^6 - 56x^5 + 70x^4 - 56x^3 + 28x^2 - 8x + 1.0001
  ! Coefficients in descending order of power
  p = [1.0_wp, -8.0_wp, 28.0_wp, -56.0_wp, 70.0_wp, &
       -56.0_wp, 28.0_wp, -8.0_wp, 1.0001_wp]

  ! Open output file (precision-dependent filename)
#ifdef REAL128
  open(newunit=ounit, file='/tmp/output_r128.txt', status='replace')
  write(ounit, '(A)') 'PRECISION real128'
#else
  open(newunit=ounit, file='/tmp/output_r64.txt', status='replace')
  write(ounit, '(A)') 'PRECISION real64'
#endif

  ! === rpoly (Jenkins-Traub for real polynomials) ===
  ! Note: rpoly uses argument order (coeffs, degree, zr, zi, status)
  call rpoly(p, deg, zr, zi, istatus)
  call report('rpoly', istatus, zr, zi, ounit)

  ! === rpzero (SLATEC) ===
  ! Note: istatus must be set to 0 before call (0 = no initial estimates)
  istatus = 0
  call rpzero(deg, p, r, istatus, s)
  call report('rpzero', istatus, real(r, wp), aimag(r), ounit)

  ! === rpqr79 (SLATEC QR) ===
  call rpqr79(deg, p, r, istatus)
  call report('rpqr79', istatus, real(r, wp), aimag(r), ounit)

  ! === dpolz (MATH77) ===
  call dpolz(deg, p, zr, zi, istatus)
  call report('dpolz', istatus, zr, zi, ounit)

#ifndef REAL128
  ! === polyroots (LAPACK companion matrix eigenvalues) ===
  ! This method is NOT available at real128 precision
  call polyroots(deg, p, zr, zi, istatus)
  call report('polyroots', istatus, zr, zi, ounit)
#endif

  ! === qr_algeq_solver (Edelman-Murakami) ===
  call qr_algeq_solver(deg, p, zr, zi, istatus, detil=detil)
  call report('qr_algeq_solver', istatus, zr, zi, ounit)

  close(ounit)

contains

  subroutine report(name, status, re, im, unit)
    character(len=*), intent(in) :: name
    integer, intent(in) :: status, unit
    real(wp), intent(in) :: re(deg), im(deg)

    complex(wp) :: z, val
    real(wp) :: berr, max_berr
    integer :: j, k

    if (status /= 0) then
      write(unit, '(A,1X,A,1X,A,1X,I0)') 'METHOD', trim(name), 'FAILED', status
      return
    end if

    ! Compute max backward error using Horner's method
    max_berr = 0.0_wp
    do j = 1, deg
      z = cmplx(re(j), im(j), wp)
      val = p(1)
      do k = 2, deg + 1
        val = val * z + p(k)
      end do
      berr = abs(val)
      if (berr > max_berr) max_berr = berr
    end do

    write(unit, '(A,1X,A,1X,ES25.16,1X,I0)') 'METHOD', trim(name), max_berr, status

    ! Output each root
    do j = 1, deg
      write(unit, '(A,1X,A,1X,I0,1X,ES25.16,1X,ES25.16)') &
        'ROOT', trim(name), j, re(j), im(j)
    end do

  end subroutine report

end program benchmark
