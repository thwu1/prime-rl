/*
 * posit16.h — Posit16 arithmetic library interface
 *
 * Posit16: 16-bit posit with es=1 (1 exponent bit, useed=4)
 *
 */

#ifndef POSIT16_H
#define POSIT16_H

#include <stdint.h>
#include <stdbool.h>

typedef struct { uint16_t v; } posit16_t;

/*
 * Quire16: 128-bit two's complement fixed-point accumulator.
 * v[0] is the high 64-bit word, v[1] is the low 64-bit word.
 * The radix point sits between logical bit positions 71 and 72,
 * where bit 0 = MSB of v[0] and bit 127 = LSB of v[1].
 */
typedef struct { uint64_t v[2]; } quire16_t;

/* Conversion */
double p16_to_f64(posit16_t a);

/* Arithmetic */
posit16_t p16_add(posit16_t a, posit16_t b);
posit16_t p16_sub(posit16_t a, posit16_t b);
posit16_t p16_mul(posit16_t a, posit16_t b);
posit16_t p16_div(posit16_t a, posit16_t b);

/* Quire operations */
quire16_t q16_clr(void);
quire16_t q16_fdp_add(quire16_t q, posit16_t a, posit16_t b);
posit16_t q16_to_p16(quire16_t q);

/* Special values */
#define P16_ZERO ((posit16_t){0x0000})
#define P16_NAR  ((posit16_t){0x8000})

static inline bool p16_is_nar(posit16_t a) { return a.v == 0x8000; }
static inline bool p16_is_zero(posit16_t a) { return a.v == 0; }

#endif /* POSIT16_H */
