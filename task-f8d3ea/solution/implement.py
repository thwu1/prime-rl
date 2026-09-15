#!/usr/bin/env python3
"""
Complete the implementation of mseed3pack.c:

1. Implement CRC-32C (Castagnoli) computation
2. Implement 6 missing Steim2 packing modes (7x4, 6x5, 5x6, 4x8, 3x10, 2x15)
3. Fix X0/Xn integration constant positions (swapped in frame 0)
4. Fix header encoding type (DE_STEIM1 -> DE_STEIM2)

"""

with open('/app/mseed3pack.c', 'r') as f:
    src = f.read()

# 1. Implement CRC-32C (Castagnoli)
src = src.replace(
    """    /* TODO: Implement CRC-32C using the Castagnoli polynomial.
     * See mseedformat.h for the algorithm specification. */
    (void)data;
    (void)length;
    return 0;""",
    """    uint32_t crc = 0xFFFFFFFF;
    size_t i;
    int j;
    for (i = 0; i < length; i++)
    {
        crc ^= data[i];
        for (j = 0; j < 8; j++)
        {
            if (crc & 1)
                crc = (crc >> 1) ^ 0x82F63B78;
            else
                crc >>= 1;
        }
    }
    return crc ^ 0xFFFFFFFF;"""
)

# 2a. Implement 7x4-bit packing (nibble=11, dnib=10)
src = src.replace(
    """            {
                /* TODO: Pack 7 four-bit signed differences into one word.
                 * Difference 0 at highest bit position, difference 6 at lowest.
                 * Set dnib in bits 31-30 and control nibble in frameptr[0]. */
            }""",
    """            {
                frameptr[widx]  = ((uint32_t)diffs[6] & 0xFu);
                frameptr[widx] |= ((uint32_t)diffs[5] & 0xFu) << 4;
                frameptr[widx] |= ((uint32_t)diffs[4] & 0xFu) << 8;
                frameptr[widx] |= ((uint32_t)diffs[3] & 0xFu) << 12;
                frameptr[widx] |= ((uint32_t)diffs[2] & 0xFu) << 16;
                frameptr[widx] |= ((uint32_t)diffs[1] & 0xFu) << 20;
                frameptr[widx] |= ((uint32_t)diffs[0] & 0xFu) << 24;
                /* dnib = 10 */
                frameptr[widx] |= 0x2u << 30;
                /* nibble = 11 */
                frameptr[0] |= 0x3u << (30 - 2 * widx);
                packedsamples = 7;
            }"""
)

# 2b. Implement 6x5-bit packing (nibble=11, dnib=01)
src = src.replace(
    """            {
                /* TODO: Pack 6 five-bit signed differences into one word.
                 * Set dnib and control nibble. */
            }""",
    """            {
                frameptr[widx]  = ((uint32_t)diffs[5] & 0x1Fu);
                frameptr[widx] |= ((uint32_t)diffs[4] & 0x1Fu) << 5;
                frameptr[widx] |= ((uint32_t)diffs[3] & 0x1Fu) << 10;
                frameptr[widx] |= ((uint32_t)diffs[2] & 0x1Fu) << 15;
                frameptr[widx] |= ((uint32_t)diffs[1] & 0x1Fu) << 20;
                frameptr[widx] |= ((uint32_t)diffs[0] & 0x1Fu) << 25;
                /* dnib = 01 */
                frameptr[widx] |= 0x1u << 30;
                /* nibble = 11 */
                frameptr[0] |= 0x3u << (30 - 2 * widx);
                packedsamples = 6;
            }"""
)

# 2c. Implement 5x6-bit packing (nibble=11, dnib=00)
src = src.replace(
    """            {
                /* TODO: Pack 5 six-bit signed differences into one word.
                 * Set dnib and control nibble. */
            }""",
    """            {
                frameptr[widx]  = ((uint32_t)diffs[4] & 0x3Fu);
                frameptr[widx] |= ((uint32_t)diffs[3] & 0x3Fu) << 6;
                frameptr[widx] |= ((uint32_t)diffs[2] & 0x3Fu) << 12;
                frameptr[widx] |= ((uint32_t)diffs[1] & 0x3Fu) << 18;
                frameptr[widx] |= ((uint32_t)diffs[0] & 0x3Fu) << 24;
                /* dnib = 00 (no bits to set) */
                /* nibble = 11 */
                frameptr[0] |= 0x3u << (30 - 2 * widx);
                packedsamples = 5;
            }"""
)

# 2d. Implement 4x8-bit packing (nibble=01, no dnib)
src = src.replace(
    """            {
                /* TODO: Pack 4 eight-bit signed differences as bytes.
                 * Use byte-level packing (no dnib for this mode).
                 * Set control nibble. */
            }""",
    """            {
                int8_t *bp = (int8_t *)&frameptr[widx];
                bp[0] = (int8_t)diffs[0];
                bp[1] = (int8_t)diffs[1];
                bp[2] = (int8_t)diffs[2];
                bp[3] = (int8_t)diffs[3];
                /* nibble = 01 */
                frameptr[0] |= 0x1u << (30 - 2 * widx);
                packedsamples = 4;
            }"""
)

# 2e. Implement 3x10-bit packing (nibble=10, dnib=11)
src = src.replace(
    """            {
                /* TODO: Pack 3 ten-bit signed differences into one word.
                 * Set dnib and control nibble. */
            }""",
    """            {
                frameptr[widx]  = ((uint32_t)diffs[2] & 0x3FFu);
                frameptr[widx] |= ((uint32_t)diffs[1] & 0x3FFu) << 10;
                frameptr[widx] |= ((uint32_t)diffs[0] & 0x3FFu) << 20;
                /* dnib = 11 */
                frameptr[widx] |= 0x3u << 30;
                /* nibble = 10 */
                frameptr[0] |= 0x2u << (30 - 2 * widx);
                packedsamples = 3;
            }"""
)

# 2f. Implement 2x15-bit packing (nibble=10, dnib=10)
src = src.replace(
    """            {
                /* TODO: Pack 2 fifteen-bit signed differences into one word.
                 * Set dnib and control nibble. */
            }""",
    """            {
                frameptr[widx]  = ((uint32_t)diffs[1] & 0x7FFFu);
                frameptr[widx] |= ((uint32_t)diffs[0] & 0x7FFFu) << 15;
                /* dnib = 10 */
                frameptr[widx] |= 0x2u << 30;
                /* nibble = 10 */
                frameptr[0] |= 0x2u << (30 - 2 * widx);
                packedsamples = 2;
            }"""
)

# 3. Fix X0/Xn positions (currently swapped)
src = src.replace(
    'frameptr[2] = (uint32_t)input[0];       /* X0 */',
    'frameptr[1] = (uint32_t)input[0];       /* X0 */'
)
src = src.replace(
    'Xnp = (int32_t *)&frameptr[1];           /* Xn set after encoding */',
    'Xnp = (int32_t *)&frameptr[2];           /* Xn set after encoding */'
)

# 4. Fix encoding type: DE_STEIM1 -> DE_STEIM2
src = src.replace(
    'record[15] = DE_STEIM1;',
    'record[15] = DE_STEIM2;'
)

with open('/app/mseed3pack.c', 'w') as f:
    f.write(src)

print("All implementations and fixes applied to mseed3pack.c")
