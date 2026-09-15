#include <math.h>
#include <string.h>
#include <stddef.h>
#include "elastic_core.h"

/* Row-major 12x12 indexing helper */
#define IDX(i, j) ((i) * 12 + (j))


void local_elastic_stiffness_3D_c(
    double E, double nu, double A, double L,
    double Iy, double Iz, double J,
    double *k)
{
    memset(k, 0, 144 * sizeof(double));

    double EA_L = E * A / L;
    double GJ_L = E * J / (2.0 * (1.0 + nu) * L);
    double EIz  = E * Iz;
    double EIy  = E * Iy;
    double L2   = L * L;
    double L3   = L2 * L;

    /* Axial (local x) */
    k[IDX(0, 0)] = k[IDX(6, 6)] = EA_L;
    k[IDX(0, 6)] = k[IDX(6, 0)] = -EA_L;

    /* Torsion (about local x) */
    k[IDX(3, 3)] = k[IDX(9, 9)] = GJ_L;
    k[IDX(3, 9)] = k[IDX(9, 3)] = -GJ_L;

    /* Bending about z-axis (v-displacement, thz-rotation) */
    k[IDX(1, 1)]  = k[IDX(7, 7)]   = 12.0 * EIz / L3;
    k[IDX(1, 7)]  = k[IDX(7, 1)]   = -12.0 * EIz / L3;
    k[IDX(1, 5)]  = k[IDX(5, 1)]   = 6.0 * EIz / L2;
    k[IDX(1, 11)] = k[IDX(11, 1)]  = 6.0 * EIz / L2;
    k[IDX(5, 7)]  = k[IDX(7, 5)]   = -6.0 * EIz / L2;
    k[IDX(7, 11)] = k[IDX(11, 7)]  = -6.0 * EIz / L2;
    k[IDX(5, 5)]  = k[IDX(11, 11)] = 4.0 * EIz / L;
    k[IDX(5, 11)] = k[IDX(11, 5)]  = 2.0 * EIz / L;

    /* Bending about y-axis (w-displacement, thy-rotation) */
    k[IDX(2, 2)]  = k[IDX(8, 8)]   = 12.0 * EIy / L3;
    k[IDX(2, 8)]  = k[IDX(8, 2)]   = -12.0 * EIy / L3;
    k[IDX(2, 4)]  = k[IDX(4, 2)]   = -6.0 * EIy / L2;
    k[IDX(2, 10)] = k[IDX(10, 2)]  = -6.0 * EIy / L2;
    k[IDX(4, 8)]  = k[IDX(8, 4)]   = 6.0 * EIy / L2;
    k[IDX(8, 10)] = k[IDX(10, 8)]  = 6.0 * EIy / L2;
    k[IDX(4, 4)]  = k[IDX(10, 10)] = 4.0 * EIy / L;
    k[IDX(4, 10)] = k[IDX(10, 4)]  = 2.0 * EIy / L;
}


void transformation_matrix_3D_c(
    double x1, double y1, double z1,
    double x2, double y2, double z2,
    const double *ref_vec,
    double *Gamma)
{
    memset(Gamma, 0, 144 * sizeof(double));

    double dx = x2 - x1, dy = y2 - y1, dz = z2 - z1;
    double L = sqrt(dx * dx + dy * dy + dz * dz);

    double ex[3] = { dx / L, dy / L, dz / L };

    double rv[3];
    if (ref_vec == NULL) {
        if (fabs(ex[0]) > 1e-10 || fabs(ex[1]) > 1e-10) {
            rv[0] = 0.0;  rv[1] = 0.0;  rv[2] = 1.0;
        } else {
            rv[0] = 0.0;  rv[1] = 1.0;  rv[2] = 0.0;
        }
    } else {
        rv[0] = ref_vec[0];  rv[1] = ref_vec[1];  rv[2] = ref_vec[2];
    }

    /* ey = cross(rv, ex), normalised */
    double ey[3];
    ey[0] = rv[1] * ex[2] - rv[2] * ex[1];
    ey[1] = rv[2] * ex[0] - rv[0] * ex[2];
    ey[2] = rv[0] * ex[1] - rv[1] * ex[0];
    double ey_norm = sqrt(ey[0] * ey[0] + ey[1] * ey[1] + ey[2] * ey[2]);
    ey[0] /= ey_norm;  ey[1] /= ey_norm;  ey[2] /= ey_norm;

    /* ez = cross(ex, ey) */
    double ez[3];
    ez[0] = ex[1] * ey[2] - ex[2] * ey[1];
    ez[1] = ex[2] * ey[0] - ex[0] * ey[2];
    ez[2] = ex[0] * ey[1] - ex[1] * ey[0];

    /* gamma = [ex; ey; ez]  (3x3, row-major) */
    double gamma[9] = {
        ex[0], ex[1], ex[2],
        ey[0], ey[1], ey[2],
        ez[0], ez[1], ez[2]
    };

    /* Gamma = kron(I_4, gamma)  — block-diagonal 12x12 */
    int b, i, j;
    for (b = 0; b < 4; b++) {
        for (i = 0; i < 3; i++) {
            for (j = 0; j < 3; j++) {
                Gamma[IDX(3 * b + i, 3 * b + j)] = gamma[3 * i + j];
            }
        }
    }
}

#undef IDX
