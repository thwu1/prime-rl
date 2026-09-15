#ifndef EXP2M1F_H
#define EXP2M1F_H

/* Correctly-rounded 2^x - 1 for IEEE 754 binary32 (float).
 * Round-to-nearest-even.
 *
 * Special cases:
 *   cr_exp2m1f(+0)   = +0
 *   cr_exp2m1f(-0)   = -0
 *   cr_exp2m1f(+Inf) = +Inf
 *   cr_exp2m1f(-Inf) = -1
 *   cr_exp2m1f(NaN)  = NaN
 *
 * This function must NOT call any libm functions (exp, log, sqrt, etc.).
 * Only basic arithmetic, bit manipulation, and compiler builtins
 * (__builtin_fma, __builtin_fmaf, __builtin_expect) are allowed.
 */
float cr_exp2m1f(float x);

#endif
