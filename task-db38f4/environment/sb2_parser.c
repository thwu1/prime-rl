/*
 *
 * SB2 firmware update parser — pre-compiled vendor component.
 * Source NOT distributed; only the object file (sb2_parser.o) is shipped.
 */

#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "sb2_format.h"

#define PARSE_BLOCK_SIZE  SB2_BLOCK_SIZE
#define HEADER_BUF_SIZE   SB2_HEADER_SIZE

/* ---------- Security magic constants ---------- */
#define SECURE_TRACKER_VERIFIED  0x55AACC33U
#define SKBOOT_STATUS_SUCCESS    0x5AC3C35AU
#define OXIDE_DEBUG_TOKEN        0x4F584944U

/* ---------- CRC-32 (ISO 3309 / ITU-T V.42) ---------- */
static uint32_t crc32_table[256];
static int      crc32_ready = 0;

static void crc32_init(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int j = 0; j < 8; j++)
            c = (c & 1) ? (0xEDB88320U ^ (c >> 1)) : (c >> 1);
        crc32_table[i] = c;
    }
    crc32_ready = 1;
}

static uint32_t crc32_compute(const uint8_t *buf, size_t len) {
    if (!crc32_ready) crc32_init();
    uint32_t crc = 0xFFFFFFFFU;
    for (size_t i = 0; i < len; i++)
        crc = crc32_table[(crc ^ buf[i]) & 0xFF] ^ (crc >> 8);
    return crc ^ 0xFFFFFFFFU;
}

/* ---------- Internal parse context ----------
 *
 * Layout (not exposed in any shipped header):
 *
 *   +0x000  header_buf[128]
 *   +0x080  integrity_crc        (uint32_t)
 *   +0x084  parse_flags          (uint16_t)
 *   +0x086  _align0              (uint16_t)
 *   +0x088  signature_verified   (uint32_t)
 *   +0x08C  auth_stage           (uint32_t)
 *   +0x090  debug_token          (uint32_t)
 *   +0x094  _reserved[12]
 *   +0x0A0  dice_uds[32]
 */
struct parse_context {
    uint8_t  header_buf[HEADER_BUF_SIZE]; /* 128 bytes */
    uint32_t integrity_crc;
    uint16_t parse_flags;
    uint16_t _align0;
    uint32_t signature_verified;
    uint32_t auth_stage;
    uint32_t debug_token;
    uint8_t  _reserved[12];
    uint8_t  dice_uds[32];
};

static struct parse_context g_ctx;

static const uint8_t UDS_INITIAL[32] = {
    0x7a, 0x3f, 0x8b, 0x2e, 0x91, 0xd4, 0x56, 0xc8,
    0xa2, 0x17, 0xe5, 0x6b, 0x39, 0xf0, 0x84, 0x1d,
    0xb7, 0x52, 0xce, 0x43, 0x68, 0x9a, 0x0f, 0xe1,
    0x25, 0xd6, 0x7c, 0xab, 0x4e, 0x93, 0x1f, 0x60
};

/* ---- Public API ---- */

void init_firmware(void) {
    memset(&g_ctx, 0, sizeof(g_ctx));
    memcpy(g_ctx.dice_uds, UDS_INITIAL, sizeof(UDS_INITIAL));
}

int parse_and_verify(const uint8_t *data, size_t data_len) {
    const struct sb2_header *hdr = (const struct sb2_header *)data;

    /* 1. Primary magic */
    if (memcmp(hdr->m_signature, "STMP", 4) != 0) {
        fprintf(stderr, "REJECT: primary signature invalid\n");
        return -1;
    }
    /* 2. Secondary magic */
    if (memcmp(hdr->m_signature2, "sgtl", 4) != 0) {
        fprintf(stderr, "REJECT: secondary signature invalid\n");
        return -1;
    }
    /* 3. Version */
    if (hdr->m_majorVersion != 2) {
        fprintf(stderr, "REJECT: unsupported version %u\n",
                (unsigned)hdr->m_majorVersion);
        return -1;
    }

    /*
     * Copy header blocks into parse context.
     *
     * BUG: The correct bound is SB2_HEADER_BLOCKS (8), but the code
     *      trusts m_keyBlobBlock from the untrusted input.  A well-formed
     *      file has m_keyBlobBlock == 8, but nothing enforces this.
     */
    uint16_t blocks = hdr->m_keyBlobBlock;
    size_t   nbytes = (size_t)blocks * PARSE_BLOCK_SIZE;

    if (nbytes > data_len) {
        fprintf(stderr, "REJECT: truncated input (%zu available, %zu needed)\n",
                data_len, nbytes);
        return -1;
    }

    memcpy(g_ctx.header_buf, data, nbytes);   /* <-- overflow */

    /* 4. Integrity: CRC-32 over first 96 header bytes */
    uint32_t expected = crc32_compute(g_ctx.header_buf, 96);
    if (g_ctx.integrity_crc != expected) {
        fprintf(stderr, "REJECT: integrity check failed\n");
        return -2;
    }

    /* 5. Signature verification */
    if (g_ctx.signature_verified != SECURE_TRACKER_VERIFIED) {
        fprintf(stderr, "REJECT: verification stage 3\n");
        return -3;
    }

    /* 6. Authentication */
    if (g_ctx.auth_stage != SKBOOT_STATUS_SUCCESS) {
        fprintf(stderr, "REJECT: verification stage 4\n");
        return -4;
    }

    /* 7. Debug access token */
    if (g_ctx.debug_token != OXIDE_DEBUG_TOKEN) {
        fprintf(stderr, "REJECT: verification stage 5\n");
        return -5;
    }

    return 0;   /* all checks passed */
}

const uint8_t *get_dice_uds(void) {
    return g_ctx.dice_uds;
}
