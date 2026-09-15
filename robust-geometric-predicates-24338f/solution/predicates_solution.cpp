#include "predicates.hpp"
#include "expansion.hpp"

using namespace expansion;

void predicates_init() {
    exactinit();
}

// =====================================================================
// orient2d - complete adaptive implementation
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
    if ((det >= errbound) || (-det >= errbound)) return det;

    double acxtail, acytail, bcxtail, bcytail;
    Two_Diff_Tail(pa[0], pc[0], acx, acxtail);
    Two_Diff_Tail(pb[0], pc[0], bcx, bcxtail);
    Two_Diff_Tail(pa[1], pc[1], acy, acytail);
    Two_Diff_Tail(pb[1], pc[1], bcy, bcytail);

    if ((acxtail == 0.0) && (acytail == 0.0)
        && (bcxtail == 0.0) && (bcytail == 0.0)) return det;

    errbound = ccwerrboundC * detsum + resulterrbound * Absolute(det);
    det += (acx * bcytail + bcy * acxtail)
         - (acy * bcxtail + bcx * acytail);
    if ((det >= errbound) || (-det >= errbound)) return det;

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
        if (detright <= 0.0) return det;
        else detsum = detleft + detright;
    } else if (detleft < 0.0) {
        if (detright >= 0.0) return det;
        else detsum = -detleft - detright;
    } else {
        return det;
    }

    double errbound = ccwerrboundA * detsum;
    if ((det >= errbound) || (-det >= errbound)) return det;

    return orient2dadapt(pa, pb, pc, detsum);
}

// =====================================================================
// orient3d - exact implementation
// =====================================================================

static double orient3dexact(const double *pa, const double *pb,
                             const double *pc, const double *pd) {
    double axby1, axby0, bxay1, bxay0;
    double bxcy1, bxcy0, cxby1, cxby0;
    double cxdy1, cxdy0, dxcy1, dxcy0;
    double dxay1, dxay0, axdy1, axdy0;
    double axcy1, axcy0, cxay1, cxay0;
    double bxdy1, bxdy0, dxby1, dxby0;
    double ab[4], bc[4], cd[4], da[4], ac[4], bd[4];
    double temp8[8];
    int templen;
    double abc[12], bcd[12], cda[12], dab[12];
    int abclen, bcdlen, cdalen, dablen;
    double adet[24], bdet[24], cdet[24], ddet[24];
    int alen, blen, clen, dlen;
    double abdet[48], cddet[48];
    int ablen, cdlen;
    double deter[96];
    int deterlen;

    Two_Product(pa[0], pb[1], axby1, axby0);
    Two_Product(pb[0], pa[1], bxay1, bxay0);
    Two_Two_Diff(axby1, axby0, bxay1, bxay0, ab[3], ab[2], ab[1], ab[0]);

    Two_Product(pb[0], pc[1], bxcy1, bxcy0);
    Two_Product(pc[0], pb[1], cxby1, cxby0);
    Two_Two_Diff(bxcy1, bxcy0, cxby1, cxby0, bc[3], bc[2], bc[1], bc[0]);

    Two_Product(pc[0], pd[1], cxdy1, cxdy0);
    Two_Product(pd[0], pc[1], dxcy1, dxcy0);
    Two_Two_Diff(cxdy1, cxdy0, dxcy1, dxcy0, cd[3], cd[2], cd[1], cd[0]);

    Two_Product(pd[0], pa[1], dxay1, dxay0);
    Two_Product(pa[0], pd[1], axdy1, axdy0);
    Two_Two_Diff(dxay1, dxay0, axdy1, axdy0, da[3], da[2], da[1], da[0]);

    Two_Product(pa[0], pc[1], axcy1, axcy0);
    Two_Product(pc[0], pa[1], cxay1, cxay0);
    Two_Two_Diff(axcy1, axcy0, cxay1, cxay0, ac[3], ac[2], ac[1], ac[0]);

    Two_Product(pb[0], pd[1], bxdy1, bxdy0);
    Two_Product(pd[0], pb[1], dxby1, dxby0);
    Two_Two_Diff(bxdy1, bxdy0, dxby1, dxby0, bd[3], bd[2], bd[1], bd[0]);

    templen = fast_expansion_sum_zeroelim(4, cd, 4, da, temp8);
    cdalen = fast_expansion_sum_zeroelim(templen, temp8, 4, ac, cda);
    templen = fast_expansion_sum_zeroelim(4, da, 4, ab, temp8);
    dablen = fast_expansion_sum_zeroelim(templen, temp8, 4, bd, dab);
    for (int i = 0; i < 4; i++) {
        bd[i] = -bd[i];
        ac[i] = -ac[i];
    }
    templen = fast_expansion_sum_zeroelim(4, ab, 4, bc, temp8);
    abclen = fast_expansion_sum_zeroelim(templen, temp8, 4, ac, abc);
    templen = fast_expansion_sum_zeroelim(4, bc, 4, cd, temp8);
    bcdlen = fast_expansion_sum_zeroelim(templen, temp8, 4, bd, bcd);

    alen = scale_expansion_zeroelim(bcdlen, bcd, pa[2], adet);
    blen = scale_expansion_zeroelim(cdalen, cda, -pb[2], bdet);
    clen = scale_expansion_zeroelim(dablen, dab, pc[2], cdet);
    dlen = scale_expansion_zeroelim(abclen, abc, -pd[2], ddet);

    ablen = fast_expansion_sum_zeroelim(alen, adet, blen, bdet, abdet);
    cdlen = fast_expansion_sum_zeroelim(clen, cdet, dlen, ddet, cddet);
    deterlen = fast_expansion_sum_zeroelim(ablen, abdet, cdlen, cddet, deter);

    return deter[deterlen - 1];
}

double orient3d(const double *pa, const double *pb,
                const double *pc, const double *pd) {
    double adx = pa[0] - pd[0], bdx = pb[0] - pd[0], cdx = pc[0] - pd[0];
    double ady = pa[1] - pd[1], bdy = pb[1] - pd[1], cdy = pc[1] - pd[1];
    double adz = pa[2] - pd[2], bdz = pb[2] - pd[2], cdz = pc[2] - pd[2];

    double bdxcdy = bdx * cdy, cdxbdy = cdx * bdy;
    double cdxady = cdx * ady, adxcdy = adx * cdy;
    double adxbdy = adx * bdy, bdxady = bdx * ady;

    double det = adz * (bdxcdy - cdxbdy)
               + bdz * (cdxady - adxcdy)
               + cdz * (adxbdy - bdxady);

    double permanent = (Absolute(bdxcdy) + Absolute(cdxbdy)) * Absolute(adz)
                     + (Absolute(cdxady) + Absolute(adxcdy)) * Absolute(bdz)
                     + (Absolute(adxbdy) + Absolute(bdxady)) * Absolute(cdz);
    double errbound = o3derrboundA * permanent;
    if ((det > errbound) || (-det > errbound)) {
        return det;
    }

    return orient3dexact(pa, pb, pc, pd);
}

// =====================================================================
// incircle - exact implementation
// =====================================================================

static double incircleexact(const double *pa, const double *pb,
                             const double *pc, const double *pd) {
    double axby1, axby0, bxay1, bxay0;
    double bxcy1, bxcy0, cxby1, cxby0;
    double cxdy1, cxdy0, dxcy1, dxcy0;
    double dxay1, dxay0, axdy1, axdy0;
    double axcy1, axcy0, cxay1, cxay0;
    double bxdy1, bxdy0, dxby1, dxby0;
    double ab[4], bc[4], cd[4], da[4], ac[4], bd[4];
    double temp8[8];
    int templen;
    double abc[12], bcd[12], cda[12], dab[12];
    int abclen, bcdlen, cdalen, dablen;
    double det24x[24], det24y[24], det48x[48], det48y[48];
    int xlen, ylen;
    double adet[96], bdet[96], cdet[96], ddet[96];
    int alen, blen, clen, dlen;
    double abdet[192], cddet[192];
    int ablen, cdlen;
    double deter[384];
    int deterlen;

    Two_Product(pa[0], pb[1], axby1, axby0);
    Two_Product(pb[0], pa[1], bxay1, bxay0);
    Two_Two_Diff(axby1, axby0, bxay1, bxay0, ab[3], ab[2], ab[1], ab[0]);

    Two_Product(pb[0], pc[1], bxcy1, bxcy0);
    Two_Product(pc[0], pb[1], cxby1, cxby0);
    Two_Two_Diff(bxcy1, bxcy0, cxby1, cxby0, bc[3], bc[2], bc[1], bc[0]);

    Two_Product(pc[0], pd[1], cxdy1, cxdy0);
    Two_Product(pd[0], pc[1], dxcy1, dxcy0);
    Two_Two_Diff(cxdy1, cxdy0, dxcy1, dxcy0, cd[3], cd[2], cd[1], cd[0]);

    Two_Product(pd[0], pa[1], dxay1, dxay0);
    Two_Product(pa[0], pd[1], axdy1, axdy0);
    Two_Two_Diff(dxay1, dxay0, axdy1, axdy0, da[3], da[2], da[1], da[0]);

    Two_Product(pa[0], pc[1], axcy1, axcy0);
    Two_Product(pc[0], pa[1], cxay1, cxay0);
    Two_Two_Diff(axcy1, axcy0, cxay1, cxay0, ac[3], ac[2], ac[1], ac[0]);

    Two_Product(pb[0], pd[1], bxdy1, bxdy0);
    Two_Product(pd[0], pb[1], dxby1, dxby0);
    Two_Two_Diff(bxdy1, bxdy0, dxby1, dxby0, bd[3], bd[2], bd[1], bd[0]);

    templen = fast_expansion_sum_zeroelim(4, cd, 4, da, temp8);
    cdalen = fast_expansion_sum_zeroelim(templen, temp8, 4, ac, cda);
    templen = fast_expansion_sum_zeroelim(4, da, 4, ab, temp8);
    dablen = fast_expansion_sum_zeroelim(templen, temp8, 4, bd, dab);
    for (int i = 0; i < 4; i++) {
        bd[i] = -bd[i];
        ac[i] = -ac[i];
    }
    templen = fast_expansion_sum_zeroelim(4, ab, 4, bc, temp8);
    abclen = fast_expansion_sum_zeroelim(templen, temp8, 4, ac, abc);
    templen = fast_expansion_sum_zeroelim(4, bc, 4, cd, temp8);
    bcdlen = fast_expansion_sum_zeroelim(templen, temp8, 4, bd, bcd);

    xlen = scale_expansion_zeroelim(bcdlen, bcd, pa[0], det24x);
    xlen = scale_expansion_zeroelim(xlen, det24x, pa[0], det48x);
    ylen = scale_expansion_zeroelim(bcdlen, bcd, pa[1], det24y);
    ylen = scale_expansion_zeroelim(ylen, det24y, pa[1], det48y);
    alen = fast_expansion_sum_zeroelim(xlen, det48x, ylen, det48y, adet);

    xlen = scale_expansion_zeroelim(cdalen, cda, pb[0], det24x);
    xlen = scale_expansion_zeroelim(xlen, det24x, -pb[0], det48x);
    ylen = scale_expansion_zeroelim(cdalen, cda, pb[1], det24y);
    ylen = scale_expansion_zeroelim(ylen, det24y, -pb[1], det48y);
    blen = fast_expansion_sum_zeroelim(xlen, det48x, ylen, det48y, bdet);

    xlen = scale_expansion_zeroelim(dablen, dab, pc[0], det24x);
    xlen = scale_expansion_zeroelim(xlen, det24x, pc[0], det48x);
    ylen = scale_expansion_zeroelim(dablen, dab, pc[1], det24y);
    ylen = scale_expansion_zeroelim(ylen, det24y, pc[1], det48y);
    clen = fast_expansion_sum_zeroelim(xlen, det48x, ylen, det48y, cdet);

    xlen = scale_expansion_zeroelim(abclen, abc, pd[0], det24x);
    xlen = scale_expansion_zeroelim(xlen, det24x, -pd[0], det48x);
    ylen = scale_expansion_zeroelim(abclen, abc, pd[1], det24y);
    ylen = scale_expansion_zeroelim(ylen, det24y, -pd[1], det48y);
    dlen = fast_expansion_sum_zeroelim(xlen, det48x, ylen, det48y, ddet);

    ablen = fast_expansion_sum_zeroelim(alen, adet, blen, bdet, abdet);
    cdlen = fast_expansion_sum_zeroelim(clen, cdet, dlen, ddet, cddet);
    deterlen = fast_expansion_sum_zeroelim(ablen, abdet, cdlen, cddet, deter);

    return deter[deterlen - 1];
}

double incircle(const double *pa, const double *pb,
                const double *pc, const double *pd) {
    double adx = pa[0] - pd[0], ady = pa[1] - pd[1];
    double bdx = pb[0] - pd[0], bdy = pb[1] - pd[1];
    double cdx = pc[0] - pd[0], cdy = pc[1] - pd[1];

    double bdxcdy = bdx * cdy, cdxbdy = cdx * bdy;
    double cdxady = cdx * ady, adxcdy = adx * cdy;
    double adxbdy = adx * bdy, bdxady = bdx * ady;

    double alift = adx * adx + ady * ady;
    double blift = bdx * bdx + bdy * bdy;
    double clift = cdx * cdx + cdy * cdy;

    double det = alift * (bdxcdy - cdxbdy)
               + blift * (cdxady - adxcdy)
               + clift * (adxbdy - bdxady);

    double permanent = (Absolute(bdxcdy) + Absolute(cdxbdy)) * alift
                     + (Absolute(cdxady) + Absolute(adxcdy)) * blift
                     + (Absolute(adxbdy) + Absolute(bdxady)) * clift;
    double errbound = iccerrboundA * permanent;
    if ((det > errbound) || (-det > errbound)) {
        return det;
    }

    return incircleexact(pa, pb, pc, pd);
}

// =====================================================================
// insphere - exact implementation
// =====================================================================

static double insphereexact(const double *pa, const double *pb,
                             const double *pc, const double *pd, const double *pe) {
    double axby1, axby0, bxay1, bxay0;
    double bxcy1, bxcy0, cxby1, cxby0;
    double cxdy1, cxdy0, dxcy1, dxcy0;
    double dxey1, dxey0, exdy1, exdy0;
    double exay1, exay0, axey1, axey0;
    double axcy1, axcy0, cxay1, cxay0;
    double bxdy1, bxdy0, dxby1, dxby0;
    double cxey1, cxey0, excy1, excy0;
    double dxay1, dxay0, axdy1, axdy0;
    double exby1, exby0, bxey1, bxey0;

    double ab[4], bc[4], cd[4], de[4], ea[4];
    double ac[4], bd[4], ce[4], da[4], eb[4];
    double temp8a[8], temp8b[8], temp16[16];
    int temp8alen, temp8blen, temp16len;
    double abc[24], bcd[24], cde[24], dea[24], eab[24];
    double abd[24], bce[24], cda[24], deb[24], eac[24];
    int abclen, bcdlen, cdelen, dealen, eablen;
    int abdlen, bcelen, cdalen, deblen, eaclen;
    double temp48a[48], temp48b[48];
    int temp48alen, temp48blen;
    double abcd[96], bcde[96], cdea[96], deab[96], eabc[96];
    int abcdlen, bcdelen, cdealen, deablen, eabclen;
    double temp192[192];
    double det384x[384], det384y[384], det384z[384];
    int xlen, ylen, zlen;
    double detxy[768];
    int xylen;
    double adet[1152], bdet[1152], cdet[1152], ddet[1152], edet[1152];
    int alen, blen, clen, dlen, elen;
    double abdet[2304], cddet[2304], cdedet[3456];
    int ablen, cdlen;
    double deter[5760];
    int deterlen;

    // Compute all 10 pairwise 2D cross products
    Two_Product(pa[0], pb[1], axby1, axby0);
    Two_Product(pb[0], pa[1], bxay1, bxay0);
    Two_Two_Diff(axby1, axby0, bxay1, bxay0, ab[3], ab[2], ab[1], ab[0]);

    Two_Product(pb[0], pc[1], bxcy1, bxcy0);
    Two_Product(pc[0], pb[1], cxby1, cxby0);
    Two_Two_Diff(bxcy1, bxcy0, cxby1, cxby0, bc[3], bc[2], bc[1], bc[0]);

    Two_Product(pc[0], pd[1], cxdy1, cxdy0);
    Two_Product(pd[0], pc[1], dxcy1, dxcy0);
    Two_Two_Diff(cxdy1, cxdy0, dxcy1, dxcy0, cd[3], cd[2], cd[1], cd[0]);

    Two_Product(pd[0], pe[1], dxey1, dxey0);
    Two_Product(pe[0], pd[1], exdy1, exdy0);
    Two_Two_Diff(dxey1, dxey0, exdy1, exdy0, de[3], de[2], de[1], de[0]);

    Two_Product(pe[0], pa[1], exay1, exay0);
    Two_Product(pa[0], pe[1], axey1, axey0);
    Two_Two_Diff(exay1, exay0, axey1, axey0, ea[3], ea[2], ea[1], ea[0]);

    Two_Product(pa[0], pc[1], axcy1, axcy0);
    Two_Product(pc[0], pa[1], cxay1, cxay0);
    Two_Two_Diff(axcy1, axcy0, cxay1, cxay0, ac[3], ac[2], ac[1], ac[0]);

    Two_Product(pb[0], pd[1], bxdy1, bxdy0);
    Two_Product(pd[0], pb[1], dxby1, dxby0);
    Two_Two_Diff(bxdy1, bxdy0, dxby1, dxby0, bd[3], bd[2], bd[1], bd[0]);

    Two_Product(pc[0], pe[1], cxey1, cxey0);
    Two_Product(pe[0], pc[1], excy1, excy0);
    Two_Two_Diff(cxey1, cxey0, excy1, excy0, ce[3], ce[2], ce[1], ce[0]);

    Two_Product(pd[0], pa[1], dxay1, dxay0);
    Two_Product(pa[0], pd[1], axdy1, axdy0);
    Two_Two_Diff(dxay1, dxay0, axdy1, axdy0, da[3], da[2], da[1], da[0]);

    Two_Product(pe[0], pb[1], exby1, exby0);
    Two_Product(pb[0], pe[1], bxey1, bxey0);
    Two_Two_Diff(exby1, exby0, bxey1, bxey0, eb[3], eb[2], eb[1], eb[0]);

    // Compute 10 triple-product cofactors (3-point minors scaled by z)
    // abc = az*bc - bz*ac + cz*ab
    temp8alen = scale_expansion_zeroelim(4, bc, pa[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, ac, -pb[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, ab, pc[2], temp8a);
    abclen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, abc);

    // bcd = bz*cd - cz*bd + dz*bc
    temp8alen = scale_expansion_zeroelim(4, cd, pb[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, bd, -pc[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, bc, pd[2], temp8a);
    bcdlen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, bcd);

    // cde = cz*de - dz*ce + ez*cd
    temp8alen = scale_expansion_zeroelim(4, de, pc[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, ce, -pd[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, cd, pe[2], temp8a);
    cdelen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, cde);

    // dea = dz*ea - ez*da + az*de
    temp8alen = scale_expansion_zeroelim(4, ea, pd[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, da, -pe[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, de, pa[2], temp8a);
    dealen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, dea);

    // eab = ez*ab - az*eb + bz*ea
    temp8alen = scale_expansion_zeroelim(4, ab, pe[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, eb, -pa[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, ea, pb[2], temp8a);
    eablen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, eab);

    // abd = az*bd + bz*da + dz*ab
    temp8alen = scale_expansion_zeroelim(4, bd, pa[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, da, pb[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, ab, pd[2], temp8a);
    abdlen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, abd);

    // bce = bz*ce + cz*eb + ez*bc
    temp8alen = scale_expansion_zeroelim(4, ce, pb[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, eb, pc[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, bc, pe[2], temp8a);
    bcelen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, bce);

    // cda = cz*da + dz*ac + az*cd
    temp8alen = scale_expansion_zeroelim(4, da, pc[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, ac, pd[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, cd, pa[2], temp8a);
    cdalen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, cda);

    // deb = dz*eb + ez*bd + bz*de
    temp8alen = scale_expansion_zeroelim(4, eb, pd[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, bd, pe[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, de, pb[2], temp8a);
    deblen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, deb);

    // eac = ez*ac + az*ce + cz*ea
    temp8alen = scale_expansion_zeroelim(4, ac, pe[2], temp8a);
    temp8blen = scale_expansion_zeroelim(4, ce, pa[2], temp8b);
    temp16len = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp8blen, temp8b, temp16);
    temp8alen = scale_expansion_zeroelim(4, ea, pc[2], temp8a);
    eaclen = fast_expansion_sum_zeroelim(temp8alen, temp8a, temp16len, temp16, eac);

    // Combine into 5 four-point cofactors, scale by squared coords, and sum
    // bcde for point a
    temp48alen = fast_expansion_sum_zeroelim(cdelen, cde, bcelen, bce, temp48a);
    temp48blen = fast_expansion_sum_zeroelim(deblen, deb, bcdlen, bcd, temp48b);
    for (int i = 0; i < temp48blen; i++) temp48b[i] = -temp48b[i];
    bcdelen = fast_expansion_sum_zeroelim(temp48alen, temp48a, temp48blen, temp48b, bcde);
    xlen = scale_expansion_zeroelim(bcdelen, bcde, pa[0], temp192);
    xlen = scale_expansion_zeroelim(xlen, temp192, pa[0], det384x);
    ylen = scale_expansion_zeroelim(bcdelen, bcde, pa[1], temp192);
    ylen = scale_expansion_zeroelim(ylen, temp192, pa[1], det384y);
    zlen = scale_expansion_zeroelim(bcdelen, bcde, pa[2], temp192);
    zlen = scale_expansion_zeroelim(zlen, temp192, pa[2], det384z);
    xylen = fast_expansion_sum_zeroelim(xlen, det384x, ylen, det384y, detxy);
    alen = fast_expansion_sum_zeroelim(xylen, detxy, zlen, det384z, adet);

    // cdea for point b
    temp48alen = fast_expansion_sum_zeroelim(dealen, dea, cdalen, cda, temp48a);
    temp48blen = fast_expansion_sum_zeroelim(eaclen, eac, cdelen, cde, temp48b);
    for (int i = 0; i < temp48blen; i++) temp48b[i] = -temp48b[i];
    cdealen = fast_expansion_sum_zeroelim(temp48alen, temp48a, temp48blen, temp48b, cdea);
    xlen = scale_expansion_zeroelim(cdealen, cdea, pb[0], temp192);
    xlen = scale_expansion_zeroelim(xlen, temp192, pb[0], det384x);
    ylen = scale_expansion_zeroelim(cdealen, cdea, pb[1], temp192);
    ylen = scale_expansion_zeroelim(ylen, temp192, pb[1], det384y);
    zlen = scale_expansion_zeroelim(cdealen, cdea, pb[2], temp192);
    zlen = scale_expansion_zeroelim(zlen, temp192, pb[2], det384z);
    xylen = fast_expansion_sum_zeroelim(xlen, det384x, ylen, det384y, detxy);
    blen = fast_expansion_sum_zeroelim(xylen, detxy, zlen, det384z, bdet);

    // deab for point c
    temp48alen = fast_expansion_sum_zeroelim(eablen, eab, deblen, deb, temp48a);
    temp48blen = fast_expansion_sum_zeroelim(abdlen, abd, dealen, dea, temp48b);
    for (int i = 0; i < temp48blen; i++) temp48b[i] = -temp48b[i];
    deablen = fast_expansion_sum_zeroelim(temp48alen, temp48a, temp48blen, temp48b, deab);
    xlen = scale_expansion_zeroelim(deablen, deab, pc[0], temp192);
    xlen = scale_expansion_zeroelim(xlen, temp192, pc[0], det384x);
    ylen = scale_expansion_zeroelim(deablen, deab, pc[1], temp192);
    ylen = scale_expansion_zeroelim(ylen, temp192, pc[1], det384y);
    zlen = scale_expansion_zeroelim(deablen, deab, pc[2], temp192);
    zlen = scale_expansion_zeroelim(zlen, temp192, pc[2], det384z);
    xylen = fast_expansion_sum_zeroelim(xlen, det384x, ylen, det384y, detxy);
    clen = fast_expansion_sum_zeroelim(xylen, detxy, zlen, det384z, cdet);

    // eabc for point d
    temp48alen = fast_expansion_sum_zeroelim(abclen, abc, eaclen, eac, temp48a);
    temp48blen = fast_expansion_sum_zeroelim(bcelen, bce, eablen, eab, temp48b);
    for (int i = 0; i < temp48blen; i++) temp48b[i] = -temp48b[i];
    eabclen = fast_expansion_sum_zeroelim(temp48alen, temp48a, temp48blen, temp48b, eabc);
    xlen = scale_expansion_zeroelim(eabclen, eabc, pd[0], temp192);
    xlen = scale_expansion_zeroelim(xlen, temp192, pd[0], det384x);
    ylen = scale_expansion_zeroelim(eabclen, eabc, pd[1], temp192);
    ylen = scale_expansion_zeroelim(ylen, temp192, pd[1], det384y);
    zlen = scale_expansion_zeroelim(eabclen, eabc, pd[2], temp192);
    zlen = scale_expansion_zeroelim(zlen, temp192, pd[2], det384z);
    xylen = fast_expansion_sum_zeroelim(xlen, det384x, ylen, det384y, detxy);
    dlen = fast_expansion_sum_zeroelim(xylen, detxy, zlen, det384z, ddet);

    // abcd for point e
    temp48alen = fast_expansion_sum_zeroelim(bcdlen, bcd, abdlen, abd, temp48a);
    temp48blen = fast_expansion_sum_zeroelim(cdalen, cda, abclen, abc, temp48b);
    for (int i = 0; i < temp48blen; i++) temp48b[i] = -temp48b[i];
    abcdlen = fast_expansion_sum_zeroelim(temp48alen, temp48a, temp48blen, temp48b, abcd);
    xlen = scale_expansion_zeroelim(abcdlen, abcd, pe[0], temp192);
    xlen = scale_expansion_zeroelim(xlen, temp192, pe[0], det384x);
    ylen = scale_expansion_zeroelim(abcdlen, abcd, pe[1], temp192);
    ylen = scale_expansion_zeroelim(ylen, temp192, pe[1], det384y);
    zlen = scale_expansion_zeroelim(abcdlen, abcd, pe[2], temp192);
    zlen = scale_expansion_zeroelim(zlen, temp192, pe[2], det384z);
    xylen = fast_expansion_sum_zeroelim(xlen, det384x, ylen, det384y, detxy);
    elen = fast_expansion_sum_zeroelim(xylen, detxy, zlen, det384z, edet);

    // Final summation
    ablen = fast_expansion_sum_zeroelim(alen, adet, blen, bdet, abdet);
    cdlen = fast_expansion_sum_zeroelim(clen, cdet, dlen, ddet, cddet);
    cdelen = fast_expansion_sum_zeroelim(cdlen, cddet, elen, edet, cdedet);
    deterlen = fast_expansion_sum_zeroelim(ablen, abdet, cdelen, cdedet, deter);

    return deter[deterlen - 1];
}

double insphere(const double *pa, const double *pb, const double *pc,
                const double *pd, const double *pe) {
    double aex = pa[0] - pe[0], bex = pb[0] - pe[0];
    double cex = pc[0] - pe[0], dex = pd[0] - pe[0];
    double aey = pa[1] - pe[1], bey = pb[1] - pe[1];
    double cey = pc[1] - pe[1], dey = pd[1] - pe[1];
    double aez = pa[2] - pe[2], bez = pb[2] - pe[2];
    double cez = pc[2] - pe[2], dez = pd[2] - pe[2];

    double aexbey = aex * bey, bexaey = bex * aey;
    double bexcey = bex * cey, cexbey = cex * bey;
    double cexdey = cex * dey, dexcey = dex * cey;
    double dexaey = dex * aey, aexdey = aex * dey;
    double aexcey = aex * cey, cexaey = cex * aey;
    double bexdey = bex * dey, dexbey = dex * bey;

    double ab = aexbey - bexaey;
    double bc = bexcey - cexbey;
    double cd = cexdey - dexcey;
    double da = dexaey - aexdey;
    double ac = aexcey - cexaey;
    double bd = bexdey - dexbey;

    double abc = aez * bc - bez * ac + cez * ab;
    double bcd = bez * cd - cez * bd + dez * bc;
    double cda = cez * da + dez * ac + aez * cd;
    double dab = dez * ab + aez * bd + bez * da;

    double alift = aex * aex + aey * aey + aez * aez;
    double blift = bex * bex + bey * bey + bez * bez;
    double clift = cex * cex + cey * cey + cez * cez;
    double dlift = dex * dex + dey * dey + dez * dez;

    double det = (dlift * abc - clift * dab) + (blift * cda - alift * bcd);

    double aezplus = Absolute(aez), bezplus = Absolute(bez);
    double cezplus = Absolute(cez), dezplus = Absolute(dez);
    double aexbeyplus = Absolute(aexbey), bexaeyplus = Absolute(bexaey);
    double bexceyplus = Absolute(bexcey), cexbeyplus = Absolute(cexbey);
    double cexdeyplus = Absolute(cexdey), dexceyplus = Absolute(dexcey);
    double dexaeyplus = Absolute(dexaey), aexdeyplus = Absolute(aexdey);
    double aexceyplus = Absolute(aexcey), cexaeyplus = Absolute(cexaey);
    double bexdeyplus = Absolute(bexdey), dexbeyplus = Absolute(dexbey);

    double permanent =
        ((cexdeyplus + dexceyplus) * bezplus
         + (dexbeyplus + bexdeyplus) * cezplus
         + (bexceyplus + cexbeyplus) * dezplus) * alift
      + ((dexaeyplus + aexdeyplus) * cezplus
         + (aexceyplus + cexaeyplus) * dezplus
         + (cexdeyplus + dexceyplus) * aezplus) * blift
      + ((aexbeyplus + bexaeyplus) * dezplus
         + (bexdeyplus + dexbeyplus) * aezplus
         + (dexaeyplus + aexdeyplus) * bezplus) * clift
      + ((bexceyplus + cexbeyplus) * aezplus
         + (cexaeyplus + aexceyplus) * bezplus
         + (aexbeyplus + bexaeyplus) * cezplus) * dlift;

    double errbound = isperrboundA * permanent;
    if ((det > errbound) || (-det > errbound)) {
        return det;
    }

    return insphereexact(pa, pb, pc, pd, pe);
}
