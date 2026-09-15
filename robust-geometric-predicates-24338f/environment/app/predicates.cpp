#include "predicates.hpp"
#include "expansion.hpp"

using namespace expansion;

void predicates_init() {
    exactinit();
}

// =====================================================================
// orient2d - COMPLETE REFERENCE IMPLEMENTATION
//
// This demonstrates the full adaptive-precision approach:
//   1. Fast filter (double arithmetic only)
//   2. Adaptive refinement with error bounds (B and C levels)
//   3. Exact computation via expansion arithmetic (D level)
//
// The other three predicates below are stubs that use only the fast
// (non-robust) filter and therefore return WRONG signs for
// near-degenerate inputs. They must be replaced with robust versions.
// =====================================================================

static double orient2dadapt(const double *pa, const double *pb, const double *pc,
                             double detsum) {
    double acx = pa[0] - pc[0];
    double bcx = pb[0] - pc[0];
    double acy = pa[1] - pc[1];
    double bcy = pb[1] - pc[1];

    double detleft, detlefttail, detright, detrighttail;
    Two_Product(acx, bcy, detleft, detlefttail);
    Two_Product(acy, bcx, detright, detrighttail);

    double B[4], B3;
    Two_Two_Diff(detleft, detlefttail, detright, detrighttail,
                 B3, B[2], B[1], B[0]);
    B[3] = B3;

    double det = estimate(4, B);
    double errbound = ccwerrboundB * detsum;
    if ((det >= errbound) || (-det >= errbound)) {
        return det;
    }

    double acxtail, acytail, bcxtail, bcytail;
    Two_Diff_Tail(pa[0], pc[0], acx, acxtail);
    Two_Diff_Tail(pb[0], pc[0], bcx, bcxtail);
    Two_Diff_Tail(pa[1], pc[1], acy, acytail);
    Two_Diff_Tail(pb[1], pc[1], bcy, bcytail);

    if ((acxtail == 0.0) && (acytail == 0.0)
        && (bcxtail == 0.0) && (bcytail == 0.0)) {
        return det;
    }

    errbound = ccwerrboundC * detsum + resulterrbound * Absolute(det);
    det += (acx * bcytail + bcy * acxtail)
         - (acy * bcxtail + bcx * acytail);
    if ((det >= errbound) || (-det >= errbound)) {
        return det;
    }

    double s1, s0, t1, t0;
    double u[4], u3;
    double C1[8], C2[12], D[16];
    int C1length, C2length, Dlength;

    Two_Product(acxtail, bcy, s1, s0);
    Two_Product(acytail, bcx, t1, t0);
    Two_Two_Diff(s1, s0, t1, t0, u3, u[2], u[1], u[0]);
    u[3] = u3;
    C1length = fast_expansion_sum_zeroelim(4, B, 4, u, C1);

    Two_Product(acx, bcytail, s1, s0);
    Two_Product(acy, bcxtail, t1, t0);
    Two_Two_Diff(s1, s0, t1, t0, u3, u[2], u[1], u[0]);
    u[3] = u3;
    C2length = fast_expansion_sum_zeroelim(C1length, C1, 4, u, C2);

    Two_Product(acxtail, bcytail, s1, s0);
    Two_Product(acytail, bcxtail, t1, t0);
    Two_Two_Diff(s1, s0, t1, t0, u3, u[2], u[1], u[0]);
    u[3] = u3;
    Dlength = fast_expansion_sum_zeroelim(C2length, C2, 4, u, D);

    return D[Dlength - 1];
}

double orient2d(const double *pa, const double *pb, const double *pc) {
    double detleft = (pa[0] - pc[0]) * (pb[1] - pc[1]);
    double detright = (pa[1] - pc[1]) * (pb[0] - pc[0]);
    double det = detleft - detright;

    double detsum;
    if (detleft > 0.0) {
        if (detright <= 0.0) {
            return det;
        } else {
            detsum = detleft + detright;
        }
    } else if (detleft < 0.0) {
        if (detright >= 0.0) {
            return det;
        } else {
            detsum = -detleft - detright;
        }
    } else {
        return det;
    }

    double errbound = ccwerrboundA * detsum;
    if ((det >= errbound) || (-det >= errbound)) {
        return det;
    }

    return orient2dadapt(pa, pb, pc, detsum);
}

// =====================================================================
// orient3d - STUB (uses only non-robust fast filter)
// =====================================================================

static double orient3dfast(const double *pa, const double *pb,
                            const double *pc, const double *pd) {
    double adx = pa[0] - pd[0], bdx = pb[0] - pd[0], cdx = pc[0] - pd[0];
    double ady = pa[1] - pd[1], bdy = pb[1] - pd[1], cdy = pc[1] - pd[1];
    double adz = pa[2] - pd[2], bdz = pb[2] - pd[2], cdz = pc[2] - pd[2];

    return adx * (bdy * cdz - bdz * cdy)
         + bdx * (cdy * adz - cdz * ady)
         + cdx * (ady * bdz - adz * bdy);
}

double orient3d(const double *pa, const double *pb,
                const double *pc, const double *pd) {
    // TODO: This fast-only implementation returns wrong signs for
    // near-degenerate inputs. Replace with a robust version.
    return orient3dfast(pa, pb, pc, pd);
}

// =====================================================================
// incircle - STUB (uses only non-robust fast filter)
// =====================================================================

static double incirclefast(const double *pa, const double *pb,
                            const double *pc, const double *pd) {
    double adx = pa[0] - pd[0], ady = pa[1] - pd[1];
    double bdx = pb[0] - pd[0], bdy = pb[1] - pd[1];
    double cdx = pc[0] - pd[0], cdy = pc[1] - pd[1];

    double abdet = adx * bdy - bdx * ady;
    double bcdet = bdx * cdy - cdx * bdy;
    double cadet = cdx * ady - adx * cdy;
    double alift = adx * adx + ady * ady;
    double blift = bdx * bdx + bdy * bdy;
    double clift = cdx * cdx + cdy * cdy;

    return alift * bcdet + blift * cadet + clift * abdet;
}

double incircle(const double *pa, const double *pb,
                const double *pc, const double *pd) {
    // TODO: This fast-only implementation returns wrong signs for
    // near-degenerate inputs. Replace with a robust version.
    return incirclefast(pa, pb, pc, pd);
}

// =====================================================================
// insphere - STUB (uses only non-robust fast filter)
// =====================================================================

static double inspherefast(const double *pa, const double *pb,
                            const double *pc, const double *pd, const double *pe) {
    double aex = pa[0] - pe[0], bex = pb[0] - pe[0];
    double cex = pc[0] - pe[0], dex = pd[0] - pe[0];
    double aey = pa[1] - pe[1], bey = pb[1] - pe[1];
    double cey = pc[1] - pe[1], dey = pd[1] - pe[1];
    double aez = pa[2] - pe[2], bez = pb[2] - pe[2];
    double cez = pc[2] - pe[2], dez = pd[2] - pe[2];

    double ab = aex * bey - bex * aey;
    double bc = bex * cey - cex * bey;
    double cd = cex * dey - dex * cey;
    double da = dex * aey - aex * dey;
    double ac = aex * cey - cex * aey;
    double bd = bex * dey - dex * bey;

    double abc = aez * bc - bez * ac + cez * ab;
    double bcd = bez * cd - cez * bd + dez * bc;
    double cda = cez * da + dez * ac + aez * cd;
    double dab = dez * ab + aez * bd + bez * da;

    double alift = aex * aex + aey * aey + aez * aez;
    double blift = bex * bex + bey * bey + bez * bez;
    double clift = cex * cex + cey * cey + cez * cez;
    double dlift = dex * dex + dey * dey + dez * dez;

    return (dlift * abc - clift * dab) + (blift * cda - alift * bcd);
}

double insphere(const double *pa, const double *pb, const double *pc,
                const double *pd, const double *pe) {
    // TODO: This fast-only implementation returns wrong signs for
    // near-degenerate inputs. Replace with a robust version.
    return inspherefast(pa, pb, pc, pd, pe);
}
