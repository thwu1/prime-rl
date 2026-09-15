/*
 * mseed3pack - Pack seismological sample data into miniSEED v3 format
 *
 * INCOMPLETE IMPLEMENTATION: This program encodes integer samples using
 * Steim2 differential compression, constructs a miniSEED v3 header,
 * computes CRC-32C, and writes the binary record to output.mseed3.
 *
 * Several core functions require implementation.  Refer to mseedformat.h
 * for the miniSEED v3 specification and Steim2 packing details.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "sinedata.h"
#include "mseedformat.h"

/*======================================================================
 * Configuration
 *====================================================================*/
#define NUM_SAMPLES    400
#define SID            "FDSN:XX_TEST_00_B_H_Z"
#define SID_LENGTH     21
#define SAMPLE_RATE    40.0
#define RECORD_YEAR    2024
#define RECORD_DAY     1

/* Maximum number of 64-byte Steim2 frames to allocate */
#define MAX_FRAMES     64

/*======================================================================
 * BITWIDTH - determine minimum bits needed for a signed difference
 *
 * Maps a signed integer to the smallest Steim2-compatible bit width:
 * 4, 5, 6, 8, 10, 15, 16, 30, or 32 bits.
 *====================================================================*/
#define BITWIDTH(VALUE, RESULT) \
    if ((VALUE) >= -8 && (VALUE) <= 7) (RESULT) = 4; \
    else if ((VALUE) >= -16 && (VALUE) <= 15) (RESULT) = 5; \
    else if ((VALUE) >= -32 && (VALUE) <= 31) (RESULT) = 6; \
    else if ((VALUE) >= -128 && (VALUE) <= 127) (RESULT) = 8; \
    else if ((VALUE) >= -512 && (VALUE) <= 511) (RESULT) = 10; \
    else if ((VALUE) >= -16384 && (VALUE) <= 16383) (RESULT) = 15; \
    else if ((VALUE) >= -32768 && (VALUE) <= 32767) (RESULT) = 16; \
    else if ((VALUE) >= -536870912 && (VALUE) <= 536870911) (RESULT) = 30; \
    else (RESULT) = 32;

/*======================================================================
 * CRC-32C (Castagnoli) computation
 *
 * Must compute the CRC-32C checksum used by miniSEED v3 for record
 * integrity validation.  See mseedformat.h for polynomial details.
 *====================================================================*/
static uint32_t compute_crc32c(const uint8_t *data, size_t length)
{
    /* TODO: Implement CRC-32C using the Castagnoli polynomial.
     * See mseedformat.h for the algorithm specification. */
    (void)data;
    (void)length;
    return 0;
}

/*======================================================================
 * Steim2 encoder
 *
 * Encodes an array of int32 samples into Steim2 compressed frames.
 * Each frame is 64 bytes (16 x uint32_t).  Word 0 of each frame holds
 * 16 two-bit nibble codes controlling data word interpretation.
 *
 * Frame 0 additionally stores integration constants:
 *   Word 1 = X0 (forward integration constant = first sample)
 *   Word 2 = Xn (reverse integration constant = last encoded sample)
 *   Data packing begins at word 3.
 *
 * Seven packing modes, checked from densest to sparsest:
 *   7 x 4-bit   (nibble=11, dnib=10)
 *   6 x 5-bit   (nibble=11, dnib=01)
 *   5 x 6-bit   (nibble=11, dnib=00)
 *   4 x 8-bit   (nibble=01)
 *   3 x 10-bit  (nibble=10, dnib=11)
 *   2 x 15-bit  (nibble=10, dnib=10)
 *   1 x 30-bit  (nibble=10, dnib=01)
 *
 * Returns number of samples encoded, or -1 on error.
 *====================================================================*/
static int64_t encode_steim2(int32_t *input, int samplecount,
                             uint32_t *output, int maxframes,
                             uint32_t *byteswritten)
{
    uint32_t *frameptr;
    int32_t *Xnp = NULL;
    int32_t diffs[7];
    int32_t bitwidth[7];
    int inputidx = 0;
    int outputsamples = 0;
    int frameidx;
    int diffcount = 0;
    int packedsamples = 0;
    int startnibble;
    int widx, idx;

    if (samplecount == 0) return 0;
    if (!input || !output) return -1;

    /* First difference is inter-record; 0 for standalone record */
    diffs[0] = 0;
    BITWIDTH(diffs[0], bitwidth[0]);
    diffcount = 1;

    for (frameidx = 0; frameidx < maxframes && outputsamples < samplecount; frameidx++)
    {
        frameptr = output + (16 * frameidx);
        memset(frameptr, 0, 64);

        if (frameidx == 0)
        {
            /* Integration constants in frame 0 */
            frameptr[2] = (uint32_t)input[0];       /* X0 */
            Xnp = (int32_t *)&frameptr[1];           /* Xn set after encoding */
            startnibble = 3;  /* Skip nibble word, X0, Xn */
        }
        else
        {
            startnibble = 1;  /* Skip nibble word only */
        }

        for (widx = startnibble; widx < 16 && outputsamples < samplecount; widx++)
        {
            /* Refill difference buffer when depleted */
            if (diffcount < 7)
            {
                /* Shift remaining unpacked diffs to front */
                for (idx = 0; idx < diffcount; idx++)
                {
                    diffs[idx] = diffs[packedsamples + idx];
                    bitwidth[idx] = bitwidth[packedsamples + idx];
                }
                /* Compute new differences */
                for (idx = diffcount; idx < 7 && inputidx < (samplecount - 1); idx++, inputidx++)
                {
                    diffs[idx] = input[inputidx + 1] - input[inputidx];
                    BITWIDTH(diffs[idx], bitwidth[idx]);
                    diffcount++;
                }
            }

            packedsamples = 0;

            /* === 7 x 4-bit differences (most dense) === */
            if (packedsamples == 0 && diffcount == 7 &&
                bitwidth[0] <= 4 && bitwidth[1] <= 4 && bitwidth[2] <= 4 &&
                bitwidth[3] <= 4 && bitwidth[4] <= 4 && bitwidth[5] <= 4 &&
                bitwidth[6] <= 4)
            {
                /* TODO: Pack 7 four-bit signed differences into one word.
                 * Difference 0 at highest bit position, difference 6 at lowest.
                 * Set dnib in bits 31-30 and control nibble in frameptr[0]. */
            }

            /* === 6 x 5-bit differences === */
            if (packedsamples == 0 && diffcount >= 6 &&
                bitwidth[0] <= 5 && bitwidth[1] <= 5 && bitwidth[2] <= 5 &&
                bitwidth[3] <= 5 && bitwidth[4] <= 5 && bitwidth[5] <= 5)
            {
                /* TODO: Pack 6 five-bit signed differences into one word.
                 * Set dnib and control nibble. */
            }

            /* === 5 x 6-bit differences === */
            if (packedsamples == 0 && diffcount >= 5 &&
                bitwidth[0] <= 6 && bitwidth[1] <= 6 && bitwidth[2] <= 6 &&
                bitwidth[3] <= 6 && bitwidth[4] <= 6)
            {
                /* TODO: Pack 5 six-bit signed differences into one word.
                 * Set dnib and control nibble. */
            }

            /* === 4 x 8-bit differences === */
            if (packedsamples == 0 && diffcount >= 4 &&
                bitwidth[0] <= 8 && bitwidth[1] <= 8 &&
                bitwidth[2] <= 8 && bitwidth[3] <= 8)
            {
                /* TODO: Pack 4 eight-bit signed differences as bytes.
                 * Use byte-level packing (no dnib for this mode).
                 * Set control nibble. */
            }

            /* === 3 x 10-bit differences === */
            if (packedsamples == 0 && diffcount >= 3 &&
                bitwidth[0] <= 10 && bitwidth[1] <= 10 && bitwidth[2] <= 10)
            {
                /* TODO: Pack 3 ten-bit signed differences into one word.
                 * Set dnib and control nibble. */
            }

            /* === 2 x 15-bit differences === */
            if (packedsamples == 0 && diffcount >= 2 &&
                bitwidth[0] <= 15 && bitwidth[1] <= 15)
            {
                /* TODO: Pack 2 fifteen-bit signed differences into one word.
                 * Set dnib and control nibble. */
            }

            /* === 1 x 30-bit difference (least dense, reference) === */
            if (packedsamples == 0 && diffcount >= 1 && bitwidth[0] <= 30)
            {
                frameptr[widx] = ((uint32_t)diffs[0] & 0x3FFFFFFFu);
                /* dnib = 01 */
                frameptr[widx] |= 0x1u << 30;
                /* nibble = 10 */
                frameptr[0] |= 0x2u << (30 - 2 * widx);
                packedsamples = 1;
            }

            if (packedsamples == 0)
            {
                fprintf(stderr, "ERROR: difference %d exceeds Steim2 30-bit limit\n",
                        diffs[0]);
                return -1;
            }

            diffcount -= packedsamples;
            outputsamples += packedsamples;
        } /* end word loop */
    } /* end frame loop */

    /* Set Xn (reverse integration constant) to last encoded sample */
    if (Xnp)
        *Xnp = input[outputsamples - 1];

    if (byteswritten)
        *byteswritten = (uint32_t)(frameidx * 64);

    return outputsamples;
}

/*======================================================================
 * Pack a complete miniSEED v3 record
 *
 * Assembles the fixed header, source identifier, and Steim2-encoded
 * data payload into a single binary record.  Computes CRC-32C over
 * the entire record (with CRC field zeroed) and embeds it.
 *====================================================================*/
static int pack_record(int32_t *samples, int num_samples,
                       uint8_t *record, int *record_length)
{
    uint32_t steim_output[MAX_FRAMES * 16];
    uint32_t steim_bytes = 0;
    int64_t packed;
    uint32_t crc;
    int sid_len = SID_LENGTH;
    int header_plus_sid = MS3_FSDH_LEN + sid_len;
    int total_length;
    double samplerate = SAMPLE_RATE;
    uint32_t numsamples = (uint32_t)num_samples;
    uint16_t year = RECORD_YEAR;
    uint16_t day = RECORD_DAY;
    uint16_t extra_length = 0;

    /* Encode samples */
    packed = encode_steim2(samples, num_samples, steim_output, MAX_FRAMES, &steim_bytes);
    if (packed < 0)
    {
        fprintf(stderr, "Steim2 encoding failed\n");
        return -1;
    }

    fprintf(stdout, "Steim2: encoded %lld samples into %u bytes (%u frames)\n",
            (long long)packed, steim_bytes, steim_bytes / 64);

    total_length = header_plus_sid + steim_bytes;
    memset(record, 0, total_length);

    /* --- Fixed header fields (40 bytes, little-endian) --- */

    /* Bytes 0-1: Record indicator "MS" */
    record[0] = 'M';
    record[1] = 'S';

    /* Byte 2: Format version */
    record[2] = 3;

    /* Byte 3: Flags */
    record[3] = 0;

    /* Bytes 4-7: Nanosecond (uint32 LE) */
    memset(record + 4, 0, 4);

    /* Bytes 8-9: Year (uint16 LE) */
    memcpy(record + 8, &year, 2);

    /* Bytes 10-11: Day of year (uint16 LE) */
    memcpy(record + 10, &day, 2);

    /* Byte 12: Hour */
    record[12] = 0;

    /* Byte 13: Minute */
    record[13] = 0;

    /* Byte 14: Second */
    record[14] = 0;

    /* Byte 15: Data encoding */
    record[15] = DE_STEIM1;

    /* Bytes 16-23: Sample rate (float64 LE) */
    memcpy(record + 16, &samplerate, 8);

    /* Bytes 24-27: Number of samples (uint32 LE) */
    memcpy(record + 24, &numsamples, 4);

    /* Bytes 28-31: CRC placeholder (zeroed for computation) */
    memset(record + 28, 0, 4);

    /* Byte 32: Publication version */
    record[32] = 1;

    /* Byte 33: Length of source identifier */
    record[33] = (uint8_t)sid_len;

    /* Bytes 34-35: Length of extra headers (uint16 LE) */
    memcpy(record + 34, &extra_length, 2);

    /* Bytes 36-39: Length of data payload (uint32 LE) */
    memcpy(record + 36, &steim_bytes, 4);

    /* --- Source identifier (immediately after fixed header) --- */
    memcpy(record + MS3_FSDH_LEN, SID, sid_len);

    /* --- Data payload --- */
    memcpy(record + header_plus_sid, steim_output, steim_bytes);

    /* --- Compute CRC-32C and embed --- */
    crc = compute_crc32c(record, total_length);
    memcpy(record + 28, &crc, 4);

    *record_length = total_length;

    fprintf(stdout, "Record: %d bytes (header+SID=%d, payload=%u)\n",
            total_length, header_plus_sid, steim_bytes);
    fprintf(stdout, "CRC-32C: 0x%08X\n", crc);

    return 0;
}

/*======================================================================
 * Main entry point
 *====================================================================*/
int main(void)
{
    int32_t samples[NUM_SAMPLES];
    uint8_t record[65536];
    int record_length = 0;
    int i;
    FILE *fp;

    /* Truncate floating-point sine data to integers */
    for (i = 0; i < NUM_SAMPLES; i++)
        samples[i] = (int32_t)dsinedata[i];

    fprintf(stdout, "Packing %d samples into miniSEED v3 record\n", NUM_SAMPLES);
    fprintf(stdout, "Sample[0]=%d  Sample[%d]=%d\n",
            samples[0], NUM_SAMPLES - 1, samples[NUM_SAMPLES - 1]);

    /* Pack the record */
    if (pack_record(samples, NUM_SAMPLES, record, &record_length) != 0)
    {
        fprintf(stderr, "Failed to pack record\n");
        return 1;
    }

    /* Write to file */
    fp = fopen("output.mseed3", "wb");
    if (!fp)
    {
        fprintf(stderr, "Failed to open output file\n");
        return 1;
    }
    fwrite(record, 1, record_length, fp);
    fclose(fp);

    fprintf(stdout, "Written %d bytes to output.mseed3\n", record_length);
    return 0;
}
