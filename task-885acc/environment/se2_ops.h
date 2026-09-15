#ifndef SE2_OPS_H
#define SE2_OPS_H

/* Normalize angle to [-pi, pi) */
double se2_normalize_angle(double a);

/* Compose two SE(2) poses: result = a (+) b */
void se2_compose(double ax, double ay, double at,
                 double bx, double by, double bt,
                 double *rx, double *ry, double *rt);

/* Invert an SE(2) pose: result = a^{-1} */
void se2_inverse(double ax, double ay, double at,
                 double *rx, double *ry, double *rt);

/* Compute edge error: e = t2v(Z^{-1} (+) Xi^{-1} (+) Xj)
 * xi/xj: node poses, z: edge measurement, e: output error (3-vector) */
void se2_edge_error(double xi_x, double xi_y, double xi_t,
                    double xj_x, double xj_y, double xj_t,
                    double z_dx, double z_dy, double z_dt,
                    double *ex, double *ey, double *et);

#endif
