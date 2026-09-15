/*
 * Doom engine arithmetic primitives - header
 * 16.16 fixed-point math, WAD lump name hashing,
 * BSP partition side test, angle computation.
 */

#ifndef DOOM_MATH_H
#define DOOM_MATH_H

#include <stdint.h>
#include <limits.h>

/* 16.16 fixed-point representation */
#define FRACBITS    16
#define FRACUNIT    (1 << FRACBITS)

typedef int fixed_t;
typedef unsigned int angle_t;

/* Binary Angle Measurement constants */
#define ANG45   0x20000000u
#define ANG90   0x40000000u
#define ANG180  0x80000000u
#define ANG270  0xc0000000u

/* Slope division constants */
#define SLOPERANGE  2048
#define SLOPEBITS   11
#define DBITS       (FRACBITS - SLOPEBITS)

/* Function prototypes */
fixed_t FixedMul(fixed_t a, fixed_t b);
fixed_t FixedDiv(fixed_t a, fixed_t b);
unsigned int W_LumpNameHash(const char *s);
int SlopeDiv(unsigned int num, unsigned int den);
int R_PointOnSide(fixed_t x, fixed_t y,
                  fixed_t node_x, fixed_t node_y,
                  fixed_t node_dx, fixed_t node_dy);
angle_t R_PointToAngle2(fixed_t x1, fixed_t y1,
                        fixed_t x2, fixed_t y2);

#endif /* DOOM_MATH_H */
