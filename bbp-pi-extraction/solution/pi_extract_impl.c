/*
 * Bailey-Borwein-Plouffe hex digit extraction for pi.
 *
 *
 * pi = sum_{k=0}^{inf} 1/16^k * (4/(8k+1) - 2/(8k+4) - 1/(8k+5) - 1/(8k+6))
 *
 * To extract hex digit at position d, compute {16^d * pi} where {x}
 * denotes the fractional part.  Each of the four sub-series S_j (for
 * j = 1, 4, 5, 6) is evaluated independently by splitting into:
 *   - a finite modular sum  (k = 0 .. d)
 *   - an infinite tail       (k = d+1 .. inf, converges rapidly)
 */

#include "pi_extract.h"
#include <math.h>

/*
 * Compute 16^p mod m via binary modular exponentiation.
 *
 * All arithmetic uses double precision.  This is correct when
 * m < 2^{26.5} because intermediate products (< m^2) fit in the
 * 53-bit double mantissa.  For the BBP algorithm, m = 8k+j with
 * k <= d, so the constraint is easily satisfied for d up to ~10^7.
 */
static double mod_pow16(long p, double m)
{
    double r, b;

    if (m == 1.0)
        return 0.0;

    r = 1.0;
    b = fmod(16.0, m);

    while (p > 0) {
        if (p & 1)
            r = fmod(r * b, m);
        p >>= 1;
        if (p > 0)
            b = fmod(b * b, m);
    }
    return r;
}

/*
 * Compute {16^d * S_j} where S_j = sum_{k=0}^{inf} 1 / (16^k * (8k+j))
 * and {x} = x - floor(x) is the fractional part.
 */
static double series(int j, long d)
{
    double s, ak, t;
    long k;

    s = 0.0;

    /* --- Finite part: k = 0 .. d --- */
    for (k = 0; k <= d; k++) {
        ak = (double)(8 * k + j);
        t  = mod_pow16(d - k, ak) / ak;
        s += t;
        s -= floor(s);            /* keep only fractional part */
    }

    /* --- Tail: k = d+1, d+2, ... (terms shrink geometrically) --- */
    for (k = d + 1; ; k++) {
        ak = (double)(8 * k + j);
        t  = pow(16.0, (double)(d - k)) / ak;
        if (t < 1e-17)
            break;
        s += t;
        s -= floor(s);
    }

    return s;
}

int pi_hex_digit(long d)
{
    double s1, s4, s5, s6, pid;

    s1 = series(1, d);
    s4 = series(4, d);
    s5 = series(5, d);
    s6 = series(6, d);

    pid = 4.0 * s1 - 2.0 * s4 - s5 - s6;

    /* Normalize to [0, 1) */
    pid = fmod(pid, 1.0);
    if (pid < 0.0)
        pid += 1.0;

    return (int)(pid * 16.0);
}
