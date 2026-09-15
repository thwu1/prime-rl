function [x, k, Lk, u0_hat] = ks_setup(L, N)
% KS_SETUP  Fourier spectral discretization of the Kuramoto-Sivashinsky equation.
%
%   [x, k, Lk, u0_hat] = ks_setup(L, N)
%
%   KS equation: u_t + u*u_x + u_xx + u_xxxx = 0
%   on [0, L] with periodic boundary conditions.
%
%   Returns:
%     x      - spatial grid (N points), column vector
%     k      - wavenumbers (matching numpy.fft.fftfreq), column vector
%     Lk     - linear operator k^2 - k^4, column vector
%     u0_hat - FFT of initial condition, column vector
%
%   Initial condition: u0(x) = cos(x/16) * (1 + sin(x/16))

x = L * (0:N-1)' / N;

% Wavenumbers matching numpy.fft.fftfreq convention
k = zeros(N, 1);
if mod(N, 2) == 0
    k(1:N/2) = (0:N/2-1)';
    k(N/2+1:N) = (-N/2:-1)';
else
    k(1:(N+1)/2) = (0:(N-1)/2)';
    k((N+1)/2+1:N) = (-(N-1)/2:-1)';
end
k = 2 * pi * k / L;

Lk = k.^2 - k.^4;

u0 = cos(x / 16) .* (1 + sin(x / 16));
u0_hat = fft(u0);
end
