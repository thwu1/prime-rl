/*
 * SO(3) rotation operations — column-major matrix convention.
 *
 */

#include "so3_ops.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

void so3_rodrigues(const double *v, double *R) {
    double a2 = v[0]*v[0] + v[1]*v[1] + v[2]*v[2];
    if (a2 < 1e-30) {
        /* Small-angle: R ≈ I + skew(v) */
        R[0] = 1.0;    R[3] = -v[2];  R[6] = v[1];
        R[1] = v[2];   R[4] = 1.0;    R[7] = -v[0];
        R[2] = -v[1];  R[5] = v[0];   R[8] = 1.0;
        return;
    }
    double a  = sqrt(a2);
    double c  = cos(a);
    double s  = sin(a);
    double t  = (1.0 - c) / a2;
    double sa = s / a;

    /* Column-major: R[i + 3*j] = R_{ij} */
    R[0] = c + t*v[0]*v[0];
    R[1] = t*v[0]*v[1] + sa*v[2];
    R[2] = t*v[0]*v[2] - sa*v[1];

    R[3] = t*v[0]*v[1] - sa*v[2];
    R[4] = c + t*v[1]*v[1];
    R[5] = t*v[1]*v[2] + sa*v[0];

    R[6] = t*v[0]*v[2] + sa*v[1];
    R[7] = t*v[1]*v[2] - sa*v[0];
    R[8] = c + t*v[2]*v[2];
}

void so3_log(const double *R, double *v) {
    /* trace = R00 + R11 + R22 = R[0] + R[4] + R[8] */
    double ct = (R[0] + R[4] + R[8] - 1.0) * 0.5;
    if (ct >  1.0) ct =  1.0;
    if (ct < -1.0) ct = -1.0;
    double ang = acos(ct);

    if (ang < 1e-10) {
        /* Near identity: v ≈ vex(R - R^T)/2 */
        v[0] = (R[5] - R[7]) * 0.5;   /* (R21 - R12)/2 */
        v[1] = (R[6] - R[2]) * 0.5;   /* (R02 - R20)/2 */
        v[2] = (R[1] - R[3]) * 0.5;   /* (R10 - R01)/2 */
        return;
    }

    if (ang > M_PI - 1e-6) {
        /* Near pi: extract axis from R + I (rank-1 matrix) */
        double n0 = (R[0]+1.0)*(R[0]+1.0) + R[1]*R[1] + R[2]*R[2];
        double n1 = R[3]*R[3] + (R[4]+1.0)*(R[4]+1.0) + R[5]*R[5];
        double n2 = R[6]*R[6] + R[7]*R[7] + (R[8]+1.0)*(R[8]+1.0);
        double nm;
        if (n0 >= n1 && n0 >= n2) {
            nm = sqrt(n0);
            v[0] = (R[0]+1.0)/nm * ang;
            v[1] = R[1]/nm * ang;
            v[2] = R[2]/nm * ang;
        } else if (n1 >= n2) {
            nm = sqrt(n1);
            v[0] = R[3]/nm * ang;
            v[1] = (R[4]+1.0)/nm * ang;
            v[2] = R[5]/nm * ang;
        } else {
            nm = sqrt(n2);
            v[0] = R[6]/nm * ang;
            v[1] = R[7]/nm * ang;
            v[2] = (R[8]+1.0)/nm * ang;
        }
        return;
    }

    double fac = ang / (2.0 * sin(ang));
    v[0] = (R[5] - R[7]) * fac;
    v[1] = (R[6] - R[2]) * fac;
    v[2] = (R[1] - R[3]) * fac;
}
