/*
 * Fixed-point arithmetic for 16.16 representation.
 * Matches Doom engine's exact integer semantics.
 */


#ifndef FIXED_MATH_H
#define FIXED_MATH_H

#include <stdint.h>

#define FRACBITS  16
#define FRACUNIT  (1 << FRACBITS)

typedef int32_t   fixed_t;
typedef uint32_t  angle_t;

#define ANG45   0x20000000u
#define ANG90   0x40000000u
#define ANG180  0x80000000u
#define ANG270  0xC0000000u

fixed_t FixedMul(fixed_t a, fixed_t b);
fixed_t FixedDiv(fixed_t a, fixed_t b);

#endif /* FIXED_MATH_H */
