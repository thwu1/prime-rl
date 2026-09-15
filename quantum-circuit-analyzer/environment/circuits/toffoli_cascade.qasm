OPENQASM 2.0;
include "qelib1.inc";
qreg q[4];
h q[0];
x q[1];
ccx q[0],q[1],q[2];
ccx q[0],q[2],q[3];
