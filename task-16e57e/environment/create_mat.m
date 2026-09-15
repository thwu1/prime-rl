% Create supplementary coefficient set in MATLAB format
tuned_v2 = [2.0, -1.5, 0.5; 1.95, -1.4, 0.45; 1.92, -1.34, 0.42; 1.9, -1.3, 0.4; 1.85, -1.2, 0.35];
save('-v7', '/app/extra_coefficients.mat', 'tuned_v2');
