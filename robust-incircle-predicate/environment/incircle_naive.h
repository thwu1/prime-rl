//
// Naive 2D incircle predicate — standard double-precision arithmetic only.
// Computes the sign of the incircle determinant directly in doubles.
// This implementation produces incorrect results on near-degenerate inputs
// where catastrophic cancellation corrupts the computed sign.

#ifndef ROBUST_INCIRCLE_H
#define ROBUST_INCIRCLE_H

#include <cmath>

namespace robust {

inline int incircle(double ax, double ay, double bx, double by,
                    double cx, double cy, double dx, double dy) {
    double adx = ax - dx, ady = ay - dy;
    double bdx = bx - dx, bdy = by - dy;
    double cdx = cx - dx, cdy = cy - dy;

    double alift = adx * adx + ady * ady;
    double blift = bdx * bdx + bdy * bdy;
    double clift = cdx * cdx + cdy * cdy;

    double det = alift * (bdx * cdy - cdx * bdy)
               + blift * (cdx * ady - adx * cdy)
               + clift * (adx * bdy - bdx * ady);

    if (det > 0.0) return 1;
    if (det < 0.0) return -1;
    return 0;
}

inline int incircle(const double* a, const double* b,
                    const double* c, const double* d) {
    return incircle(a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]);
}

} // namespace robust

#endif // ROBUST_INCIRCLE_H
