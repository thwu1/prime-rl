// Gmsh geometry: 1D channel mesh for Poiseuille flow
// Usage: gmsh -1 mesh.geo -setnumber N 100 -o mesh.msh -format msh2
//
// Generates a uniform 1D mesh on [0, H] with N elements (N+1 nodes).

DefineConstant[ N = {100, Name "Elements"} ];
H = 1.0;

Point(1) = {0, 0, 0};
Point(2) = {H, 0, 0};

Line(1) = {1, 2};

Transfinite Curve{1} = N + 1 Using Progression 1.0;
