function dydt = ks_rhs(y, t)
% KS_RHS  Right-hand side of the Kuramoto-Sivashinsky equation for lsode.
%
%   dydt = ks_rhs(y, t)
%
%   The state y is [real(u_hat); imag(u_hat)] (real-valued vector of length 2*N).
%   Uses global variables Lk_g, k_g, N_g set by the calling script.

global Lk_g k_g N_g;

N = N_g;
u_hat = y(1:N) + 1i * y(N+1:2*N);

% Physical space for nonlinear term
u = real(ifft(u_hat));

% Nonlinear term: N(u_hat) = -j*k/2 * FFT(u^2)
nl = -0.5i * k_g .* fft(u.^2);

% Full RHS: L*u_hat + N(u_hat)
dudt = Lk_g .* u_hat + nl;

dydt = [real(dudt); imag(dudt)];
end
