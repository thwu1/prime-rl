//
// Independent MPFR-based verification of the incircle predicate.
// Computes incircle determinant at 256-bit precision (exact for double inputs)
// and compares results against the robust::incircle implementation.

#include "incircle.h"
#include <mpfr.h>
#include <cstdio>
#include <cstdlib>
#include <cmath>

// Compute exact incircle sign using MPFR at 256-bit precision.
// With double inputs (53-bit significands), the incircle determinant
// requires at most ~220 bits, so 256 bits gives exact results.
static int incircle_mpfr(double ax, double ay, double bx, double by,
                         double cx, double cy, double dx, double dy) {
    const mpfr_prec_t P = 256;

    mpfr_t m_adx, m_ady, m_bdx, m_bdy, m_cdx, m_cdy;
    mpfr_t m_alift, m_blift, m_clift;
    mpfr_t m_t1, m_t2, m_det, m_tmp;

    mpfr_init2(m_adx, P); mpfr_init2(m_ady, P);
    mpfr_init2(m_bdx, P); mpfr_init2(m_bdy, P);
    mpfr_init2(m_cdx, P); mpfr_init2(m_cdy, P);
    mpfr_init2(m_alift, P); mpfr_init2(m_blift, P); mpfr_init2(m_clift, P);
    mpfr_init2(m_t1, P); mpfr_init2(m_t2, P);
    mpfr_init2(m_det, P); mpfr_init2(m_tmp, P);

    // Coordinate differences (exact at this precision)
    mpfr_set_d(m_adx, ax, MPFR_RNDN); mpfr_set_d(m_tmp, dx, MPFR_RNDN);
    mpfr_sub(m_adx, m_adx, m_tmp, MPFR_RNDN);

    mpfr_set_d(m_ady, ay, MPFR_RNDN); mpfr_set_d(m_tmp, dy, MPFR_RNDN);
    mpfr_sub(m_ady, m_ady, m_tmp, MPFR_RNDN);

    mpfr_set_d(m_bdx, bx, MPFR_RNDN); mpfr_set_d(m_tmp, dx, MPFR_RNDN);
    mpfr_sub(m_bdx, m_bdx, m_tmp, MPFR_RNDN);

    mpfr_set_d(m_bdy, by, MPFR_RNDN); mpfr_set_d(m_tmp, dy, MPFR_RNDN);
    mpfr_sub(m_bdy, m_bdy, m_tmp, MPFR_RNDN);

    mpfr_set_d(m_cdx, cx, MPFR_RNDN); mpfr_set_d(m_tmp, dx, MPFR_RNDN);
    mpfr_sub(m_cdx, m_cdx, m_tmp, MPFR_RNDN);

    mpfr_set_d(m_cdy, cy, MPFR_RNDN); mpfr_set_d(m_tmp, dy, MPFR_RNDN);
    mpfr_sub(m_cdy, m_cdy, m_tmp, MPFR_RNDN);

    // Lifts: alift = adx^2 + ady^2
    mpfr_mul(m_alift, m_adx, m_adx, MPFR_RNDN);
    mpfr_mul(m_tmp, m_ady, m_ady, MPFR_RNDN);
    mpfr_add(m_alift, m_alift, m_tmp, MPFR_RNDN);

    mpfr_mul(m_blift, m_bdx, m_bdx, MPFR_RNDN);
    mpfr_mul(m_tmp, m_bdy, m_bdy, MPFR_RNDN);
    mpfr_add(m_blift, m_blift, m_tmp, MPFR_RNDN);

    mpfr_mul(m_clift, m_cdx, m_cdx, MPFR_RNDN);
    mpfr_mul(m_tmp, m_cdy, m_cdy, MPFR_RNDN);
    mpfr_add(m_clift, m_clift, m_tmp, MPFR_RNDN);

    // det = alift*(bdx*cdy - cdx*bdy) + blift*(cdx*ady - adx*cdy) + clift*(adx*bdy - bdx*ady)

    // Term 1: alift * (bdx*cdy - cdx*bdy)
    mpfr_mul(m_t1, m_bdx, m_cdy, MPFR_RNDN);
    mpfr_mul(m_t2, m_cdx, m_bdy, MPFR_RNDN);
    mpfr_sub(m_t1, m_t1, m_t2, MPFR_RNDN);
    mpfr_mul(m_det, m_alift, m_t1, MPFR_RNDN);

    // Term 2: blift * (cdx*ady - adx*cdy)
    mpfr_mul(m_t1, m_cdx, m_ady, MPFR_RNDN);
    mpfr_mul(m_t2, m_adx, m_cdy, MPFR_RNDN);
    mpfr_sub(m_t1, m_t1, m_t2, MPFR_RNDN);
    mpfr_mul(m_t1, m_blift, m_t1, MPFR_RNDN);
    mpfr_add(m_det, m_det, m_t1, MPFR_RNDN);

    // Term 3: clift * (adx*bdy - bdx*ady)
    mpfr_mul(m_t1, m_adx, m_bdy, MPFR_RNDN);
    mpfr_mul(m_t2, m_bdx, m_ady, MPFR_RNDN);
    mpfr_sub(m_t1, m_t1, m_t2, MPFR_RNDN);
    mpfr_mul(m_t1, m_clift, m_t1, MPFR_RNDN);
    mpfr_add(m_det, m_det, m_t1, MPFR_RNDN);

    int sign = mpfr_sgn(m_det);

    mpfr_clear(m_adx); mpfr_clear(m_ady);
    mpfr_clear(m_bdx); mpfr_clear(m_bdy);
    mpfr_clear(m_cdx); mpfr_clear(m_cdy);
    mpfr_clear(m_alift); mpfr_clear(m_blift); mpfr_clear(m_clift);
    mpfr_clear(m_t1); mpfr_clear(m_t2);
    mpfr_clear(m_det); mpfr_clear(m_tmp);

    return (sign > 0) ? 1 : (sign < 0) ? -1 : 0;
}

// Deterministic pseudo-random number generator (LCG)
static unsigned long long g_rng = 0xDEADBEEF42ULL;

static double rng_double(double lo, double hi) {
    g_rng = g_rng * 6364136223846793005ULL + 1442695040888963407ULL;
    double u = (double)(g_rng >> 11) / (double)(1ULL << 53);
    return lo + u * (hi - lo);
}

static int verify(int id, double ax, double ay, double bx, double by,
                  double cx, double cy, double dx, double dy) {
    int got = robust::incircle(ax, ay, bx, by, cx, cy, dx, dy);
    int ref = incircle_mpfr(ax, ay, bx, by, cx, cy, dx, dy);
    if (got != ref) {
        printf("MISMATCH config %d: robust=%d, mpfr=%d\n", id, got, ref);
        printf("  a=(%.17g, %.17g) b=(%.17g, %.17g)\n", ax, ay, bx, by);
        printf("  c=(%.17g, %.17g) d=(%.17g, %.17g)\n", cx, cy, dx, dy);
        return 1;
    }
    return 0;
}

int main() {
    int failures = 0;
    int id = 0;

    // Category 1: Random points (60 configurations)
    for (int i = 0; i < 60; i++) {
        failures += verify(id++,
            rng_double(-100, 100), rng_double(-100, 100),
            rng_double(-100, 100), rng_double(-100, 100),
            rng_double(-100, 100), rng_double(-100, 100),
            rng_double(-100, 100), rng_double(-100, 100));
    }

    // Category 2: Nearly-cocircular with tight perturbations (50 configurations)
    for (int i = 0; i < 50; i++) {
        double R = (i < 25) ? rng_double(0.5, 100.0) : rng_double(1e4, 1e8);
        double t1 = rng_double(0, 6.2831853);
        double t2 = t1 + rng_double(0.8, 1.8);
        double t3 = t2 + rng_double(0.8, 1.8);
        double t4 = t3 + rng_double(0.5, 1.5);
        double eps = rng_double(-1e-10, 1e-10) * R;
        failures += verify(id++,
            R * cos(t1), R * sin(t1),
            R * cos(t2), R * sin(t2),
            R * cos(t3), R * sin(t3),
            (R + eps) * cos(t4), (R + eps) * sin(t4));
    }

    // Category 3: Large coordinates (30 configurations)
    for (int i = 0; i < 30; i++) {
        double off = rng_double(1e10, 1e13);
        double R = rng_double(1, 1000);
        double t1 = rng_double(0, 6.2831853);
        double t2 = t1 + rng_double(0.8, 1.8);
        double t3 = t2 + rng_double(0.8, 1.8);
        double t4 = t3 + rng_double(0.5, 1.5);
        double eps = rng_double(-0.5, 0.5);
        failures += verify(id++,
            off + R * cos(t1), off + R * sin(t1),
            off + R * cos(t2), off + R * sin(t2),
            off + R * cos(t3), off + R * sin(t3),
            off + (R + eps) * cos(t4), off + (R + eps) * sin(t4));
    }

    // Category 4: Exactly cocircular — power-of-2 radii (30 configurations)
    for (int i = 0; i < 30; i++) {
        double R = (double)(1LL << (i % 26 + 1));
        failures += verify(id++, R, 0.0, 0.0, R, -R, 0.0, 0.0, -R);
    }

    // Category 5: Collinear triangle with random query (30 configurations)
    for (int i = 0; i < 30; i++) {
        double ox = rng_double(-50, 50);
        double oy = rng_double(-50, 50);
        double ux = rng_double(-1, 1), uy = rng_double(-1, 1);
        failures += verify(id++,
            ox + 1.0 * ux, oy + 1.0 * uy,
            ox + 2.0 * ux, oy + 2.0 * uy,
            ox + 3.0 * ux, oy + 3.0 * uy,
            rng_double(-100, 100), rng_double(-100, 100));
    }

    printf("\nVerified %d configurations, %d mismatches\n", id, failures);
    if (failures == 0) {
        printf("MPFR_VERIFICATION_PASSED\n");
    } else {
        printf("MPFR_VERIFICATION_FAILED\n");
    }

    mpfr_free_cache();
    return failures == 0 ? 0 : 1;
}
