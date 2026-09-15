/*
 * rotcore.c — C99 rotation mathematics library for biomechanical analysis
 *
 *
 * Compile: gcc -O2 -shared -fPIC -o librotcore.so rotcore.c -lm
 */

#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* --- Utility --- */

static int axis_idx(char c) {
    if (c == 'X') return 0;
    if (c == 'Y') return 1;
    if (c == 'Z') return 2;
    return -1;
}

static double clamp_d(double x, double lo, double hi) {
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

/* Permutation sign: +1 for even permutations of (0,1,2), -1 for odd */
static int perm_sign(int i, int j, int k) {
    int d = (j - i) * (k - j) * (k - i);
    return (d > 0) ? 1 : -1;
}

/* --- Elementary rotation matrix (row-major 3x3) --- */

static void elem_rot(int axis, double angle, double M[9]) {
    double c = cos(angle), s = sin(angle);
    int a1 = (axis + 1) % 3;
    int a2 = (axis + 2) % 3;
    memset(M, 0, 9 * sizeof(double));
    M[axis * 3 + axis] = 1.0;
    M[a1 * 3 + a1] = c;
    M[a2 * 3 + a2] = c;
    M[a1 * 3 + a2] = -s;
    M[a2 * 3 + a1] = s;
}

/* --- 3x3 matrix multiplication: C = A * B --- */

static void mat3_mul(const double A[9], const double B[9], double C[9]) {
    double tmp[9];
    int i, j, k;
    for (i = 0; i < 3; i++)
        for (j = 0; j < 3; j++) {
            tmp[i * 3 + j] = 0.0;
            for (k = 0; k < 3; k++)
                tmp[i * 3 + j] += A[i * 3 + k] * B[k * 3 + j];
        }
    memcpy(C, tmp, 9 * sizeof(double));
}

/* ================================================================
 * rotcore_compose
 * ================================================================ */

void rotcore_compose(const double angles[3], const char* seq, double R_out[9]) {
    double R1[9], R2[9], R3[9], T[9];
    elem_rot(axis_idx(seq[0]), angles[0], R1);
    elem_rot(axis_idx(seq[1]), angles[1], R2);
    elem_rot(axis_idx(seq[2]), angles[2], R3);
    mat3_mul(R1, R2, T);
    mat3_mul(T, R3, R_out);
}

/* ================================================================
 * rotcore_decompose
 *
 * Returns 0 normally, 1 if gimbal-locked.
 * Cardan: second angle in (-pi/2, pi/2)
 * Proper Euler: second angle in (0, pi)
 * ================================================================ */

int rotcore_decompose(const double R[9], const char* seq, double angles[3]) {
    int ax0 = axis_idx(seq[0]);
    int ax1 = axis_idx(seq[1]);
    int ax2 = axis_idx(seq[2]);
    int is_proper = (ax0 == ax2);

    if (!is_proper) {
        /* ---- Cardan sequence (all axes different) ---- */
        int i = ax0, j = ax1, k = ax2;
        int p = perm_sign(i, j, k);

        /* R[i][k] = p * sin(b) */
        double sb = clamp_d(p * R[i * 3 + k], -1.0, 1.0);
        double b = asin(sb);
        double cb = cos(b);
        int gimbal = (fabs(cb) < 1e-10) ? 1 : 0;

        if (!gimbal) {
            angles[0] = atan2(-p * R[j * 3 + k], R[k * 3 + k]);
            angles[2] = atan2(-p * R[i * 3 + j], R[i * 3 + i]);
        } else {
            /* At gimbal lock, set gamma = 0 */
            angles[2] = 0.0;
            double s = (sb >= 0.0) ? 1.0 : -1.0;
            angles[0] = atan2(s * R[j * 3 + i], R[j * 3 + j]);
        }
        angles[1] = b;
        return gimbal;
    } else {
        /* ---- Proper Euler sequence (i, j, i) ---- */
        int i = ax0, j = ax1;
        int k = 3 - i - j;  /* the remaining axis */
        int p = perm_sign(i, j, k);

        /* R[i][i] = cos(b) */
        double cv = clamp_d(R[i * 3 + i], -1.0, 1.0);
        double b = acos(cv);
        double sb = sin(b);
        int gimbal = (fabs(sb) < 1e-10) ? 1 : 0;

        if (!gimbal) {
            /* alpha = atan2(R[j][i], -p * R[k][i]) */
            angles[0] = atan2(R[j * 3 + i], -p * R[k * 3 + i]);
            /* gamma = atan2(R[i][j], p * R[i][k]) */
            angles[2] = atan2(R[i * 3 + j], p * R[i * 3 + k]);
        } else {
            /* Gimbal lock: sin(b) ~ 0 */
            angles[2] = 0.0;
            int a1 = (i + 1) % 3;
            int a2 = (i + 2) % 3;
            if (b < M_PI / 2.0) {
                /* b ~ 0: R ~ Ri(a+g) */
                angles[0] = atan2(R[a2 * 3 + a1], R[a1 * 3 + a1]);
            } else {
                /* b ~ pi: sign depends on permutation parity */
                double sgn = (p > 0) ? 1.0 : -1.0;
                angles[0] = atan2(sgn * R[a2 * 3 + a1], sgn * R[a1 * 3 + a1]);
            }
        }
        angles[1] = b;
        return gimbal;
    }
}

/* ================================================================
 * rotcore_mat_to_quat (Shepperd's method)
 *
 * Output: q = [w, x, y, z], unit norm, w >= 0
 * Numerically stable for all rotations including near 180 degrees.
 * ================================================================ */

void rotcore_mat_to_quat(const double R[9], double q[4]) {
    /*
     * Row-major indexing:
     * R[0]=R00  R[1]=R01  R[2]=R02
     * R[3]=R10  R[4]=R11  R[5]=R12
     * R[6]=R20  R[7]=R21  R[8]=R22
     */
    double tr = R[0] + R[4] + R[8];
    double w, x, y, z, s;

    if (tr > 0.0) {
        s = 2.0 * sqrt(1.0 + tr);
        w = s / 4.0;
        x = (R[7] - R[5]) / s;
        y = (R[2] - R[6]) / s;
        z = (R[3] - R[1]) / s;
    } else if (R[0] > R[4] && R[0] > R[8]) {
        s = 2.0 * sqrt(1.0 + R[0] - R[4] - R[8]);
        w = (R[7] - R[5]) / s;
        x = s / 4.0;
        y = (R[1] + R[3]) / s;
        z = (R[2] + R[6]) / s;
    } else if (R[4] > R[8]) {
        s = 2.0 * sqrt(1.0 + R[4] - R[0] - R[8]);
        w = (R[2] - R[6]) / s;
        x = (R[1] + R[3]) / s;
        y = s / 4.0;
        z = (R[5] + R[7]) / s;
    } else {
        s = 2.0 * sqrt(1.0 + R[8] - R[0] - R[4]);
        w = (R[3] - R[1]) / s;
        x = (R[2] + R[6]) / s;
        y = (R[5] + R[7]) / s;
        z = s / 4.0;
    }

    /* Normalize */
    double n = sqrt(w * w + x * x + y * y + z * z);
    if (n > 1e-15) {
        w /= n; x /= n; y /= n; z /= n;
    }

    /* Ensure w >= 0 (canonical form) */
    if (w < 0.0) {
        w = -w; x = -x; y = -y; z = -z;
    }

    q[0] = w;
    q[1] = x;
    q[2] = y;
    q[3] = z;
}
