/*
 * Q15/Q31 saturating fixed-point basic operators.
 * Derived from ITU-T/ETSI basicop2.c (3GPP TS 26.073).
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include "basicop.h"

Flag Overflow = 0;
Flag Carry    = 0;

/* ------------------------------------------------------------------ */
Word16 saturate(Word32 L_var1)
{
    Word16 var_out;
    if (L_var1 > 0x00007fffL) {
        Overflow = 1;
        var_out  = MAX_16;
    } else if (L_var1 < (Word32)0xffff8000L) {
        Overflow = 1;
        var_out  = MIN_16;
    } else {
        var_out = (Word16)L_var1;
    }
    return var_out;
}

/* ------------------------------------------------------------------ */
Word16 add(Word16 var1, Word16 var2)
{
    return saturate((Word32)var1 + var2);
}

/* ------------------------------------------------------------------ */
Word16 sub(Word16 var1, Word16 var2)
{
    return saturate((Word32)var1 - var2);
}

/* ------------------------------------------------------------------ */
Word16 abs_s(Word16 var1)
{
    if (var1 == MIN_16) return MAX_16;
    return (var1 < 0) ? -var1 : var1;
}

/* ------------------------------------------------------------------ */
Word16 shr(Word16 var1, Word16 var2)
{
    Word16 var_out;
    if (var2 < 0) {
        if (var2 < -16) var2 = -16;
        var_out = shl(var1, (Word16)(-var2));
    } else {
        if (var2 >= 15) {
            var_out = (var1 < 0) ? -1 : 0;
        } else {
            if (var1 < 0)
                var_out = (Word16)(~((~var1) >> var2));
            else
                var_out = (Word16)(var1 >> var2);
        }
    }
    return var_out;
}

/* ------------------------------------------------------------------ */
Word16 shl(Word16 var1, Word16 var2)
{
    Word16 var_out;
    Word32 result;

    if (var2 < 0) {
        if (var2 < -16) var2 = -16;
        var_out = shr(var1, (Word16)(-var2));
    } else {
        result = (Word32)var1 * ((Word32)1 << var2);
        if ((var2 > 15 && var1 != 0) ||
            (result != (Word32)((Word16)result))) {
            Overflow = 1;
            var_out  = (var1 > 0) ? MAX_16 : MIN_16;
        } else {
            var_out = (Word16)result;
        }
    }
    return var_out;
}

/* ------------------------------------------------------------------ */
Word16 mult(Word16 var1, Word16 var2)
{
    Word32 L_product;
    L_product = (Word32)var1 * (Word32)var2;
    L_product = (L_product & (Word32)0xffff8000L) >> 15;
    if (L_product & (Word32)0x00010000L)
        L_product = L_product | (Word32)0xffff0000L;
    return saturate(L_product);
}

/* ------------------------------------------------------------------ */
Word16 mult_r(Word16 var1, Word16 var2)
{
    Word32 L_product;
    L_product  = (Word32)var1 * (Word32)var2;
    L_product += (Word32)0x00004000L;
    L_product &= (Word32)0xffff8000L;
    L_product >>= 15;
    if (L_product & (Word32)0x00010000L)
        L_product |= (Word32)0xffff0000L;
    return saturate(L_product);
}

/* ------------------------------------------------------------------ */
Word32 L_mult(Word16 var1, Word16 var2)
{
    Word32 L_var_out;
    L_var_out = (Word32)var1 * (Word32)var2;

    if (L_var_out != (Word32)0x40000001L) {
        L_var_out *= 2;
    } else {
        Overflow  = 1;
        L_var_out = MAX_32;
    }
    return L_var_out;
}

/* ------------------------------------------------------------------ */
Word16 negate(Word16 var1)
{
    return (var1 == MIN_16) ? MAX_16 : (Word16)(-var1);
}

/* ------------------------------------------------------------------ */
Word16 extract_h(Word32 L_var1)
{
    return (Word16)(L_var1 >> 16);
}

/* ------------------------------------------------------------------ */
Word16 extract_l(Word32 L_var1)
{
    return (Word16)L_var1;
}

/* ------------------------------------------------------------------ */
/*
 * round_fx — ITU-T basic operator "round".
 * Rounds the lower 16 bits of a 32-bit value into the upper 16 bits
 * with midpoint-up rounding behavior.
 */
Word16 round_fx(Word32 L_var1)
{
    Word32 L_rounded;
    L_rounded = L_add(L_var1, (Word32)0x00000800L);
    return extract_h(L_rounded);
}

/* ------------------------------------------------------------------ */
Word32 L_mac(Word32 L_var3, Word16 var1, Word16 var2)
{
    return L_add(L_var3, L_mult(var1, var2));
}

/* ------------------------------------------------------------------ */
Word32 L_msu(Word32 L_var3, Word16 var1, Word16 var2)
{
    return L_sub(L_var3, L_mult(var1, var2));
}

/* ------------------------------------------------------------------ */
Word32 L_add(Word32 L_var1, Word32 L_var2)
{
    Word32 L_var_out;
    L_var_out = L_var1 + L_var2;
    if (((L_var1 ^ L_var2) & MIN_32) == 0) {
        if ((L_var_out ^ L_var1) & MIN_32) {
            L_var_out = (L_var1 < 0) ? MIN_32 : MAX_32;
            Overflow  = 1;
        }
    }
    return L_var_out;
}

/* ------------------------------------------------------------------ */
Word32 L_sub(Word32 L_var1, Word32 L_var2)
{
    Word32 L_var_out;
    L_var_out = L_var1 - L_var2;
    if (((L_var1 ^ L_var2) & MIN_32) != 0) {
        if ((L_var_out ^ L_var1) & MIN_32) {
            L_var_out = (L_var1 < 0L) ? MIN_32 : MAX_32;
            Overflow  = 1;
        }
    }
    return L_var_out;
}

/* ------------------------------------------------------------------ */
Word32 L_negate(Word32 L_var1)
{
    return (L_var1 == MIN_32) ? MAX_32 : -L_var1;
}

/* ------------------------------------------------------------------ */
Word32 L_shl(Word32 L_var1, Word16 var2)
{
    Word32 L_var_out = L_var1;
    if (var2 <= 0) {
        if (var2 < -32) var2 = -32;
        L_var_out = L_shr(L_var1, (Word16)(-var2));
    } else {
        for (; var2 > 0; var2--) {
            if (L_var1 > (Word32)0x3fffffffL) {
                Overflow  = 1;
                L_var_out = MAX_32;
                break;
            } else if (L_var1 < (Word32)0xc0000000L) {
                Overflow  = 1;
                L_var_out = MIN_32;
                break;
            }
            L_var1   *= 2;
            L_var_out = L_var1;
        }
    }
    return L_var_out;
}

/* ------------------------------------------------------------------ */
Word32 L_shr(Word32 L_var1, Word16 var2)
{
    Word32 L_var_out;
    if (var2 < 0) {
        if (var2 < -32) var2 = -32;
        L_var_out = L_shl(L_var1, (Word16)(-var2));
    } else {
        if (var2 >= 31) {
            L_var_out = (L_var1 < 0L) ? -1 : 0;
        } else {
            if (L_var1 < 0)
                L_var_out = ~((~L_var1) >> var2);
            else
                L_var_out = L_var1 >> var2;
        }
    }
    return L_var_out;
}

/* ------------------------------------------------------------------ */
Word32 L_abs(Word32 L_var1)
{
    if (L_var1 == MIN_32) return MAX_32;
    return (L_var1 < 0) ? -L_var1 : L_var1;
}

/* ------------------------------------------------------------------ */
Word32 L_deposit_h(Word16 var1)
{
    return (Word32)var1 << 16;
}

/* ------------------------------------------------------------------ */
Word32 L_deposit_l(Word16 var1)
{
    return (Word32)var1;
}

/* ------------------------------------------------------------------ */
Word16 norm_s(Word16 var1)
{
    Word16 var_out;
    if (var1 == 0) return 0;
    if (var1 == (Word16)0xffff) return 15;
    if (var1 < 0) var1 = ~var1;
    for (var_out = 0; var1 < 0x4000; var_out++)
        var1 <<= 1;
    return var_out;
}

/* ------------------------------------------------------------------ */
Word16 norm_l(Word32 L_var1)
{
    Word16 var_out;
    if (L_var1 == 0) return 0;
    if (L_var1 == (Word32)0xffffffffL) return 31;
    if (L_var1 < 0) L_var1 = ~L_var1;
    for (var_out = 0; L_var1 < (Word32)0x20000000L; var_out++)
        L_var1 <<= 1;
    return var_out;
}

/* ------------------------------------------------------------------ */
Word16 div_s(Word16 var1, Word16 var2)
{
    Word16 var_out = 0;
    Word16 iteration;
    Word32 L_num, L_denom;

    if ((var1 > var2) || (var1 < 0) || (var2 < 0)) {
        fprintf(stderr, "Division Error var1=%d var2=%d\n", var1, var2);
        abort();
    }
    if (var2 == 0) {
        fprintf(stderr, "Division by 0, Fatal error\n");
        abort();
    }
    if (var1 == 0)   return 0;
    if (var1 == var2) return MAX_16;

    L_num   = (Word32)var1;
    L_denom = (Word32)var2;
    for (iteration = 0; iteration < 15; iteration++) {
        var_out <<= 1;
        L_num   <<= 1;
        if (L_num >= L_denom) {
            L_num  -= L_denom;
            var_out = (Word16)(var_out + 1);
        }
    }
    return var_out;
}
