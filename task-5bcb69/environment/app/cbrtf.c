/* Skeleton for correctly-rounded cube root (IEEE 754 binary32).
 *
 * Special cases are handled. The core numerical algorithm that computes
 * correctly-rounded cube roots for normal and subnormal inputs is
 * unimplemented — you must write it.
 *
 */

#include <stdint.h>
#include "cbrtf.h"

typedef union { float f; uint32_t u; } b32u32_u;
typedef union { double f; uint64_t u; } b64u64_u;

float cr_cbrtf(float x) {
    b32u32_u xi = {.f = x};
    uint32_t hx = xi.u;
    uint32_t sign = hx & 0x80000000u;
    hx &= 0x7fffffffu;

    /* +-0 -> return with sign preserved */
    if (hx == 0u)
        return x;

    /* NaN or Inf: x + x returns Inf unchanged and quiets sNaN */
    if (hx >= 0x7f800000u)
        return x + x;

    /* TODO: Implement the correctly-rounded cube root for all normal and
     * subnormal binary32 inputs. The result must match MPFR's mpfr_cbrt
     * with MPFR_RNDN for every representable float.
     *
     * Double-precision intermediate arithmetic is available via b64u64_u.
     */

    return 0.0f; /* placeholder — replace with your implementation */
}
