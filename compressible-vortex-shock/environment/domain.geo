// Computational domain for compressible vortex-shock interaction
// Structured quadrilateral mesh on [0,1] x [0,1]
// 200 x 200 elements, uniform spacing

Point(1) = {0, 0, 0};
Point(2) = {1, 0, 0};
Point(3) = {1, 1, 0};
Point(4) = {0, 1, 0};

Line(1) = {1, 2};
Line(2) = {2, 3};
Line(3) = {3, 4};
Line(4) = {4, 1};

Curve Loop(1) = {1, 2, 3, 4};
Plane Surface(1) = {1};

Transfinite Curve{1} = 201;
Transfinite Curve{2} = 201;
Transfinite Curve{3} = 201;
Transfinite Curve{4} = 201;

Transfinite Surface{1};
Recombine Surface{1};

Mesh.MshFileVersion = 2.2;
Mesh.ElementOrder = 1;
