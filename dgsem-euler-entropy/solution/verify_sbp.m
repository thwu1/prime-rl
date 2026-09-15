% verify_sbp.m -- SBP property verification using GNU Octave

M = dlmread('/app/results/mass_matrix.csv', ',');
D = dlmread('/app/results/deriv_matrix.csv', ',');
n = size(M, 1);

% SBP property: Q + Q^T = B where Q = M*D, B = diag(-1, 0, ..., 0, 1)
Q = M * D;
B = zeros(n);
B(1, 1) = -1;
B(n, n) = 1;

sbp_err = norm(Q + Q' - B, 'fro');
mc = cond(M);
sr = max(abs(eig(D)));

% Write results as JSON
fid = fopen('/app/results/spectral.json', 'w');
fprintf(fid, '{\n');
fprintf(fid, '  "sbp_error": %.15e,\n', sbp_err);
fprintf(fid, '  "mass_cond": %.15e,\n', mc);
fprintf(fid, '  "D_spectral_radius": %.15e\n', sr);
fprintf(fid, '}\n');
fclose(fid);

fprintf('SBP error: %e\n', sbp_err);
fprintf('Mass cond: %e\n', mc);
fprintf('D spectral radius: %e\n', sr);
fprintf('Wrote /app/results/spectral.json\n');
