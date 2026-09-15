#include "manipulator.h"
#include <cmath>


namespace manipulator {

namespace {
    const double PI = M_PI;

    const double d1 = 0.15185;
    const double a2 = -0.37082;
    const double a3 = -0.28956;
    const double d4 = 0.10483;
    const double d5 = 0.08793;
    const double d6 = 0.07506;

    // 4x4 matrix multiply (row-major), result may alias neither input
    void mat4_mul(const double* A, const double* B, double* C) {
        double tmp[16];
        for (int i = 0; i < 4; i++)
            for (int j = 0; j < 4; j++) {
                tmp[i*4+j] = 0.0;
                for (int k = 0; k < 4; k++)
                    tmp[i*4+j] += A[i*4+k] * B[k*4+j];
            }
        for (int i = 0; i < 16; i++) C[i] = tmp[i];
    }

    // Standard DH transform for one joint
    //   A_i = Rz(theta) * Tz(d) * Tx(a) * Rx(alpha)
    void dh_transform(double theta, double d, double a, double alpha, double* T) {
        double ct = cos(theta), st = sin(theta);
        double ca = cos(alpha), sa = sin(alpha);
        T[0]  = ct;      T[1]  = -st*ca;  T[2]  = st*sa;   T[3]  = a*ct;
        T[4]  = st;      T[5]  = ct*ca;   T[6]  = -ct*sa;  T[7]  = a*st;
        T[8]  = 0.0;     T[9]  = sa;      T[10] = ca;       T[11] = d;
        T[12] = 0.0;     T[13] = 0.0;     T[14] = 0.0;      T[15] = 1.0;
    }
}

void forward(const double* q, double* T) {
    // Individual DH link transforms
    double A1[16], A2[16], A3[16], A4[16], A5[16], A6[16];
    dh_transform(q[0], d1,  0.0, PI/2.0,  A1);
    dh_transform(q[1], 0.0, a2,  0.0,     A2);
    dh_transform(q[2], 0.0, a3,  0.0,     A3);
    dh_transform(q[3], d4,  0.0, PI/2.0,  A4);
    dh_transform(q[4], d5,  0.0, -PI/2.0, A5);
    dh_transform(q[5], d6,  0.0, 0.0,     A6);

    // T_0_6 = A1 * A2 * A3 * A4 * A5 * A6
    double T12[16], T123[16], T1234[16], T12345[16], T06[16];
    mat4_mul(A1, A2, T12);
    mat4_mul(T12, A3, T123);
    mat4_mul(T123, A4, T1234);
    mat4_mul(T1234, A5, T12345);
    mat4_mul(T12345, A6, T06);

    // T_base_ee = T_base_0 * T_0_6 * T_6_ee
    //
    // T_base_0 (180-degree rotation about X-axis):
    //   1   0   0   0
    //   0  -1   0   0
    //   0   0  -1   0
    //   0   0   0   1
    //
    // T_6_ee (cyclic axis permutation  x->y, y->z, z->x):
    //   0   0   1   0
    //   1   0   0   0
    //   0   1   0   0
    //   0   0   0   1

    const double Tbase0[16] = {
         1,  0,  0,  0,
         0, -1,  0,  0,
         0,  0, -1,  0,
         0,  0,  0,  1
    };
    const double T6ee[16] = {
         0,  0,  1,  0,
         1,  0,  0,  0,
         0,  1,  0,  0,
         0,  0,  0,  1
    };

    double temp[16];
    mat4_mul(Tbase0, T06, temp);
    mat4_mul(temp, T6ee, T);
}

} // namespace manipulator
