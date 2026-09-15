
#ifndef CBRTF_H
#define CBRTF_H

/*
 * Correctly-rounded cube root for IEEE 754 binary32 (single-precision float).
 *
 * Returns the float value nearest to the exact mathematical cbrt(x),
 * using IEEE 754 round-to-nearest-even tie-breaking.
 *
 * Required behavior:
 *   cr_cbrtf(+0)   = +0
 *   cr_cbrtf(-0)   = -0
 *   cr_cbrtf(+Inf) = +Inf
 *   cr_cbrtf(-Inf) = -Inf
 *   cr_cbrtf(NaN)  = NaN
 *   cr_cbrtf(-x)   = -cr_cbrtf(x)  for all x
 */
float cr_cbrtf(float x);

#endif /* CBRTF_H */
