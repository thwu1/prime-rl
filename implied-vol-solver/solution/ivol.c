/* High-precision Black-Scholes implied volatility solver.
 *
 * Exports: bs_price(), implied_vol()
 * Links against: -lm only
 *
 * Uses Stefanica-Radoicic initial guess with Halley iteration on the
 * log-price objective. erfcx implemented from scratch since it is not
 * in the C standard library.
 */

#include <math.h>
#include <float.h>
#include "ivol.h"

#define SQRT_2       1.4142135623730950488
#define INV_SQRT_2   0.70710678118654752440
#define INV_SQRT_2PI 0.39894228040143267794
#define TWO_OVER_PI  0.63661977236758134308
#define MY_EPS       2.2204460492503131e-16
#define SQRT_MY_EPS  1.4901161193847656e-08

static double normcdf(double x) {
    return 0.5 * erfc(-x * INV_SQRT_2);
}

/*
 * erfcx(x) = erfc(x) * exp(x*x)
 * Scaled complementary error function. Not in standard C math library.
 *
 * Strategy:
 *   x >= 0, x < 25: direct exp(x^2)*erfc(x) (both representable)
 *   x >= 25: asymptotic series 1/(x*sqrt(pi)) * sum_{k} (-1)^k (2k-1)!!/(2x^2)^k
 *   x < 0: reflection identity erfcx(x) = 2*exp(x^2) - erfcx(-x)
 */
static double my_erfcx(double x) {
    if (x >= 0.0) {
        if (x < 25.0) {
            return exp(x * x) * erfc(x);
        } else {
            double ix2 = 0.5 / (x * x);
            double s = 1.0;
            double term = 1.0;
            int k;
            for (k = 1; k <= 25; k++) {
                term *= -(2 * k - 1) * ix2;
                double snew = s + term;
                if (snew == s) break;
                s = snew;
            }
            return s / (x * sqrt(M_PI));
        }
    } else {
        double ax = -x;
        if (ax < 25.0) {
            return 2.0 * exp(ax * ax) - my_erfcx(ax);
        } else {
            /* For very large |x| negative, erfcx ~ 2*exp(x^2).
             * exp(x^2) overflows beyond |x|~26.6. Return safe large value;
             * calling code multiplies by a compensating tiny normalization. */
            return 2.0e300;
        }
    }
}

double bs_price(int is_call, double K, double F, double totalvar, double df) {
    int sign = is_call ? 1 : -1;
    if (totalvar < MY_EPS) {
        double intr = sign * (F - K);
        return df * (intr > 0.0 ? intr : 0.0);
    }
    if (F < MY_EPS) {
        return is_call ? 0.0 : df * K;
    }
    if (K < MY_EPS) {
        return is_call ? df * F : 0.0;
    }
    double sv = sqrt(totalvar);
    double d1 = log(F / K) / sv + sv * 0.5;
    double d2 = d1 - sv;
    double nd1 = normcdf(sign * d1);
    double nd2 = normcdf(sign * d2);
    return sign * df * (F * nd1 - K * nd2);
}

/*
 * Normalize option price to an undiscounted call with ex = F/K <= 1.
 * Uses put-call parity and in-out duality to ensure the iteration
 * always works in a numerically favorable regime (OTM call).
 */
static void normalize_price(int is_call, double price, double F, double K,
                            double df, double *c_out, double *ex_out) {
    double c = price / (F * df);
    double ex = F / K;

    if (!is_call) {
        if (ex <= 1.0) {
            /* put-call parity: C = P + (F - K) undiscounted, normalized by F */
            c = c + 1.0 - 1.0 / ex;
        } else {
            /* in-out duality for puts with F > K */
            c = ex * c;
            ex = 1.0 / ex;
        }
    } else {
        if (ex > 1.0) {
            /* in-out duality for ITM calls: transform to OTM */
            c = ex * (c - 1.0) + 1.0;
            ex = 1.0 / ex;
        }
    }
    *c_out = c;
    *ex_out = ex;
}

/*
 * Stefanica-Radoicic initial approximation for scaled volatility v = sigma*sqrt(T).
 * Given normalized undiscounted call price, moneyness ratio ey = F/K,
 * and log-moneyness y = log(F/K).
 */
static double sr_initial_guess(double price, double ey, double y) {
    double alpha = price * ey;
    double r = 2.0 * alpha - ey + 1.0;
    double em2piy = exp(-TWO_OVER_PI * y);
    double tmp = ey * em2piy - 1.0 / (ey * em2piy);
    double A_val = tmp * tmp;
    double r2 = r * r;
    double eyem = ey * em2piy + 1.0 / (ey * em2piy);
    double B_val = 4.0 * (em2piy + 1.0 / em2piy)
                 - 2.0 / ey * eyem * (ey * ey + 1.0 - r2);

    double beta;
    double C_val;

    if (fabs(alpha) < SQRT_MY_EPS) {
        C_val = -16.0 * (1.0 - 1.0 / ey) * alpha
              - 16.0 * (1.0 - 3.0 / ey + 1.0 / (ey * ey)) * alpha * alpha;
        beta = (B_val != 0.0) ? C_val / B_val : SQRT_MY_EPS;
    } else if (fabs(ey - alpha) < SQRT_MY_EPS) {
        double diff = alpha - ey;
        C_val = -16.0 * (1.0 + 1.0 / ey) * diff
              - 16.0 * (1.0 + 3.0 / ey + 1.0 / (ey * ey)) * diff * diff;
        if (C_val == 0.0) {
            beta = (A_val != 0.0) ? B_val / A_val : SQRT_MY_EPS;
        } else {
            beta = (B_val != 0.0) ? C_val / B_val : SQRT_MY_EPS;
        }
    } else if (fabs(y) < SQRT_MY_EPS) {
        double a2 = alpha * alpha;
        double a4 = a2 * a2;
        C_val = 16.0 * ((a2 - a4)
                + (2.0 * a4 + 2.0 * alpha * a2 - a2 - alpha) * y);
        double B_loc = 16.0 * (a2 - y * (alpha + a2));
        beta = (B_loc != 0.0) ? C_val / B_loc : SQRT_MY_EPS;
    } else {
        double eym1 = ey - 1.0;
        double eyp1 = ey + 1.0;
        C_val = 1.0 / (ey * ey) * (r2 - eym1 * eym1) * (eyp1 * eyp1 - r2);
        double disc = B_val * B_val + 4.0 * A_val * C_val;
        if (disc < 0.0) disc = 0.0;
        beta = 2.0 * C_val / (B_val + sqrt(disc));
    }

    if (beta <= 0.0) beta = SQRT_MY_EPS;

    double gamma = -log(beta) / TWO_OVER_PI;

    if (y >= 0.0) {
        double em2_sq = em2piy * em2piy;
        double sq = 1.0 - em2_sq;
        double As = 0.5 * (1.0 + sqrt(sq > 0.0 ? sq : 0.0));
        double c0 = As - 0.5 / ey;
        double gmy = gamma - y;
        if (gmy < 0.0) gmy = 0.0;
        if (price <= c0) {
            return sqrt(gamma + y) - sqrt(gmy);
        }
        return sqrt(gamma + y) + sqrt(gmy);
    }

    double inv_em_sq = 1.0 / (em2piy * em2piy);
    double sq = 1.0 - inv_em_sq;
    double As = 0.5 * (1.0 - sqrt(sq > 0.0 ? sq : 0.0));
    double c0 = 0.5 - As / ey;
    double gpy = gamma + y;
    if (gpy < 0.0) gpy = 0.0;
    if (price <= c0) {
        return -sqrt(gpy) + sqrt(gamma - y);
    }
    return sqrt(gpy) + sqrt(gamma - y);
}

/*
 * Log-price objective function with first and second derivative ratios.
 * Uses erfcx-based computation to avoid underflow for deep OTM options.
 * Working in log-price space provides uniform cubic convergence across
 * all volatility regimes.
 */
static void objective_log(double x, double ex, double v, double logc,
                          double *fb, double *fb_over_fpb,
                          double *fp2b_over_fpb) {
    if (v < 1e-300) v = 1e-300;
    double h = x / v;
    double t = v * 0.5;

    double Np = my_erfcx(-(h + t) / SQRT_2);
    double Nm = my_erfcx(-(h - t) / SQRT_2);

    double diff = Np - Nm;
    if (diff <= 0.0) diff = 1e-300;

    double eh2t2 = exp(-(h * h + t * t) * 0.5);
    double norm = 0.5 / sqrt(ex) * eh2t2;
    double c_est = norm * diff;
    if (c_est <= 0.0) c_est = 1e-300;
    double log_c_est = log(c_est);

    double log_vega = (2.0 / sqrt(2.0 * M_PI)) / diff;
    double volga_over_vega = (h + t) * (h - t) / v;
    double log_volga_over_vega = volga_over_vega - log_vega;

    *fb = log_c_est - logc;
    *fb_over_fpb = *fb / log_vega;
    *fp2b_over_fpb = log_volga_over_vega;
}

double implied_vol(int is_call, double price, double F, double K,
                   double tte, double df) {
    double c, ex;
    normalize_price(is_call, price, F, K, df, &c, &ex);

    if (c <= 0.0) return MY_EPS;

    double upper = 1.0 / ex;
    if (upper > 1.0) upper = 1.0;
    if (c >= upper) return -1.0;

    double x = log(ex);
    double v = sr_initial_guess(c, ex, x);
    if (v <= 0.0) v = SQRT_MY_EPS;

    double logc = log(c);
    double xtolrel = 32.0 * MY_EPS;
    double ftolrel = MY_EPS;
    double ftol = (fabs(logc) > 1.0 ? fabs(logc) : 1.0) * ftolrel;

    double fb, fb_over_fpb, fp2b_over_fpb;
    objective_log(x, ex, v, logc, &fb, &fb_over_fpb, &fp2b_over_fpb);

    if (fabs(fb) < ftol) return v / sqrt(tte);

    int i;
    for (i = 0; i < 64; i++) {
        double v0 = v;
        double lf = fb_over_fpb * fp2b_over_fpb;
        /* Halley step: cubic convergence */
        double denom = 1.0 - lf * 0.5;
        if (fabs(denom) < 1e-300) denom = 1e-300;
        double step = -(1.0 / denom) * fb_over_fpb;
        double v1 = v0 + step;

        if (v1 <= 0.0) v1 = v0 * 0.5;

        objective_log(x, ex, v1, logc, &fb, &fb_over_fpb, &fp2b_over_fpb);
        v = v1;

        double xtol = (fabs(v) > 1.0 ? fabs(v) : 1.0) * xtolrel;
        if (fabs(v - v0) <= xtol || fabs(fb) <= ftol) break;
    }

    return v / sqrt(tte);
}
