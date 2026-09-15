//
// Robust adaptive-precision 2D incircle predicate (header-only).
// Implements cascaded evaluation:
//   Stage A: fast double-precision filter with semi-static error bound
//   Stage B: exact expansion-arithmetic fallback using TwoDiff for
//            coordinate differences to handle all near-degenerate cases
//
// No external dependencies beyond <cmath>.

#ifndef ROBUST_INCIRCLE_H
#define ROBUST_INCIRCLE_H

#include <cmath>

namespace robust {

// ============================================================
// Constants
// ============================================================

// Splitter for Dekker splitting: 2^ceil(p/2) + 1 where p = 53
static constexpr double SPLITTER = 134217729.0; // 2^27 + 1

// Machine epsilon for IEEE 754 double: 2^-53
static constexpr double EPSILON = 1.1102230246251565e-16;

// Semi-static error bound for incircle filter
static constexpr double ICCERR_A = (10.0 + 96.0 * EPSILON) * EPSILON;

// ============================================================
// Error-free transformations
// ============================================================

inline void Split(double a, double& ahi, double& alo) {
    double c = SPLITTER * a;
    double abig = c - a;
    ahi = c - abig;
    alo = a - ahi;
}

inline void TwoProduct(double a, double b, double& x, double& y) {
    x = a * b;
    double ahi, alo, bhi, blo;
    Split(a, ahi, alo);
    Split(b, bhi, blo);
    double err1 = x - (ahi * bhi);
    double err2 = err1 - (alo * bhi);
    double err3 = err2 - (ahi * blo);
    y = (alo * blo) - err3;
}

inline void TwoProductPresplit(double a, double b,
                                double bhi, double blo,
                                double& x, double& y) {
    x = a * b;
    double ahi, alo;
    Split(a, ahi, alo);
    double err1 = x - (ahi * bhi);
    double err2 = err1 - (alo * bhi);
    double err3 = err2 - (ahi * blo);
    y = (alo * blo) - err3;
}

inline void TwoSum(double a, double b, double& x, double& y) {
    x = a + b;
    double bvirt = x - a;
    double avirt = x - bvirt;
    double bround = b - bvirt;
    double around = a - avirt;
    y = around + bround;
}

inline void TwoDiff(double a, double b, double& x, double& y) {
    x = a - b;
    double bvirt = a - x;
    double avirt = x + bvirt;
    double bround = bvirt - b;
    double around = a - avirt;
    y = around + bround;
}

// ============================================================
// Expansion arithmetic
// ============================================================

// Sum two non-overlapping expansions e and f into h (zero-eliminated).
// Returns the length of h. h must have space for elen + flen elements.
inline int expansion_sum_zeroelim(int elen, const double* e,
                                   int flen, const double* f,
                                   double* h) {
    double Q, Qnew, hh;
    int eindex = 0, findex = 0, hindex = 0;
    double enow = e[0], fnow = f[0];

    if ((fnow > enow) == (fnow > -enow)) {
        Q = enow;
        eindex++;
        if (eindex < elen) enow = e[eindex];
    } else {
        Q = fnow;
        findex++;
        if (findex < flen) fnow = f[findex];
    }

    if (eindex < elen && findex < flen) {
        enow = e[eindex]; fnow = f[findex];
        if ((fnow > enow) == (fnow > -enow)) {
            TwoSum(Q, enow, Qnew, hh);
            eindex++;
            if (eindex < elen) enow = e[eindex];
        } else {
            TwoSum(Q, fnow, Qnew, hh);
            findex++;
            if (findex < flen) fnow = f[findex];
        }
        Q = Qnew;
        if (hh != 0.0) h[hindex++] = hh;

        while (eindex < elen && findex < flen) {
            enow = e[eindex]; fnow = f[findex];
            if ((fnow > enow) == (fnow > -enow)) {
                TwoSum(Q, enow, Qnew, hh);
                eindex++;
                if (eindex < elen) enow = e[eindex];
            } else {
                TwoSum(Q, fnow, Qnew, hh);
                findex++;
                if (findex < flen) fnow = f[findex];
            }
            Q = Qnew;
            if (hh != 0.0) h[hindex++] = hh;
        }
    }

    while (eindex < elen) {
        TwoSum(Q, e[eindex], Qnew, hh);
        eindex++;
        Q = Qnew;
        if (hh != 0.0) h[hindex++] = hh;
    }

    while (findex < flen) {
        TwoSum(Q, f[findex], Qnew, hh);
        findex++;
        Q = Qnew;
        if (hh != 0.0) h[hindex++] = hh;
    }

    if (Q != 0.0 || hindex == 0) h[hindex++] = Q;
    return hindex;
}

// Multiply expansion e by scalar b, zero-eliminated.
// Returns the length of h. h must have space for 2 * elen elements.
inline int scale_expansion_zeroelim(int elen, const double* e,
                                     double b, double* h) {
    double Q, hh, product1, product0, sum;
    double bhi, blo;
    int hindex = 0;

    Split(b, bhi, blo);
    TwoProductPresplit(e[0], b, bhi, blo, Q, hh);
    if (hh != 0.0) h[hindex++] = hh;

    for (int eindex = 1; eindex < elen; eindex++) {
        TwoProductPresplit(e[eindex], b, bhi, blo, product1, product0);
        TwoSum(Q, product0, sum, hh);
        if (hh != 0.0) h[hindex++] = hh;
        TwoSum(product1, sum, Q, hh);
        if (hh != 0.0) h[hindex++] = hh;
    }

    if (Q != 0.0 || hindex == 0) h[hindex++] = Q;
    return hindex;
}

// ============================================================
// Expansion multiplication helpers
// ============================================================

// Multiply two 2-expansions exactly. Result in h (max 8 terms).
// a = a[0] + a[1], b = b[0] + b[1], where [0] is tail, [1] is head.
inline int mul_2exp(const double* a, const double* b, double* h) {
    double p0[2], p1[2], p2[2], p3[2];
    TwoProduct(a[0], b[0], p0[1], p0[0]);
    TwoProduct(a[0], b[1], p1[1], p1[0]);
    TwoProduct(a[1], b[0], p2[1], p2[0]);
    TwoProduct(a[1], b[1], p3[1], p3[0]);

    double s1[4], s2[8];
    int s1_len = expansion_sum_zeroelim(2, p0, 2, p1, s1);
    int s2_len = expansion_sum_zeroelim(s1_len, s1, 2, p2, s2);
    return expansion_sum_zeroelim(s2_len, s2, 2, p3, h);
}

// Multiply two arbitrary-length expansions. Result in h (max 2*elen*flen).
// work must have at least as many elements as h.
inline int mul_exp(int elen, const double* e,
                    int flen, const double* f,
                    double* h, double* work) {
    double scaled[64];
    int hlen = scale_expansion_zeroelim(flen, f, e[0], h);

    for (int i = 1; i < elen; i++) {
        int slen = scale_expansion_zeroelim(flen, f, e[i], scaled);
        int wlen = expansion_sum_zeroelim(hlen, h, slen, scaled, work);
        for (int j = 0; j < wlen; j++) h[j] = work[j];
        hlen = wlen;
    }
    return hlen;
}

// ============================================================
// Incircle predicate
// ============================================================

inline int incircle_filtered(double ax, double ay, double bx, double by,
                              double cx, double cy, double dx, double dy) {
    double adx = ax - dx, ady = ay - dy;
    double bdx = bx - dx, bdy = by - dy;
    double cdx = cx - dx, cdy = cy - dy;

    double bdxcdy = bdx * cdy, cdxbdy = cdx * bdy;
    double cdxady = cdx * ady, adxcdy = adx * cdy;
    double adxbdy = adx * bdy, bdxady = bdx * ady;

    double alift = adx * adx + ady * ady;
    double blift = bdx * bdx + bdy * bdy;
    double clift = cdx * cdx + cdy * cdy;

    double det = alift * (bdxcdy - cdxbdy)
               + blift * (cdxady - adxcdy)
               + clift * (adxbdy - bdxady);

    double permanent = (std::fabs(bdxcdy) + std::fabs(cdxbdy)) * alift
                     + (std::fabs(cdxady) + std::fabs(adxcdy)) * blift
                     + (std::fabs(adxbdy) + std::fabs(bdxady)) * clift;

    double errbound = ICCERR_A * permanent;

    if (det > errbound || -det > errbound) {
        return (det > 0.0) ? 1 : -1;
    }
    return 0; // uncertain — need exact arithmetic
}

inline int incircle_exact(double ax, double ay, double bx, double by,
                           double cx, double cy, double dx, double dy) {
    // Exact coordinate differences as 2-expansions [tail, head].
    // TwoDiff captures the roundoff so no precision is lost.
    double adx[2], ady[2], bdx[2], bdy[2], cdx[2], cdy[2];
    TwoDiff(ax, dx, adx[1], adx[0]);
    TwoDiff(ay, dy, ady[1], ady[0]);
    TwoDiff(bx, dx, bdx[1], bdx[0]);
    TwoDiff(by, dy, bdy[1], bdy[0]);
    TwoDiff(cx, dx, cdx[1], cdx[0]);
    TwoDiff(cy, dy, cdy[1], cdy[0]);

    // 2x2 cross products via exact 2-expansion multiplication
    // bc = bdx*cdy - cdx*bdy
    double bdx_cdy[8], cdx_bdy[8];
    int bdx_cdy_len = mul_2exp(bdx, cdy, bdx_cdy);
    int cdx_bdy_len = mul_2exp(cdx, bdy, cdx_bdy);
    double neg_cdx_bdy[8];
    for (int i = 0; i < cdx_bdy_len; i++) neg_cdx_bdy[i] = -cdx_bdy[i];
    double bc[16];
    int bc_len = expansion_sum_zeroelim(bdx_cdy_len, bdx_cdy,
                                         cdx_bdy_len, neg_cdx_bdy, bc);

    // ca = cdx*ady - adx*cdy
    double cdx_ady[8], adx_cdy[8];
    int cdx_ady_len = mul_2exp(cdx, ady, cdx_ady);
    int adx_cdy_len = mul_2exp(adx, cdy, adx_cdy);
    double neg_adx_cdy[8];
    for (int i = 0; i < adx_cdy_len; i++) neg_adx_cdy[i] = -adx_cdy[i];
    double ca[16];
    int ca_len = expansion_sum_zeroelim(cdx_ady_len, cdx_ady,
                                         adx_cdy_len, neg_adx_cdy, ca);

    // ab = adx*bdy - bdx*ady
    double adx_bdy[8], bdx_ady[8];
    int adx_bdy_len = mul_2exp(adx, bdy, adx_bdy);
    int bdx_ady_len = mul_2exp(bdx, ady, bdx_ady);
    double neg_bdx_ady[8];
    for (int i = 0; i < bdx_ady_len; i++) neg_bdx_ady[i] = -bdx_ady[i];
    double ab[16];
    int ab_len = expansion_sum_zeroelim(adx_bdy_len, adx_bdy,
                                         bdx_ady_len, neg_bdx_ady, ab);

    // Lifts: alift = adx^2 + ady^2 (exact via 2-expansion squaring)
    double adx_sq[8], ady_sq[8];
    int adx_sq_len = mul_2exp(adx, adx, adx_sq);
    int ady_sq_len = mul_2exp(ady, ady, ady_sq);
    double alift[16];
    int alift_len = expansion_sum_zeroelim(adx_sq_len, adx_sq,
                                            ady_sq_len, ady_sq, alift);

    double bdx_sq[8], bdy_sq[8];
    int bdx_sq_len = mul_2exp(bdx, bdx, bdx_sq);
    int bdy_sq_len = mul_2exp(bdy, bdy, bdy_sq);
    double blift[16];
    int blift_len = expansion_sum_zeroelim(bdx_sq_len, bdx_sq,
                                            bdy_sq_len, bdy_sq, blift);

    double cdx_sq[8], cdy_sq[8];
    int cdx_sq_len = mul_2exp(cdx, cdx, cdx_sq);
    int cdy_sq_len = mul_2exp(cdy, cdy, cdy_sq);
    double clift[16];
    int clift_len = expansion_sum_zeroelim(cdx_sq_len, cdx_sq,
                                            cdy_sq_len, cdy_sq, clift);

    // Determinant terms: adet = bc * alift, bdet = ca * blift, cdet = ab * clift
    double work[600];

    double adet[600];
    int adet_len = mul_exp(bc_len, bc, alift_len, alift, adet, work);

    double bdet[600];
    int bdet_len = mul_exp(ca_len, ca, blift_len, blift, bdet, work);

    double cdet[600];
    int cdet_len = mul_exp(ab_len, ab, clift_len, clift, cdet, work);

    // Final sum: det = adet + bdet + cdet
    double abdet[1200];
    int abdet_len = expansion_sum_zeroelim(adet_len, adet,
                                            bdet_len, bdet, abdet);

    double deter[1800];
    int deter_len = expansion_sum_zeroelim(abdet_len, abdet,
                                            cdet_len, cdet, deter);

    // Sign is determined by most significant component
    return (deter[deter_len - 1] > 0.0) ? 1 :
           (deter[deter_len - 1] < 0.0) ? -1 : 0;
}

// Public API: cascaded filter -> exact
inline int incircle(double ax, double ay, double bx, double by,
                     double cx, double cy, double dx, double dy) {
    int ret = incircle_filtered(ax, ay, bx, by, cx, cy, dx, dy);
    if (ret != 0) return ret;
    return incircle_exact(ax, ay, bx, by, cx, cy, dx, dy);
}

inline int incircle(const double* a, const double* b,
                     const double* c, const double* d) {
    return incircle(a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1]);
}

} // namespace robust

#endif // ROBUST_INCIRCLE_H
