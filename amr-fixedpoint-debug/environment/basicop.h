/*
 * Q15/Q31 saturating fixed-point basic operators.
 * Derived from ITU-T/ETSI basic_op.h (3GPP TS 26.073).
 *
 */

#ifndef BASICOP_H
#define BASICOP_H

typedef short Word16;
typedef int   Word32;
typedef int   Flag;

#define MAX_16  (Word16)32767
#define MIN_16  (Word16)(-32768)
#define MAX_32  (Word32)0x7fffffffL
#define MIN_32  (Word32)(-2147483647L - 1)

extern Flag Overflow;
extern Flag Carry;

/* --- 16-bit operators --- */
Word16 saturate(Word32 L_var1);
Word16 add(Word16 var1, Word16 var2);
Word16 sub(Word16 var1, Word16 var2);
Word16 abs_s(Word16 var1);
Word16 shl(Word16 var1, Word16 var2);
Word16 shr(Word16 var1, Word16 var2);
Word16 mult(Word16 var1, Word16 var2);
Word16 mult_r(Word16 var1, Word16 var2);
Word16 negate(Word16 var1);
Word16 norm_s(Word16 var1);
Word16 div_s(Word16 var1, Word16 var2);

/* --- 32-bit operators --- */
Word32 L_mult(Word16 var1, Word16 var2);
Word32 L_mac(Word32 L_var3, Word16 var1, Word16 var2);
Word32 L_msu(Word32 L_var3, Word16 var1, Word16 var2);
Word32 L_add(Word32 L_var1, Word32 L_var2);
Word32 L_sub(Word32 L_var1, Word32 L_var2);
Word32 L_negate(Word32 L_var1);
Word32 L_shl(Word32 L_var1, Word16 var2);
Word32 L_shr(Word32 L_var1, Word16 var2);
Word32 L_abs(Word32 L_var1);
Word32 L_deposit_h(Word16 var1);
Word32 L_deposit_l(Word16 var1);
Word16 extract_h(Word32 L_var1);
Word16 extract_l(Word32 L_var1);
Word16 norm_l(Word32 L_var1);

/*
 * ITU-T 'round' operator — renamed to round_fx to avoid
 * collision with C99/C11 math.h round().
 */
Word16 round_fx(Word32 L_var1);

/* WMOPS counting macros (no-op stubs) */
#define test()
#define move16()
#define move32()
#define logic16()

#endif /* BASICOP_H */
