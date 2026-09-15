% Single-phase Poiseuille flow: cell-centered finite volume solver
% Reads mesh node coordinates, assembles sparse system, solves via backslash.
%
% Usage: octave --no-gui solver.m <nodes_file> <mu> <G> <output_file>
%
% Input:  nodes_file  -- one y-coordinate per line (N+1 node positions)
%         mu          -- dynamic viscosity (scalar, uniform)
%         G           -- pressure gradient magnitude
%         output_file -- write "y_center  u" per line
%
% Solves:  d/dy(mu * du/dy) = -G   on [0, H]
%          u(0) = u(H) = 0  (no-slip walls)

args = argv();
nodes_file = args{1};
mu_val = str2double(args{2});
G = str2double(args{3});
output_file = args{4};

% ---- Read mesh nodes ----
nodes = load(nodes_file);
nodes = sort(nodes);
N = length(nodes) - 1;

% ---- Cell geometry ----
dy_cells = diff(nodes);                       % cell widths
y_centers = nodes(1:end-1) + dy_cells / 2;    % cell center positions

% ---- Viscosity field (uniform for single phase) ----
mu = ones(N, 1) * mu_val;

% ---- Face viscosities: arithmetic average of adjacent cells ----
mu_face = zeros(N-1, 1);
for i = 1:N-1
    mu_face(i) = (mu(i) + mu(i+1)) / 2.0;
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

% Bottom wall (no-slip via ghost cell: u_ghost = -u_1)
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

% Top wall (no-slip via ghost cell: u_ghost = -u_N)
if N > 1
    cf = mu_face(N-1) / dy_face(N-1);
    A(N,N-1) = cf;
    A(N,N) = -cf;
end
A(N,N) = A(N,N) - 2 * mu(N) / dy_cells(N);

% ---- Solve ----
u = A \ b;

% ---- Write output ----
fid = fopen(output_file, 'w');
for i = 1:N
    fprintf(fid, '%.15e %.15e\n', y_centers(i), u(i));
end
fclose(fid);

printf('Solved %d cells. Output: %s\n', N, output_file);
