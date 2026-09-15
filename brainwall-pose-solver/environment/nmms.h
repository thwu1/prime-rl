#ifndef NMMS_H
#define NMMS_H

/*
 * NMMS Binary Format Definitions
 * See spec.md for the full Nanobot Matter Manipulation System specification.
 *
 */

#include <stdint.h>

/* Command single-byte opcodes */
#define CMD_HALT    0xFF
#define CMD_WAIT    0xFE
#define CMD_FLIP    0xFD

/* Command type masks (applied to low nibble / low 3 bits) */
#define CMD_SMOVE_LOW4  0x04
#define CMD_LMOVE_LOW4  0x0C
#define CMD_LOW3_MASK   0x07
#define CMD_FUSIONP     0x07
#define CMD_FUSIONS     0x06
#define CMD_FISSION     0x05
#define CMD_FILL        0x03

/* Axis encoding for linear coordinate differences: 01=x, 10=y, 11=z */
#define AXIS_X  1
#define AXIS_Y  2
#define AXIS_Z  3

/* Near coordinate difference (nd) encoding/decoding macros.
 * nd = (dx+1)*9 + (dy+1)*3 + (dz+1)
 */
#define ND_ENCODE(dx, dy, dz)  (((dx)+1)*9 + ((dy)+1)*3 + ((dz)+1))
#define ND_DX(v)  (((v) / 9) - 1)
#define ND_DY(v)  ((((v) / 3) % 3) - 1)
#define ND_DZ(v)  (((v) % 3) - 1)

/* Linear coordinate difference decoding.
 * Long (lld): 5-bit field, component = i - 15
 * Short (sld): 4-bit field, component = i - 5
 */
#define LLD_DECODE(i)  ((int)(i) - 15)
#define SLD_DECODE(i)  ((int)(i) - 5)

/* Model file layout:
 *   Byte 0: resolution R (uint8)
 *   Bytes 1..ceil(R^3/8): bit array of voxel states
 *   Bit index for coordinate (x,y,z) = x*R*R + y*R + z
 *   Within each byte, bit 0 is least significant.
 */

/* Limits */
#define MAX_RESOLUTION 250
#define MAX_BOTS       20

#endif /* NMMS_H */
