// CI2 computational domain [0,1]x[0,1]
// Structured quadrilateral mesh
lc = 0.02;
Point(1) = {0, 0, 0, lc};
Point(2) = {1, 0, 0, lc};
Point(3) = {1, 1, 0, lc};
Point(4) = {0, 1, 0, lc};
Line(1) = {1, 2};
Line(2) = {2, 3};
Line(3) = {3, 4};
Line(4) = {4, 1};
Curve Loop(1) = {1, 2, 3, 4};
Plane Surface(1) = {1};
Transfinite Curve {1, 3} = 51 Using Progression 1;
Transfinite Curve {2, 4} = 51 Using Progression 1;
Transfinite Surface {1};
Recombine Surface {1};
Physical Surface("domain") = {1};
Physical Curve("boundary") = {1, 2, 3, 4};
