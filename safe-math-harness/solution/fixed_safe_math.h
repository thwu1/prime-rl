/*
 * safe_math.h - Safe integer arithmetic wrappers for int32_t
 *
 * Each function wraps an arithmetic operation to avoid C undefined behavior.
 * If the operation would invoke UB, the function returns 0 instead.
 *
 */

#ifndef SAFE_MATH_H
#define SAFE_MATH_H

#include <stdint.h>
#include <limits.h>

/*
 * Safe addition: returns a + b, or 0 on overflow.
 */
static inline int32_t safe_add_int32_t(int32_t a, int32_t b) {
    if ((b > 0 && a > INT32_MAX - b) || (b < 0 && a < INT32_MIN - b))
        return 0;
    return a + b;
}

/*
 * Safe subtraction: returns a - b, or 0 on overflow.
 *
 * FIX: use (INT32_MAX + b) instead of (INT32_MAX - (-b)) to avoid
 * UB when b == INT32_MIN (negating INT32_MIN is undefined).
 */
static inline int32_t safe_sub_int32_t(int32_t a, int32_t b) {
    if ((b > 0 && a < INT32_MIN + b) || (b < 0 && a > INT32_MAX + b))
        return 0;
    return a - b;
}

/*
 * Safe multiplication: returns a * b, or 0 on overflow.
 *
 * FIX: check BEFORE multiplying to avoid UB.  The old version
 * computed a*b first (UB on overflow) then tried to verify.
 */
static inline int32_t safe_mul_int32_t(int32_t a, int32_t b) {
    if (a > 0) {
        if (b > 0) {
            if (a > INT32_MAX / b) return 0;
        } else if (b < 0) {
            if (b < INT32_MIN / a) return 0;
        }
    } else if (a < 0) {
        if (b > 0) {
            if (a < INT32_MIN / b) return 0;
        } else if (b < 0) {
            if (b < INT32_MAX / a) return 0;
        }
    }
    return a * b;
}

/*
 * Safe division: returns a / b, or 0 on division by zero or overflow.
 *
 * FIX: added check for INT32_MIN / -1, which overflows because
 * the result (INT32_MAX + 1) is not representable as int32_t.
 */
static inline int32_t safe_div_int32_t(int32_t a, int32_t b) {
    if (b == 0 || (a == INT32_MIN && b == -1))
        return 0;
    return a / b;
}

/*
 * Safe modulo: returns a % b, or 0 on division by zero or overflow.
 *
 * FIX: added check for INT32_MIN % -1, which invokes UB because
 * it requires computing INT32_MIN / -1 internally.
 */
static inline int32_t safe_mod_int32_t(int32_t a, int32_t b) {
    if (b == 0 || (a == INT32_MIN && b == -1))
        return 0;
    return a % b;
}

/*
 * Safe left shift: returns a << b, or 0 on invalid shift.
 *
 * FIX: In C11, left-shifting a negative signed value is UB.
 * Also, the result a * 2^b must be representable in int32_t.
 * Added checks for a < 0 and for result overflow.
 */
static inline int32_t safe_lshift_int32_t(int32_t a, int b) {
    if (b < 0 || b >= 32 || a < 0)
        return 0;
    if (b > 0 && a > (INT32_MAX >> b))
        return 0;
    return a << b;
}

/*
 * Safe arithmetic right shift: returns a >> b, or 0 on invalid shift.
 * Uses unsigned shift for portability (avoids implementation-defined
 * behavior of right-shifting negative signed values).
 */
static inline int32_t safe_rshift_int32_t(int32_t a, int b) {
    if (b < 0 || b >= 32)
        return 0;
    return (int32_t)((uint32_t)a >> b);
}

/*
 * Safe unary negation: returns -a, or 0 on overflow.
 *
 * FIX: -INT32_MIN is UB because the result (2^31) is not
 * representable as int32_t.  Added explicit check.
 */
static inline int32_t safe_neg_int32_t(int32_t a) {
    if (a == INT32_MIN)
        return 0;
    return -a;
}

#endif /* SAFE_MATH_H */
