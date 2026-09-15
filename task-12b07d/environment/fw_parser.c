/*
 * Simulated SB2 firmware update parser.
 * Inspired by real-world embedded firmware update mechanisms.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define BLOCK_SIZE 16
#define HDR_BUF_BLOCKS 8
#define HDR_BUF_SIZE (HDR_BUF_BLOCKS * BLOCK_SIZE)

#pragma pack(push, 1)
typedef struct {
    uint32_t magic;
    uint16_t major_ver;
    uint16_t minor_ver;
    uint32_t flags;
    uint32_t image_blocks;
    uint32_t first_boot;
    uint32_t cert_offset;
    uint16_t hdr_blocks;
    uint16_t key_blob_block;
    uint16_t key_blob_count;
    uint16_t max_mac;
    uint8_t  reserved[32];
} sb2_hdr_t;
#pragma pack(pop)

typedef struct {
    uint8_t  hdr_buf[HDR_BUF_SIZE];
    uint32_t auth_req;
    uint32_t dbg_iface;
    uint32_t sec_bypass;
    uint8_t  secret_out[32];
} parse_ctx_t;

static const uint8_t dev_secret[32] = {
    0xd3, 0x4d, 0xb3, 0x3f, 0xc4, 0xf3, 0xb4, 0xb3,
    0x13, 0x37, 0x42, 0x42, 0xf3, 0x3d, 0xfa, 0xc3,
    0xab, 0xcd, 0xef, 0x01, 0x23, 0x45, 0x67, 0x89,
    0x9a, 0xbc, 0xde, 0xf0, 0x11, 0x22, 0x33, 0x44
};

static int do_parse(const char *path) {
    parse_ctx_t *ctx = (parse_ctx_t *)calloc(1, sizeof(parse_ctx_t));
    if (!ctx) return 1;
    ctx->auth_req = 1;

    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "cannot open '%s'\n", path);
        free(ctx);
        return 1;
    }

    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (sz < (long)sizeof(sb2_hdr_t)) {
        fprintf(stderr, "file too small\n");
        fclose(f);
        free(ctx);
        return 1;
    }

    uint8_t *raw = (uint8_t *)malloc(sz);
    if (!raw) {
        fclose(f);
        free(ctx);
        return 1;
    }
    fread(raw, 1, sz, f);
    fclose(f);

    sb2_hdr_t *h = (sb2_hdr_t *)raw;

    if (h->magic != 0x53423221u) {
        fprintf(stderr, "bad magic: 0x%08x\n", h->magic);
        free(raw);
        free(ctx);
        return 1;
    }
    if (h->major_ver != 2 || h->minor_ver != 1) {
        fprintf(stderr, "unsupported ver %u.%u\n", h->major_ver, h->minor_ver);
        free(raw);
        free(ctx);
        return 1;
    }

    /* Copy header data into context buffer.
     * Uses key_blob_block from the header to determine how many
     * blocks to copy. */
    uint32_t n = (uint32_t)h->key_blob_block;
    uint32_t cb = n * BLOCK_SIZE;
    if (cb > (uint32_t)sz)
        cb = (uint32_t)sz;

    memcpy(ctx->hdr_buf, raw, cb);

    /* Verify signature if authentication is active */
    if (ctx->auth_req) {
        uint32_t acc = 0xa5a5a5a5u;
        uint32_t *wp = (uint32_t *)ctx->hdr_buf;
        for (int i = 0; i < (int)(sizeof(sb2_hdr_t) / 4); i++)
            acc ^= wp[i];
        if (acc != 0) {
            fprintf(stderr, "auth failed\n");
            free(raw);
            free(ctx);
            return 1;
        }
    }

    printf("=== SB2 Update Parser v%u.%u ===\n", h->major_ver, h->minor_ver);
    printf("Flags: 0x%08x\n", h->flags);
    printf("Image blocks: %u\n", h->image_blocks);
    printf("Key blob block: %u\n", h->key_blob_block);
    printf("Auth required: %u\n", ctx->auth_req);
    printf("Debug interface: %u\n", ctx->dbg_iface);
    printf("Security bypass: 0x%08x\n", ctx->sec_bypass);

    if (ctx->sec_bypass == 0x55aa55aau) {
        printf("BYPASS_ACTIVE\n");
        memcpy(ctx->secret_out, dev_secret, 32);
        printf("DEVICE_SECRET:");
        for (int i = 0; i < 32; i++)
            printf("%02x", ctx->secret_out[i]);
        printf("\n");
    }

    if (ctx->dbg_iface == 1)
        printf("DEBUG_ENABLED\n");

    printf("Parse complete.\n");
    free(raw);
    free(ctx);
    return 0;
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <update.sb2>\n", argv[0]);
        return 1;
    }
    return do_parse(argv[1]);
}
