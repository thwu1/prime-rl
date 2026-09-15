// 1D Shock Tube Mesh Generator
// Generates a uniform 1D mesh for the compressible Euler equations
//
// Usage: gmsh -1 mesh_template.geo -setnumber N <cells> -o output.msh
//
// Parameters:
//   N : number of desired cells (set via -setnumber on command line)

DefineConstant[ N = {100, Name "Number of cells"} ];

x_left = -5.0;
x_right = 5.0;

// Define endpoints of the shock tube domain
Point(1) = {x_left, 0, 0, 1.0};
Point(2) = {x_right, 0, 0, 1.0};

// Connect endpoints with a line
Line(1) = {1, 2};

// Distribute mesh nodes uniformly along the line
Transfinite Curve {1} = N;

// Force mesh file version 4.1
Mesh.MshFileVersion = 4.1;

Mesh 1;
