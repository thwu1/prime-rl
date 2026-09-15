#include "manipulator.h"
#include <cmath>


namespace manipulator {

namespace {
    const double ZERO_THRESH = 1e-8;
    int SIGN(double x) { return (x > 0) - (x < 0); }
    const double PI = M_PI;

    const double d1 = 0.15185;
    const double a2 = -0.37082;
    const double a3 = -0.28956;
    const double d4 = 0.10483;
    const double d5 = 0.08793;
    const double d6 = 0.07506;

    double clamp(double x, double lo, double hi) {
        if (x < lo) return lo;
        if (x > hi) return hi;
        return x;
    }
}

int inverse(const double* T, double* q_sols, double q6_des) {
    int num_sols = 0;

    // ---------------------------------------------------------------
    // Recover T_0_6 from the input T_base_ee.
    //
    //   T_0_6  =  inv(T_base_0) * T_base_ee * inv(T_6_ee)
    //
    // T_base_0  = Rx(pi)   = diag(1,-1,-1,1)  -> self-inverse
    // T_6_ee    = cyclic    -> inv = transpose
    //             [0 0 1 0]      [0 1 0 0]
    //             [1 0 0 0]  ->  [0 0 1 0]
    //             [0 1 0 0]      [1 0 0 0]
    //             [0 0 0 1]      [0 0 0 1]
    double T00 =  T[2],  T01 =  T[0],  T02 =  T[1],  T03 =  T[3];
    double T10 = -T[6],  T11 = -T[4],  T12 = -T[5],  T13 = -T[7];
    double T20 = -T[10], T21 = -T[8],  T22 = -T[9],  T23 = -T[11];
    // ---------------------------------------------------------------

    // ======================== q1  (shoulder) ========================
    double q1[2];
    {
        double A = d6 * T12 - T13;
        double B = d6 * T02 - T03;
        double R = A * A + B * B;

        if (fabs(A) < ZERO_THRESH) {
            double div = clamp(-d4 / B, -1.0, 1.0);
            double arcsin = asin(div);
            if (fabs(arcsin) < ZERO_THRESH) arcsin = 0.0;
            if (arcsin < 0.0)
                q1[0] = arcsin + 2.0 * PI;
            else
                q1[0] = arcsin;
            q1[1] = PI - arcsin;
        } else if (fabs(B) < ZERO_THRESH) {
            double div = clamp(d4 / A, -1.0, 1.0);
            double arccos = acos(div);
            q1[0] = arccos;
            q1[1] = 2.0 * PI - arccos;
        } else if (d4 * d4 > R) {
            return 0;
        } else {
            double arccos = acos(d4 / sqrt(R));
            double arctan = atan2(-B, A);
            double pos = arccos + arctan;
            double neg = -arccos + arctan;
            if (fabs(pos) < ZERO_THRESH) pos = 0.0;
            if (fabs(neg) < ZERO_THRESH) neg = 0.0;
            q1[0] = pos >= 0.0 ? pos : 2.0 * PI + pos;
            q1[1] = neg >= 0.0 ? neg : 2.0 * PI + neg;
        }
    }

    // ======================== q5  (wrist bend) ======================
    double q5[2][2];
    for (int i = 0; i < 2; i++) {
        double numer = T03 * sin(q1[i]) - T13 * cos(q1[i]) - d4;
        double div = clamp(numer / d6, -1.0, 1.0);
        double arccos = acos(div);
        q5[i][0] = arccos;
        q5[i][1] = 2.0 * PI - arccos;
    }

    // ============ q6, q3, q2, q4  (wrist + elbow + shoulder) ========
    for (int i = 0; i < 2; i++) {
        for (int j = 0; j < 2; j++) {
            double c1 = cos(q1[i]), s1 = sin(q1[i]);
            double c5 = cos(q5[i][j]), s5 = sin(q5[i][j]);

            // ---- q6 ----
            double q6;
            if (fabs(s5) < ZERO_THRESH)
                q6 = q6_des;
            else {
                q6 = atan2(SIGN(s5) * -(T01 * s1 - T11 * c1),
                           SIGN(s5) *  (T00 * s1 - T10 * c1));
                if (fabs(q6) < ZERO_THRESH) q6 = 0.0;
                if (q6 < 0.0) q6 += 2.0 * PI;
            }

            double c6 = cos(q6), s6 = sin(q6);

            // ---- auxiliary vectors ----
            double x04x = -s5 * (T02 * c1 + T12 * s1)
                          - c5 * (s6 * (T01 * c1 + T11 * s1)
                                - c6 * (T00 * c1 + T10 * s1));
            double x04y = c5 * (T20 * c6 - T21 * s6) - T22 * s5;

            double p13x = d5 * (s6 * (T00 * c1 + T10 * s1)
                              + c6 * (T01 * c1 + T11 * s1))
                        - d6 * (T02 * c1 + T12 * s1)
                        + T03 * c1 + T13 * s1;
            double p13y = T23 - d1 - d6 * T22
                        + d5 * (T21 * c6 + T20 * s6);

            // ---- q3 (elbow) ----
            double c3 = (p13x * p13x + p13y * p13y
                         - a2 * a2 - a3 * a3) / (2.0 * a2 * a3);

            // Near ±1: snap for numerical robustness
            if (fabs(fabs(c3) - 1.0) < ZERO_THRESH)
                c3 = SIGN(c3);
            else if (fabs(c3) > 1.0) {
                // No valid arm configuration for this q1/q5 branch
                continue;
            }

            double q3[2], q2[2], q4[2];
            double ac3 = acos(c3);
            q3[0] = ac3;
            q3[1] = 2.0 * PI - ac3;

            double denom = a2 * a2 + a3 * a3 + 2.0 * a2 * a3 * c3;
            double s3 = sin(ac3);
            double A = a2 + a3 * c3;
            double B = a3 * s3;

            q2[0] = atan2((A * p13y - B * p13x) / denom,
                          (A * p13x + B * p13y) / denom);
            q2[1] = atan2((A * p13y + B * p13x) / denom,
                          (A * p13x - B * p13y) / denom);

            double c23_0 = cos(q2[0] + q3[0]), s23_0 = sin(q2[0] + q3[0]);
            double c23_1 = cos(q2[1] + q3[1]), s23_1 = sin(q2[1] + q3[1]);

            q4[0] = atan2(c23_0 * x04y - s23_0 * x04x,
                          x04x * c23_0 + x04y * s23_0);
            q4[1] = atan2(c23_1 * x04y - s23_1 * x04x,
                          x04x * c23_1 + x04y * s23_1);

            for (int k = 0; k < 2; k++) {
                if (fabs(q2[k]) < ZERO_THRESH) q2[k] = 0.0;
                else if (q2[k] < 0.0) q2[k] += 2.0 * PI;
                if (fabs(q4[k]) < ZERO_THRESH) q4[k] = 0.0;
                else if (q4[k] < 0.0) q4[k] += 2.0 * PI;

                q_sols[num_sols * 6 + 0] = q1[i];
                q_sols[num_sols * 6 + 1] = q2[k];
                q_sols[num_sols * 6 + 2] = q3[k];
                q_sols[num_sols * 6 + 3] = q4[k];
                q_sols[num_sols * 6 + 4] = q5[i][j];
                q_sols[num_sols * 6 + 5] = q6;
                num_sols++;
            }
        }
    }

    return num_sols;
}

} // namespace manipulator
