% Two-phase Poiseuille flow: cell-centered FVM solver with harmonic averaging
% Extends the single-phase solver to handle a viscosity jump at y = Sw*H.
%
%
% Usage: octave --no-gui two_phase_solver.m <nodes_file> <Sw> <mu_ratio> <G> <H> <output_file>
%
% Solves:  d/dy(mu(y) * du/dy) = -G   on [0, H]
%          u(0) = u(H) = 0
%          mu(y) = mu1 for y <= Sw*H, mu2 = mu1*mu_ratio for y > Sw*H

args = argv();
nodes_file = args{1};
Sw = str2double(args{2});
mu_ratio = str2double(args{3});
G = str2double(args{4});
H = str2double(args{5});
output_file = args{6};

mu1 = 1.0;
mu2 = mu1 * mu_ratio;
h1 = Sw * H;

% ---- Read mesh nodes ----
nodes = load(nodes_file);
nodes = sort(nodes);
N = length(nodes) - 1;

% ---- Cell geometry ----
dy_cells = diff(nodes);
y_centers = nodes(1:end-1) + dy_cells / 2;

% ---- Piecewise viscosity field ----
mu = zeros(N, 1);
for i = 1:N
    if y_centers(i) <= h1
        mu(i) = mu1;
    else
        mu(i) = mu2;
    end
end

% ---- Face viscosities: HARMONIC average ----
% Critical for second-order accuracy at the viscosity discontinuity
mu_face = zeros(N-1, 1);
for i = 1:N-1
    mu_face(i) = 2.0 * mu(i) * mu(i+1) / (mu(i) + mu(i+1));
end

% ---- Distance between adjacent cell centers ----
dy_face = zeros(N-1, 1);
for i = 1:N-1
    dy_face(i) = y_centers(i+1) - y_centers(i);
end

% ---- Assemble sparse linear system ----
A = sparse(N, N);
b = zeros(N, 1);
for i = 1:N
    b(i) = -G * dy_cells(i);
end

% Bottom wall (no-slip via ghost cell)
A(1,1) = -2 * mu(1) / dy_cells(1);
if N > 1
    cf = mu_face(1) / dy_face(1);
    A(1,1) = A(1,1) - cf;
    A(1,2) = cf;
end

% Interior cells
for i = 2:N-1
    cl = mu_face(i-1) / dy_face(i-1);
    cr = mu_face(i) / dy_face(i);
    A(i,i-1) = cl;
    A(i,i) = -(cl + cr);
    A(i,i+1) = cr;
end

% Top wall (no-slip via ghost cell)
if N > 1
    cf = mu_face(N-1) / dy_face(N-1);
    A(N,N-1) = cf;
    A(N,N) = -cf;
end
A(N,N) = A(N,N) - 2 * mu(N) / dy_cells(N);

% ---- Solve ----
u = A \ b;

% ---- Write velocity profile ----
fid = fopen(output_file, 'w');
for i = 1:N
    fprintf(fid, '%.15e %.15e\n', y_centers(i), u(i));
end
fclose(fid);
