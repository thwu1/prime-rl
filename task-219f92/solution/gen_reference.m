% gen_reference.m — Generate Octave reference data for cross-validation.
%
% Run from /app: octave --no-gui --silent octave/gen_reference.m
%
% Produces CSV files in /app/reference/:
%   phi_coeffs.csv     — phi_k(z) values
%   etd4rk_coeffs.csv  — ETD4RK update coefficients
%   ks_ref.csv         — KS equation reference solution via lsode

addpath('/app/octave');

% Create output directory
[~, ~, ~] = mkdir('/app/reference');

% ===== 1. Phi-function reference values =====
z_vals = [-100, -50, -20, -10, -5, -1, -0.5, -0.1, -1e-6, 0, 1e-6, 0.1, 0.5, 1, 2, 5];
nz = length(z_vals);
phi_data = zeros(nz, 5);
phi_data(:, 1) = z_vals(:);
for k = 0:3
    for i = 1:nz
        phi_data(i, k + 2) = phifun(z_vals(i), k);
    end
end
dlmwrite('/app/reference/phi_coeffs.csv', phi_data, 'delimiter', ',', 'precision', '%.18e');

% ===== 2. ETD4RK coefficient reference values =====
hL_vals = [-50, -20, -10, -5, -1, -0.1];
nhL = length(hL_vals);
coeff_data = zeros(nhL, 4);
coeff_data(:, 1) = hL_vals(:);
for i = 1:nhL
    hL = hL_vals(i);
    p1 = phifun(hL, 1);
    p2 = phifun(hL, 2);
    p3 = phifun(hL, 3);
    coeff_data(i, 2) = p1 - 3*p2 + 4*p3;
    coeff_data(i, 3) = 2*(p2 - 2*p3);
    coeff_data(i, 4) = -p2 + 4*p3;
end
dlmwrite('/app/reference/etd4rk_coeffs.csv', coeff_data, 'delimiter', ',', 'precision', '%.18e');

% ===== 3. KS equation reference solution via lsode =====
global Lk_g k_g N_g;

L_domain = 32 * pi;
N_modes = 64;

[x, k_wave, Lk, u0_hat] = ks_setup(L_domain, N_modes);
Lk_g = Lk;
k_g = k_wave;
N_g = N_modes;

% Split complex state into real/imaginary for lsode
y0 = [real(u0_hat); imag(u0_hat)];

lsode_options('absolute tolerance', 1e-12);
lsode_options('relative tolerance', 1e-12);
lsode_options('integration method', 'stiff');

t_out = linspace(0, 1.0, 51);
sol = lsode(@ks_rhs, y0, t_out);

u_ref_hat = sol(end, 1:N_modes)' + 1i * sol(end, N_modes+1:2*N_modes)';
u_ref = real(ifft(u_ref_hat));

dlmwrite('/app/reference/ks_ref.csv', u_ref', 'delimiter', ',', 'precision', '%.18e');

printf('Reference data generated successfully.\n');
