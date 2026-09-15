OPENQASM 2.0;
include "qelib1.inc";
qreg q[2];
ry(1.5707963267948966) q[0];
cx q[0],q[1];
rz(0.7853981633974483) q[1];
