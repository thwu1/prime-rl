/*
 * mseedformat.h - miniSEED v3 format specification reference
 *
 * Based on the FDSN miniSEED 3 specification and the EarthScope
 * libmseed implementation (Apache 2.0 license).
 *
 */

#ifndef MSEEDFORMAT_H
#define MSEEDFORMAT_H

#include <stdint.h>

/*======================================================================
 * miniSEED 3 Fixed Section of Data Header (40 bytes minimum)
 *
 * All multi-byte fields are little-endian.
 *
 * Offset  Length  Type        Field
 * ------  ------  ----------  ------------------------------------------
 *  0       2      char[2]     Record indicator ('M','S')
 *  2       1      uint8       Format version (3)
 *  3       1      uint8       Flags
 *  4       4      uint32_LE   Nanosecond (0-999999999)
 *  8       2      uint16_LE   Year
 * 10       2      uint16_LE   Day of year (1-366)
 * 12       1      uint8       Hour (0-23)
 * 13       1      uint8       Minute (0-59)
 * 14       1      uint8       Second (0-60, 60 for leap second)
 * 15       1      uint8       Data encoding (see DE_* constants below)
 * 16       8      float64_LE  Sample rate (Hz)
 * 24       4      uint32_LE   Number of samples
 * 28       4      uint32_LE   CRC-32C of entire record (see below)
 * 32       1      uint8       Publication version
 * 33       1      uint8       Length of source identifier in bytes
 * 34       2      uint16_LE   Length of extra headers in bytes
 * 36       4      uint32_LE   Length of data payload in bytes
 *
 * Immediately following the 40-byte fixed header:
 *   [field 33] bytes: source identifier (e.g. "FDSN:XX_TEST_00_B_H_Z")
 *   [field 34] bytes: extra headers (JSON, may be 0)
 *   [field 36] bytes: data payload (Steim2-encoded frames, etc.)
 *
 * CRC-32C Computation
 * -------------------
 * The CRC-32C (Castagnoli) checksum is computed over the COMPLETE
 * record with bytes 28-31 (the CRC field) set to zero.
 *
 * Algorithm:
 *   Polynomial (reflected): 0x82F63B78
 *   Initial value:          0xFFFFFFFF
 *   Final XOR:              0xFFFFFFFF
 *   Bit-by-bit reflected:   for each byte, XOR into CRC low byte,
 *     then for 8 iterations: if LSB set, shift right and XOR poly;
 *     otherwise shift right.
 *====================================================================*/

/* Fixed header length in bytes */
#define MS3_FSDH_LEN   40

/* Data encoding type constants */
#define DE_TEXT         0
#define DE_INT16        1
#define DE_INT24        2
#define DE_INT32        3
#define DE_FLOAT32      4
#define DE_FLOAT64      5
#define DE_STEIM1      10
#define DE_STEIM2      11

/*======================================================================
 * Steim2 Compression Frame Format
 *
 * Each frame is 64 bytes = 16 x 32-bit words (little-endian on disk).
 *
 * CONTROL WORD (word 0)
 * ---------------------
 * Word 0 contains 16 two-bit "nibble" codes, one per word in the frame.
 * The nibble for word W occupies bits (31 - 2*W) downto (30 - 2*W).
 *
 *   nibble = 00  Non-data / header word (skip)
 *   nibble = 01  4 x 8-bit differences (byte-level)
 *   nibble = 10  Consult dnib (bits 31-30 of data word) for subtype
 *   nibble = 11  Consult dnib (bits 31-30 of data word) for subtype
 *
 * FRAME 0 SPECIAL WORDS
 * ---------------------
 *   Word 1: X0 - forward integration constant (first sample, int32)
 *   Word 2: Xn - reverse integration constant (last sample, int32)
 *   Data words start at word 3.  Words 1 and 2 have nibble = 00.
 *
 * OTHER FRAMES
 * ---------------------
 *   Data words start at word 1.
 *
 * DECODE NIBBLE (dnib) SUBTYPES
 * ---------------------
 * When nibble = 10:
 *   dnib = 01  ->  1 x 30-bit difference  (bits 29-0)
 *   dnib = 10  ->  2 x 15-bit differences (d0 at bits 29-15, d1 at 14-0)
 *   dnib = 11  ->  3 x 10-bit differences (d0 at 29-20, d1 at 19-10, d2 at 9-0)
 *
 * When nibble = 11:
 *   dnib = 00  ->  5 x 6-bit differences (d0 at 29-24, d1 at 23-18, d2 at 17-12, d3 at 11-6, d4 at 5-0)
 *   dnib = 01  ->  6 x 5-bit differences (d0 at 29-25, d1 at 24-20, d2 at 19-15, d3 at 14-10, d4 at 9-5, d5 at 4-0)
 *   dnib = 10  ->  7 x 4-bit differences (d0 at 27-24, d1 at 23-20, d2 at 19-16, d3 at 15-12, d4 at 11-8, d5 at 7-4, d6 at 3-0)
 *
 * PACKING ORDER
 * ---------------------
 * All differences are signed two's complement.  Mask each difference
 * to the correct bit width before packing into the word.
 *
 * Within each word, difference d0 (earliest in time) occupies the
 * HIGHEST bit positions and the last difference occupies the LOWEST.
 *
 *   Mode        Nibble  Dnib  N  Bits   Bit positions (d0 first)
 *   ----------  ------  ----  -  ----   ----------------------------------
 *   7 x 4-bit   11      10    7    4    27-24, 23-20, 19-16, 15-12, 11-8, 7-4, 3-0
 *   6 x 5-bit   11      01    6    5    29-25, 24-20, 19-15, 14-10, 9-5, 4-0
 *   5 x 6-bit   11      00    5    6    29-24, 23-18, 17-12, 11-6, 5-0
 *   4 x 8-bit   01      --    4    8    bytes: byte0=d0, byte1=d1, byte2=d2, byte3=d3
 *   3 x 10-bit  10      11    3   10    29-20, 19-10, 9-0
 *   2 x 15-bit  10      10    2   15    29-15, 14-0
 *   1 x 30-bit  10      01    1   30    29-0
 *
 * The encoder should try modes from most dense (7x4) to least dense
 * (1x30) and use the first mode for which all differences fit.
 *====================================================================*/

#endif /* MSEEDFORMAT_H */
