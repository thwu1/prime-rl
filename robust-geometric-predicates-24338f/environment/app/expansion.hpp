#ifndef EXPANSION_HPP
#define EXPANSION_HPP

// Adaptive-precision expansion arithmetic for robust geometric predicates.
//
// An "expansion" is an array of doubles sorted by increasing magnitude
// (smallest first) with non-overlapping significands. The exact value
// of the represented number equals the sum of all components.
// Functions that produce expansions return the length of the result.
//
// Compile with: g++ -O2 -ffp-contract=off
// The -ffp-contract=off flag is critical to prevent fused multiply-add
// which would break the error analysis.

#include <cmath>

namespace expansion {

// Global constants set by exactinit().
inline double splitter;
inline double epsilon;
inline double resulterrbound;
inline double ccwerrboundA, ccwerrboundB, ccwerrboundC;
inline double o3derrboundA, o3derrboundB, o3derrboundC;
inline double iccerrboundA, iccerrboundB, iccerrboundC;
inline double isperrboundA, isperrboundB, isperrboundC;

// Must be called once before any predicate or expansion operation.
// Determines machine epsilon and the Veltkamp splitter, then derives
// the error bound constants for each geometric predicate.
inline void exactinit() {
    double half = 0.5;
    double check, lastcheck;
    int every_other = 1;

    epsilon = 1.0;
    splitter = 1.0;
    check = 1.0;
    do {
        lastcheck = check;
        epsilon *= half;
        if (every_other) {
            splitter *= 2.0;
        }
        every_other = !every_other;
        check = 1.0 + epsilon;
    } while ((check != 1.0) && (check != lastcheck));
    splitter += 1.0;

    resulterrbound = (3.0 + 8.0 * epsilon) * epsilon;
    ccwerrboundA = (3.0 + 16.0 * epsilon) * epsilon;
    ccwerrboundB = (2.0 + 12.0 * epsilon) * epsilon;
    ccwerrboundC = (9.0 + 64.0 * epsilon) * epsilon * epsilon;
    o3derrboundA = (7.0 + 56.0 * epsilon) * epsilon;
    o3derrboundB = (3.0 + 28.0 * epsilon) * epsilon;
    o3derrboundC = (26.0 + 288.0 * epsilon) * epsilon * epsilon;
    iccerrboundA = (10.0 + 96.0 * epsilon) * epsilon;
    iccerrboundB = (4.0 + 48.0 * epsilon) * epsilon;
    iccerrboundC = (44.0 + 576.0 * epsilon) * epsilon * epsilon;
    isperrboundA = (16.0 + 224.0 * epsilon) * epsilon;
    isperrboundB = (5.0 + 72.0 * epsilon) * epsilon;
    isperrboundC = (71.0 + 1408.0 * epsilon) * epsilon * epsilon;
}

inline double Absolute(double a) { return a >= 0.0 ? a : -a; }

// =====================================================================
// Exact arithmetic primitives
// =====================================================================

// Fast_Two_Sum: computes x + y = a + b exactly.
// PRECONDITION: |a| >= |b|.
inline void Fast_Two_Sum(double a, double b, double &x, double &y) {
    x = a + b;
    double bvirt = x - a;
    y = b - bvirt;
}

inline void Fast_Two_Diff(double a, double b, double &x, double &y) {
    x = a - b;
    double bvirt = a - x;
    y = bvirt - b;
}

// Two_Sum: computes x + y = a + b exactly. No precondition on magnitudes.
inline void Two_Sum(double a, double b, double &x, double &y) {
    x = a + b;
    double bvirt = x - a;
    double avirt = x - bvirt;
    double bround = b - bvirt;
    double around = a - avirt;
    y = around + bround;
}

// Two_Diff: computes x + y = a - b exactly.
inline void Two_Diff(double a, double b, double &x, double &y) {
    x = a - b;
    double bvirt = a - x;
    double avirt = x + bvirt;
    double bround = bvirt - b;
    double around = a - avirt;
    y = around + bround;
}

// Two_Diff_Tail: given x = fl(a - b), computes y such that a - b = x + y exactly.
inline void Two_Diff_Tail(double a, double b, double x, double &y) {
    double bvirt = a - x;
    double avirt = x + bvirt;
    double bround = bvirt - b;
    double around = a - avirt;
    y = around + bround;
}

// Split: splits a into ahi + alo where ahi has the leading bits.
// Uses the Veltkamp splitting technique.
inline void Split(double a, double &ahi, double &alo) {
    double c = splitter * a;
    double abig = c - a;
    ahi = c - abig;
    alo = a - ahi;
}

// Two_Product: computes x + y = a * b exactly.
inline void Two_Product(double a, double b, double &x, double &y) {
    x = a * b;
    double ahi, alo, bhi, blo;
    Split(a, ahi, alo);
    Split(b, bhi, blo);
    double err1 = x - (ahi * bhi);
    double err2 = err1 - (alo * bhi);
    double err3 = err2 - (ahi * blo);
    y = (alo * blo) - err3;
}

// Two_Product_Presplit: Two_Product where b has already been split.
inline void Two_Product_Presplit(double a, double b, double bhi, double blo,
                                  double &x, double &y) {
    x = a * b;
    double ahi, alo;
    Split(a, ahi, alo);
    double err1 = x - (ahi * bhi);
    double err2 = err1 - (alo * bhi);
    double err3 = err2 - (ahi * blo);
    y = (alo * blo) - err3;
}

// Square: computes x + y = a * a exactly (faster than Two_Product for squaring).
inline void Square(double a, double &x, double &y) {
    x = a * a;
    double ahi, alo;
    Split(a, ahi, alo);
    double err1 = x - (ahi * ahi);
    double err3 = err1 - ((ahi + ahi) * alo);
    y = (alo * alo) - err3;
}

// =====================================================================
// Fixed-length compound operations
// =====================================================================

inline void Two_One_Sum(double a1, double a0, double b,
                         double &x2, double &x1, double &x0) {
    double _i;
    Two_Sum(a0, b, _i, x0);
    Two_Sum(a1, _i, x2, x1);
}

inline void Two_One_Diff(double a1, double a0, double b,
                          double &x2, double &x1, double &x0) {
    double _i;
    Two_Diff(a0, b, _i, x0);
    Two_Sum(a1, _i, x2, x1);
}

inline void Two_Two_Sum(double a1, double a0, double b1, double b0,
                          double &x3, double &x2, double &x1, double &x0) {
    double _j, _0;
    Two_One_Sum(a1, a0, b0, _j, _0, x0);
    Two_One_Sum(_j, _0, b1, x3, x2, x1);
}

inline void Two_Two_Diff(double a1, double a0, double b1, double b0,
                           double &x3, double &x2, double &x1, double &x0) {
    double _j, _0;
    Two_One_Diff(a1, a0, b0, _j, _0, x0);
    Two_One_Diff(_j, _0, b1, x3, x2, x1);
}

// =====================================================================
// Variable-length expansion operations
// =====================================================================

// fast_expansion_sum_zeroelim: sum two expansions, eliminate zeros.
// h must NOT alias e or f. Returns length of h.
inline int fast_expansion_sum_zeroelim(int elen, const double *e,
                                        int flen, const double *f, double *h) {
    double Q, Qnew, hh;
    int eindex, findex, hindex;
    double enow, fnow;

    enow = e[0];
    fnow = f[0];
    eindex = findex = 0;
    if ((fnow > enow) == (fnow > -enow)) {
        Q = enow;
        enow = e[++eindex];
    } else {
        Q = fnow;
        fnow = f[++findex];
    }
    hindex = 0;
    if ((eindex < elen) && (findex < flen)) {
        if ((fnow > enow) == (fnow > -enow)) {
            Fast_Two_Sum(enow, Q, Qnew, hh);
            enow = e[++eindex];
        } else {
            Fast_Two_Sum(fnow, Q, Qnew, hh);
            fnow = f[++findex];
        }
        Q = Qnew;
        if (hh != 0.0) {
            h[hindex++] = hh;
        }
        while ((eindex < elen) && (findex < flen)) {
            if ((fnow > enow) == (fnow > -enow)) {
                Two_Sum(Q, enow, Qnew, hh);
                enow = e[++eindex];
            } else {
                Two_Sum(Q, fnow, Qnew, hh);
                fnow = f[++findex];
            }
            Q = Qnew;
            if (hh != 0.0) {
                h[hindex++] = hh;
            }
        }
    }
    while (eindex < elen) {
        Two_Sum(Q, enow, Qnew, hh);
        enow = e[++eindex];
        Q = Qnew;
        if (hh != 0.0) {
            h[hindex++] = hh;
        }
    }
    while (findex < flen) {
        Two_Sum(Q, fnow, Qnew, hh);
        fnow = f[++findex];
        Q = Qnew;
        if (hh != 0.0) {
            h[hindex++] = hh;
        }
    }
    if ((Q != 0.0) || (hindex == 0)) {
        h[hindex++] = Q;
    }
    return hindex;
}

// scale_expansion_zeroelim: multiply expansion e by scalar b, eliminate zeros.
// h must NOT alias e. Returns length of h.
inline int scale_expansion_zeroelim(int elen, const double *e, double b, double *h) {
    double Q, sum, hh, product1, product0;
    double bhi, blo;
    int eindex, hindex;

    Split(b, bhi, blo);
    Two_Product_Presplit(e[0], b, bhi, blo, Q, hh);
    hindex = 0;
    if (hh != 0) {
        h[hindex++] = hh;
    }
    for (eindex = 1; eindex < elen; eindex++) {
        double enow = e[eindex];
        Two_Product_Presplit(enow, b, bhi, blo, product1, product0);
        Two_Sum(Q, product0, sum, hh);
        if (hh != 0) {
            h[hindex++] = hh;
        }
        Fast_Two_Sum(product1, sum, Q, hh);
        if (hh != 0) {
            h[hindex++] = hh;
        }
    }
    if ((Q != 0.0) || (hindex == 0)) {
        h[hindex++] = Q;
    }
    return hindex;
}

// estimate: approximate value of an expansion (sum all components).
inline double estimate(int elen, const double *e) {
    double Q = e[0];
    for (int i = 1; i < elen; i++) {
        Q += e[i];
    }
    return Q;
}

} // namespace expansion

#endif // EXPANSION_HPP
