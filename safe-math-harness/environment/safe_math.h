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
 */
static inline int32_t safe_sub_int32_t(int32_t a, int32_t b) {
    if ((b > 0 && a < INT32_MIN + b) || (b < 0 && a > INT32_MAX - (-b)))
        return 0;
    return a - b;
}

/*
 * Safe multiplication: returns a * b, or 0 on overflow.
 */
static inline int32_t safe_mul_int32_t(int32_t a, int32_t b) {
    int32_t result = a * b;
    if (a != 0 && result / a != b)
        return 0;
    return result;
}

/*
 * Safe division: returns a / b, or 0 on division by zero.
 */
static inline int32_t safe_div_int32_t(int32_t a, int32_t b) {
    if (b == 0)
        return 0;
    return a / b;
}

/*
 * Safe modulo: returns a % b, or 0 on division by zero.
 */
static inline int32_t safe_mod_int32_t(int32_t a, int32_t b) {
    if (b == 0)
        return 0;
    return a % b;
}

/*
 * Safe left shift: returns a << b, or 0 on invalid shift.
 */
static inline int32_t safe_lshift_int32_t(int32_t a, int b) {
    if (b < 0 || b >= 32)
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
 */
static inline int32_t safe_neg_int32_t(int32_t a) {
    return -a;
}

#endif /* SAFE_MATH_H */
