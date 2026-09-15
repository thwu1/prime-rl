#ifndef FIXPOINT_H
#define FIXPOINT_H

/*
 * Q16.16 fixed-point arithmetic header.
 * All values are stored as int32_t with 16 fractional bits.
 *
 */

#include <stdint.h>

typedef int32_t fix16_t;

#define FIX16_ONE       ((fix16_t)0x00010000)
#define FIX16_HALF      ((fix16_t)0x00008000)
#define FIX16_MAX       ((fix16_t)0x7FFFFFFF)
#define FIX16_MIN       ((fix16_t)0x80000000)
#define FIX16_OVERFLOW  ((fix16_t)0x80000000)

/* Conversion macros */
#define FIX16_FROM_INT(x)    ((fix16_t)((int32_t)(x) << 16))
#define FIX16_TO_FLOAT(x)    ((double)(x) / 65536.0)

/* Compile-time constant from double literal */
#define FIX16_CONST(x) ((fix16_t)(((x) >= 0) ? ((x) * 65536.0 + 0.5) : ((x) * 65536.0 - 0.5)))

/* --- Arithmetic functions (to be implemented in pid_controller.c) --- */

/*
 * Saturating addition: returns a + b, clamped to [FIX16_MIN, FIX16_MAX]
 * on overflow.
 */
static inline fix16_t fix16_sadd(fix16_t a, fix16_t b)
{
    int64_t sum = (int64_t)a + (int64_t)b;
    if (sum > FIX16_MAX) return FIX16_MAX;
    if (sum < FIX16_MIN) return FIX16_MIN;
    return (fix16_t)sum;
}

/*
 * Saturating subtraction: returns a - b, clamped on overflow.
 */
static inline fix16_t fix16_ssub(fix16_t a, fix16_t b)
{
    int64_t diff = (int64_t)a - (int64_t)b;
    if (diff > FIX16_MAX) return FIX16_MAX;
    if (diff < FIX16_MIN) return FIX16_MIN;
    return (fix16_t)diff;
}

/*
 * Saturating multiplication: returns (a * b) >> 16, with rounding
 * and saturation on overflow.
 */
static inline fix16_t fix16_smul(fix16_t a, fix16_t b)
{
    int64_t product = (int64_t)a * (int64_t)b;
    /* Round to nearest */
    product += FIX16_HALF;
    fix16_t result = (fix16_t)(product >> 16);
    /* Check overflow: upper 17 bits should all be the same */
    int64_t upper = product >> 47;
    if (product >= 0) {
        if (upper) return FIX16_MAX;
    } else {
        product--; /* adjust for negative rounding */
        result = (fix16_t)(product >> 16);
        if (~upper) return FIX16_MIN;
    }
    return result;
}

/*
 * Saturating division: returns (a << 16) / b, with saturation.
 */
static inline fix16_t fix16_sdiv(fix16_t a, fix16_t b)
{
    if (b == 0) return (a >= 0) ? FIX16_MAX : FIX16_MIN;
    int64_t num = ((int64_t)a) << 16;
    int64_t result = num / (int64_t)b;
    /* Round to nearest */
    int64_t rem = num % (int64_t)b;
    if (rem != 0) {
        if ((rem > 0) == (b > 0))
            result += (2 * ((rem > 0) ? rem : -rem) >= ((b > 0) ? b : -b)) ? 1 : 0;
        else
            result -= (2 * ((rem > 0) ? rem : -rem) >= ((b > 0) ? b : -b)) ? 1 : 0;
    }
    if (result > FIX16_MAX) return FIX16_MAX;
    if (result < FIX16_MIN) return FIX16_MIN;
    return (fix16_t)result;
}

/*
 * Clamp x to [lo, hi].
 */
static inline fix16_t fix16_clamp(fix16_t x, fix16_t lo, fix16_t hi)
{
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

#endif /* FIXPOINT_H */
