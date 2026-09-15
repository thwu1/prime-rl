OPENQASM 2.0;
include "qelib1.inc";

qreg q[5];

// Initial Neel state |01010>
x q[1];
x q[3];

// Trotterized anisotropic Heisenberg spin chain simulation
// H = sum_ij (Jx*X_i X_j + Jy*Y_i Y_j + Jz*Z_i Z_j) + B*sum_i Z_i

// ZZ nearest-neighbor interactions via CNOT-Rz-CNOT
cx q[0], q[1];
rz(0.42) q[1];
cx q[0], q[1];

cx q[1], q[2];
rz(0.42) q[2];
cx q[1], q[2];

cx q[2], q[3];
rz(0.42) q[3];
cx q[2], q[3];

cx q[3], q[4];
rz(0.42) q[4];
cx q[3], q[4];

// XX next-nearest-neighbor interaction q0-q2
h q[0];
h q[2];
cx q[0], q[2];
rz(0.28) q[2];
cx q[0], q[2];
h q[0];
h q[2];

// XX long-range interaction q1-q4
h q[1];
h q[4];
cx q[1], q[4];
rz(0.28) q[4];
cx q[1], q[4];
h q[1];
h q[4];

// YY long-range interaction q0-q3 via Sdg-H-CNOT-Rz-CNOT-H-S
sdg q[0];
sdg q[3];
h q[0];
h q[3];
cx q[0], q[3];
rz(0.21) q[3];
cx q[0], q[3];
h q[0];
h q[3];
s q[0];
s q[3];

// External magnetic field terms
rz(0.35) q[0];
rz(0.35) q[1];
rz(0.35) q[2];
rz(0.35) q[3];
rz(0.35) q[4];
