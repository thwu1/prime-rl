! sedtrans.f90 — Sediment transport computational kernels
! Adapted from XBeach (Deltares) Van Rijn / Dean formulations
!

subroutine fall_velocity(d50, temp, ws)
    implicit none
    double precision, intent(in) :: d50, temp
    double precision, intent(out) :: ws
    double precision :: dsand, dgravel, rhoint, rhosol, ag, s, vcmol, coefw

    rhoint = 1024.0d0
    rhosol = 2650.0d0
    dsand = 0.000064d0
    dgravel = 0.002d0
    ag = 9.81d0
    s = rhosol / rhoint
    vcmol = 4.0d-5 / (20.0d0 + temp)

    if (d50 .lt. 1.5d0 * dsand) then
        ! Stokes settling
        ws = (s - 1.0d0) * ag * d50 * d50 / (18.0d0 * vcmol)
    else if (d50 .lt. 0.5d0 * dgravel) then
        ! Transitional regime
        if (d50 .lt. 2.0d0 * dsand) then
            coefw = (-2.9912d0 / dsand) * d50 + 15.9824d0
        else
            coefw = 10.0d0
        end if
        ws = coefw * vcmol / d50 * &
             (sqrt(1.0d0 + (s - 1.0d0) * ag * d50**3 &
              / (100.0d0 * vcmol**2)) - 1.0d0)
    else
        ! Impact / turbulent regime
        ws = 1.1d0 * sqrt((s - 1.0d0) * ag * d50)
    end if

end subroutine fall_velocity


subroutine equilibrium_profile(x, A, z_offset, z_out, nx)
    implicit none
    integer, intent(in) :: nx
    double precision, intent(in) :: x(:), A, z_offset
    double precision, intent(out) :: z_out(:)
    integer :: i

    do i = 1, nx
        if (x(i) .ge. 0.0d0) then
            z_out(i) = z_offset - A * (x(i))**(2.0d0 / 3.0d0)
        else
            z_out(i) = z_offset
        end if
    end do

end subroutine equilibrium_profile
