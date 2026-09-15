% Equational laws for magmas (sets with a single binary operation)
% Binary operation denoted by f(x,y)
% Variables: x, y, z, w
% Format: ID: LHS = RHS.

1: f(x,y) = x.
2: f(x,y) = y.
3: f(x,x) = x.
4: f(x,y) = f(y,x).
5: f(f(x,y),z) = f(x,f(y,z)).
6: f(x,f(x,y)) = f(x,y).
7: f(f(x,y),y) = f(x,y).
8: f(f(x,x),y) = f(x,f(x,y)).
9: f(x,f(y,y)) = f(f(x,y),y).
10: f(f(x,y),x) = f(x,f(y,x)).
11: f(x,f(y,z)) = f(f(x,y),f(x,z)).
12: f(f(x,y),f(z,w)) = f(f(x,z),f(y,w)).
