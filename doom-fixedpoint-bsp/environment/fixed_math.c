/*
 * Fixed-point 16.16 arithmetic implementation.
 * FixedMul uses 64-bit intermediate to avoid overflow.
 * FixedDiv detects potential overflow and returns saturated values.
 */


#include <stdlib.h>
#include <limits.h>
#include "fixed_math.h"

fixed_t FixedMul(fixed_t a, fixed_t b)
{
    return (fixed_t)(((int64_t)a * (int64_t)b) >> FRACBITS);
}

fixed_t FixedDiv(fixed_t a, fixed_t b)
{
    if ((abs(a) >> 15) >= abs(b))
    {
        return (a ^ b) < 0 ? INT_MAX : INT_MIN;
    }
    else
    {
        int64_t result = ((int64_t)a << FRACBITS) / b;
        return (fixed_t)result;
    }
}
