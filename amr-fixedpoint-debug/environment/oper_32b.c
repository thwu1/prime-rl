/*
 * Double-precision format (DPF) operations for AMR-NB codec.
 * Derived from oper_32b.c (3GPP TS 26.073).
 *
 */

#include "basicop.h"
#include "oper_32b.h"

/* ------------------------------------------------------------------ *
 *  L_Extract — split a 32-bit integer into DPF (hi, lo).             *
 * ------------------------------------------------------------------ */
void L_Extract(Word32 L_32, Word16 *hi, Word16 *lo)
{
    *hi = extract_h(L_32);
    *lo = extract_l(L_msu(L_shr(L_32, 1), *hi, 16384));
}

/* ------------------------------------------------------------------ *
 *  L_Comp — compose a 32-bit integer from DPF (hi, lo).              *
 * ------------------------------------------------------------------ */
Word32 L_Comp(Word16 hi, Word16 lo)
{
    Word32 L_32;
    L_32 = L_deposit_h(hi);
    return L_mac(L_32, lo, 1);
}

/* ------------------------------------------------------------------ *
 *  Mpy_32 — multiply two DPF numbers.                                *
 * ------------------------------------------------------------------ */
Word32 Mpy_32(Word16 hi1, Word16 lo1, Word16 hi2, Word16 lo2)
{
    Word32 L_32;
    L_32 = L_mult(hi1, hi2);
    L_32 = L_mac(L_32, mult(hi1, lo2), 1);
    return L_32;
}

/* ------------------------------------------------------------------ *
 *  Mpy_32_16 — multiply a DPF number by a 16-bit integer.            *
 * ------------------------------------------------------------------ */
Word32 Mpy_32_16(Word16 hi, Word16 lo, Word16 n)
{
    Word32 L_32;
    L_32 = L_mult(hi, n);
    L_32 = L_mac(L_32, mult(lo, n), 1);
    return L_32;
}

/* ------------------------------------------------------------------ *
 *  Div_32 — fractional integer division of two DPF numbers.           *
 * ------------------------------------------------------------------ */
Word32 Div_32(Word32 L_num, Word16 denom_hi, Word16 denom_lo)
{
    Word16 approx, hi, lo, n_hi, n_lo;
    Word32 L_32;

    approx = div_s((Word16)0x3fff, denom_hi);

    L_32 = Mpy_32_16(denom_hi, denom_lo, approx);
    L_32 = L_sub((Word32)0x7fffffffL, L_32);
    L_Extract(L_32, &hi, &lo);
    L_32 = Mpy_32_16(hi, lo, approx);

    L_Extract(L_32, &hi, &lo);
    L_Extract(L_num, &n_hi, &n_lo);
    L_32 = Mpy_32(n_hi, n_lo, hi, lo);
    L_32 = L_shl(L_32, 2);

    return L_32;
}
