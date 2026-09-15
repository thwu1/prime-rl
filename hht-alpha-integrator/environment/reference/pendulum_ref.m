% pendulum_ref.m  —  minimal-coordinate ODE reference for a planar double
% pendulum (uniform rigid rods, pin joints, gravity).
%
% Usage:
%   octave-cli --no-gui pendulum_ref.m theta1 theta2 omega1 omega2 t_end output.csv
%
% Physical parameters are hardcoded to match the C++ model defaults:
%   L1 = L2 = 1, m1 = m2 = 1, g = 9.81

args = argv();
if length(args) ~= 6
  error('Need 6 args: theta1 theta2 omega1 omega2 t_end output_file');
end

theta1_0  = str2double(args{1});
theta2_0  = str2double(args{2});
omega1_0  = str2double(args{3});
omega2_0  = str2double(args{4});
t_end_val = str2double(args{5});
out_file  = args{6};

L1 = 1.0;  L2 = 1.0;
m1 = 1.0;  m2 = 1.0;
g_val = 9.81;

y0 = [theta1_0; theta2_0; omega1_0; omega2_0];

opts = odeset('RelTol', 1e-12, 'AbsTol', 1e-14);
[t_out, y_out] = ode45( ...
    @(t, y) pend_rhs(t, y, L1, L2, m1, m2, g_val), ...
    [0, t_end_val], y0, opts);

fid = fopen(out_file, 'w');
fprintf(fid, 'time,theta1,theta2,omega1,omega2\n');
for i = 1:length(t_out)
  fprintf(fid, '%.15e,%.15e,%.15e,%.15e,%.15e\n', ...
          t_out(i), y_out(i,1), y_out(i,2), y_out(i,3), y_out(i,4));
end
fclose(fid);

% -----------------------------------------------------------------------
function ydot = pend_rhs(~, y, L1, L2, m1, m2, g)
  theta1 = y(1);  theta2 = y(2);
  omega1 = y(3);  omega2 = y(4);

  c = cos(theta1 - theta2);
  s = sin(theta1 - theta2);

  A11 = (m1 / 3.0 + m2) * L1^2;
  A12 = 0.5 * m2 * L1 * L2 * c;
  A22 = m2 * L2^2 / 3.0;

  b1 = -0.5 * m2 * L1 * L2 * s * omega2^2 ...
       - g * cos(theta1) * (m1 * L1 / 2.0 + m2 * L1);
  b2 =  0.5 * m2 * L1 * L2 * s * omega1^2 ...
       - m2 * g * (L2 / 2.0) * cos(theta2);

  d = A11 * A22 - A12^2;
  alpha1 = (A22 * b1 - A12 * b2) / d;
  alpha2 = (A11 * b2 - A12 * b1) / d;

  ydot = [omega1; omega2; alpha1; alpha2];
endfunction
