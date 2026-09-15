#include <math.h>
#include "se2_ops.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

double se2_normalize_angle(double a) {
    while (a > M_PI) a -= 2.0 * M_PI;
    while (a <= -M_PI) a += 2.0 * M_PI;
    return a;
}

void se2_compose(double ax, double ay, double at,
                 double bx, double by, double bt,
                 double *rx, double *ry, double *rt) {
    double ca = cos(at), sa = sin(at);
    *rx = ax + ca * bx - sa * by;
    *ry = ay + sa * bx + ca * by;
    *rt = se2_normalize_angle(at + bt);
}

void se2_inverse(double ax, double ay, double at,
                 double *rx, double *ry, double *rt) {
    double ca = cos(at), sa = sin(at);
    *rx = -(ca * ax + sa * ay);
    *ry = -(-sa * ax + ca * ay);
    *rt = se2_normalize_angle(-at);
}

void se2_edge_error(double xi_x, double xi_y, double xi_t,
                    double xj_x, double xj_y, double xj_t,
                    double z_dx, double z_dy, double z_dt,
                    double *ex, double *ey, double *et) {
    /* Xi^{-1} */
    double inv_x, inv_y, inv_t;
    se2_inverse(xi_x, xi_y, xi_t, &inv_x, &inv_y, &inv_t);

    /* Xi^{-1} (+) Xj */
    double comp_x, comp_y, comp_t;
    se2_compose(inv_x, inv_y, inv_t, xj_x, xj_y, xj_t,
                &comp_x, &comp_y, &comp_t);

    /* Z^{-1} */
    double zinv_x, zinv_y, zinv_t;
    se2_inverse(z_dx, z_dy, z_dt, &zinv_x, &zinv_y, &zinv_t);

    /* e = t2v(Z^{-1} (+) Xi^{-1} (+) Xj) */
    se2_compose(zinv_x, zinv_y, zinv_t, comp_x, comp_y, comp_t,
                ex, ey, et);
    *et = se2_normalize_angle(*et);
}
