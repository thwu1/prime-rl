 */
#include <math.h>

/* Cartwright epoch: 2000-01-01T12:00:00 MJD, adjusted for UT-to-TDT offset.
 * The correct default is 51544.4993.
 * May be overridden via compiler -D flag.
 */
#ifndef CARTWRIGHT_EPOCH
#define CARTWRIGHT_EPOCH 51544.4993
#endif

/* Rate coefficient for ascending lunar node (degrees/day).
 * Physically the node regresses, so the correct value is negative.
 * May be overridden via compiler -D flag.
 */
#ifndef NODE_RATE
#define NODE_RATE (-0.05295377)
#endif

static double normalize_angle(double angle)
{
    /* Normalize angle to [0, 360) degrees */
    return fmod(angle, 360.0);
}

void compute_mean_longitudes(const double *mjd, int count,
                             double *s, double *h, double *p,
                             double *node, double *pp)
{
    int i;
    for (i = 0; i < count; i++) {
        double T = mjd[i] - CARTWRIGHT_EPOCH;
        s[i]    = normalize_angle(218.3164  + 13.17639648 * T);
        h[i]    = normalize_angle(280.4661  +  0.98564736 * T);
        p[i]    = normalize_angle( 83.3535  +  0.11140353 * T);
        node[i] = normalize_angle(125.0445  + NODE_RATE   * T);
        pp[i]   = normalize_angle(282.8);
    }
}
