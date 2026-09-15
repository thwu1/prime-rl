/* Sequential reference for N-body force computation */

#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

#define NBODIES 500
#define SOFTENING 1e-9

static unsigned int _lcg_state = 12345;
static double lcg_rand_double(void) {
    _lcg_state = _lcg_state * 1103515245u + 12345u;
    return (double)((_lcg_state >> 16) & 0x7fff) / 32767.0;
}

typedef struct {
    double x, y, z;
    double mass;
} Body;

int main(void) {
    Body *bodies = (Body *)malloc(NBODIES * sizeof(Body));
    double *fx = (double *)calloc(NBODIES, sizeof(double));
    double *fy = (double *)calloc(NBODIES, sizeof(double));
    double *fz = (double *)calloc(NBODIES, sizeof(double));

    for (int i = 0; i < NBODIES; i++) {
        bodies[i].x = lcg_rand_double() * 100.0;
        bodies[i].y = lcg_rand_double() * 100.0;
        bodies[i].z = lcg_rand_double() * 100.0;
        bodies[i].mass = lcg_rand_double() * 10.0 + 1.0;
    }

    /* Sequential all-pairs force computation */
    for (int i = 0; i < NBODIES; i++) {
        for (int j = 0; j < NBODIES; j++) {
            if (i == j) continue;
            double dx = bodies[j].x - bodies[i].x;
            double dy = bodies[j].y - bodies[i].y;
            double dz = bodies[j].z - bodies[i].z;
            double dist_sq = dx*dx + dy*dy + dz*dz + SOFTENING;
            double inv_dist = 1.0 / sqrt(dist_sq);
            double inv_dist3 = inv_dist * inv_dist * inv_dist;
            double f = bodies[i].mass * bodies[j].mass * inv_dist3;
            fx[i] += f * dx;
            fy[i] += f * dy;
            fz[i] += f * dz;
        }
    }

    double sum_fx = 0, sum_fy = 0, sum_fz = 0;
    for (int i = 0; i < NBODIES; i++) {
        sum_fx += fx[i];
        sum_fy += fy[i];
        sum_fz += fz[i];
    }

    printf("sum_fx=%.10e\n", sum_fx);
    printf("sum_fy=%.10e\n", sum_fy);
    printf("sum_fz=%.10e\n", sum_fz);
    printf("fx[0]=%.10e\n", fx[0]);
    printf("fy[100]=%.10e\n", fy[100]);
    printf("fz[499]=%.10e\n", fz[NBODIES-1]);

    free(bodies);
    free(fx);
    free(fy);
    free(fz);
    return 0;
}
