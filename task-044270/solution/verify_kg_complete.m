% verify_kg.m - Independent cross-validation of geometric stiffness matrix
%
% Computes the 12x12 local geometric stiffness matrix for 3D Euler-Bernoulli
% beam elements using Octave notation (1-indexed matrices).
%
% Case 1: Pure axial loading (build_kg_axial)
% Case 2: Combined axial + torsion + bending (build_kg_combined)
%
% Run: octave --no-gui --silent /app/octave_ref/verify_kg.m

1;  % Force Octave to treat this as a script, not a function file

function kg = build_kg_axial(L, A, Ip, P)
  % Geometric stiffness for pure axial loading (all moments zero).
  % P = axial force at node j (Fx2), positive = tension.
  % Uses 1-based indexing (Octave convention).

  kg = zeros(12, 12);

  % Upper triangle off-diagonal entries (only Fx2-dependent terms)
  kg(1,7) = -P/L;
  kg(2,6) = P/10;
  kg(2,8) = -6*P/(5*L);
  kg(2,12) = P/10;
  kg(3,5) = -P/10;
  kg(3,9) = -6*P/(5*L);
  kg(3,11) = -P/10;
  kg(4,10) = -P*Ip/(A*L);
  kg(5,9) = P/10;
  kg(5,11) = -P*L/30;
  kg(6,8) = -P/10;
  kg(6,12) = -P*L/30;
  kg(8,12) = -P/10;
  kg(9,11) = P/10;

  % Symmetrize
  kg = kg + kg';

  % Diagonal entries
  kg(1,1) = P/L;
  kg(2,2) = 6*P/(5*L);
  kg(3,3) = 6*P/(5*L);
  kg(4,4) = P*Ip/(A*L);
  kg(5,5) = 2*P*L/15;
  kg(6,6) = 2*P*L/15;
  kg(7,7) = P/L;
  kg(8,8) = 6*P/(5*L);
  kg(9,9) = 6*P/(5*L);
  kg(10,10) = P*Ip/(A*L);
  kg(11,11) = 2*P*L/15;
  kg(12,12) = 2*P*L/15;
endfunction


function kg = build_kg_combined(L, A, Ip, P, T, My1, Mz1, My2, Mz2)
  % Geometric stiffness with full torsion-bending coupling.
  % Uses 1-based indexing (Octave convention).
  %
  % P   = Fx2  (axial force at node j, positive = tension)
  % T   = Mx2  (torsional moment at node j)
  % My1, Mz1 = bending moments at node i about y and z axes
  % My2, Mz2 = bending moments at node j about y and z axes

  kg = zeros(12, 12);

  % Upper triangle off-diagonal entries (all terms)
  % Row 1 (u_x at node i)
  kg(1,7) = -P/L;

  % Row 2 (u_y at node i)
  kg(2,4) = My1/L;
  kg(2,5) = T/L;
  kg(2,6) = P/10;
  kg(2,8) = -6*P/(5*L);
  kg(2,10) = My2/L;
  kg(2,11) = -T/L;
  kg(2,12) = P/10;

  % Row 3 (u_z at node i)
  kg(3,4) = Mz1/L;
  kg(3,5) = -P/10;
  kg(3,6) = T/L;
  kg(3,9) = -6*P/(5*L);
  kg(3,10) = Mz2/L;
  kg(3,11) = -P/10;
  kg(3,12) = -T/L;

  % Row 4 (theta_x at node i)
  kg(4,5) = -(2*Mz1 - Mz2)/6;
  kg(4,6) = (2*My1 - My2)/6;
  kg(4,8) = -My1/L;
  kg(4,9) = -Mz1/L;
  kg(4,10) = -P*Ip/(A*L);
  kg(4,11) = -(Mz1 + Mz2)/6;
  kg(4,12) = (My1 + My2)/6;

  % Row 5 (theta_y at node i)
  kg(5,8) = -T/L;
  kg(5,9) = P/10;
  kg(5,10) = -(Mz1 + Mz2)/6;
  kg(5,11) = -P*L/30;
  kg(5,12) = T/2;

  % Row 6 (theta_z at node i)
  kg(6,8) = -P/10;
  kg(6,9) = -T/L;
  kg(6,10) = (My1 + My2)/6;
  kg(6,11) = -T/2;
  kg(6,12) = -P*L/30;

  % Row 8 (u_y at node j)
  kg(8,10) = -My2/L;
  kg(8,11) = T/L;
  kg(8,12) = -P/10;

  % Row 9 (u_z at node j)
  kg(9,10) = -Mz2/L;
  kg(9,11) = P/10;
  kg(9,12) = T/L;

  % Row 10 (theta_x at node j)
  kg(10,11) = (Mz1 - 2*Mz2)/6;
  kg(10,12) = -(My1 - 2*My2)/6;

  % Symmetrize
  kg = kg + kg';

  % Diagonal entries
  kg(1,1) = P/L;
  kg(2,2) = 6*P/(5*L);
  kg(3,3) = 6*P/(5*L);
  kg(4,4) = P*Ip/(A*L);
  kg(5,5) = 2*P*L/15;
  kg(6,6) = 2*P*L/15;
  kg(7,7) = P/L;
  kg(8,8) = 6*P/(5*L);
  kg(9,9) = 6*P/(5*L);
  kg(10,10) = P*Ip/(A*L);
  kg(11,11) = 2*P*L/15;
  kg(12,12) = 2*P*L/15;
endfunction


% ---- Test parameters ----
L = 2.0;
A = 0.01;
Ip = 5e-6;

% Case 1: Pure axial compression
K1 = build_kg_axial(L, A, Ip, -1000.0);
dlmwrite('/app/octave_ref/kg_case1.csv', K1, 'precision', '%.15e');
printf('Case 1 written (Frobenius norm: %.10e)\n', norm(K1, 'fro'));

% Case 2: Combined loading
K2 = build_kg_combined(L, A, Ip, 500.0, 200.0, 50.0, -75.0, -25.0, 100.0);
dlmwrite('/app/octave_ref/kg_case2.csv', K2, 'precision', '%.15e');
printf('Case 2 written (Frobenius norm: %.10e)\n', norm(K2, 'fro'));

printf('All reference matrices generated.\n');
