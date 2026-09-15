/*
 * Ed25519 implementation using OpenSSL BIGNUM for GF(2^255-19) arithmetic.
 * Implements RFC 8032 Section 5.1: key derivation, signing, verification.
 *
 */

#include "ed25519.h"
#include <openssl/sha.h>
#include <openssl/bn.h>
#include <string.h>
#include <stdlib.h>

/* ── Global constants ──────────────────────────────────────────────────── */

static BIGNUM *FP       = NULL;   /* Field prime p = 2^255 - 19        */
static BIGNUM *CURVE_D  = NULL;   /* Curve parameter d                 */
static BIGNUM *GROUP_L  = NULL;   /* Group order L                     */
static BIGNUM *SQRT_M1  = NULL;   /* sqrt(-1) mod p                    */
static BIGNUM *BASE_X   = NULL;   /* Base point x-coordinate           */
static BIGNUM *BASE_Y   = NULL;   /* Base point y-coordinate           */
static int g_init = 0;

/* Extended homogeneous coordinates: x = X/Z, y = Y/Z, xy = T/Z */
typedef struct {
    BIGNUM *X, *Y, *Z, *T;
} ge_point;

/* ── Helpers ───────────────────────────────────────────────────────────── */

static void bn_to_le(const BIGNUM *n, uint8_t *out, size_t len) {
    memset(out, 0, len);
    int nbytes = BN_num_bytes(n);
    if (nbytes == 0) return;
    uint8_t *be = (uint8_t *)malloc(nbytes);
    BN_bn2bin(n, be);
    for (int i = 0; i < nbytes && i < (int)len; i++)
        out[i] = be[nbytes - 1 - i];
    free(be);
}

static BIGNUM *le_to_bn(const uint8_t *in, size_t len) {
    uint8_t *be = (uint8_t *)malloc(len);
    for (size_t i = 0; i < len; i++)
        be[i] = in[len - 1 - i];
    BIGNUM *n = BN_bin2bn(be, (int)len, NULL);
    free(be);
    return n;
}

/* ── Initialization ────────────────────────────────────────────────────── */

static void ensure_init(void) {
    if (g_init) return;
    BN_CTX *ctx = BN_CTX_new();

    /* p = 2^255 - 19 */
    FP = BN_new();
    BIGNUM *one = BN_new();
    BN_one(one);
    BN_lshift(FP, one, 255);
    BIGNUM *n19 = BN_new();
    BN_set_word(n19, 19);
    BN_sub(FP, FP, n19);
    BN_free(n19);
    BN_free(one);

    /* d = -121665 / 121666  mod p */
    CURVE_D = BN_new();
    BIGNUM *a = BN_new(), *b = BN_new(), *inv = BN_new();
    BN_set_word(a, 121665);
    BN_set_word(b, 121666);
    BN_mod_inverse(inv, b, FP, ctx);
    BN_mod_mul(CURVE_D, a, inv, FP, ctx);
    BN_mod_sub(CURVE_D, FP, CURVE_D, FP, ctx);   /* negate */
    BN_free(a); BN_free(b); BN_free(inv);

    /* L = 2^252 + 27742317777372353535851937790883648493 */
    GROUP_L = BN_new();
    BN_hex2bn(&GROUP_L,
        "1000000000000000000000000000000014DEF9DEA2F79CD65812631A5CF5D3ED");

    /* sqrt(-1) = 2^((p-1)/4) mod p */
    SQRT_M1 = BN_new();
    BIGNUM *two = BN_new(), *exp = BN_new(), *pm1 = BN_new();
    BN_set_word(two, 2);
    BN_copy(pm1, FP);
    BN_sub_word(pm1, 1);
    BN_rshift(exp, pm1, 2);                        /* (p-1)/4 */
    BN_mod_exp(SQRT_M1, two, exp, FP, ctx);
    BN_free(two); BN_free(exp); BN_free(pm1);

    /* Base point (Bx, By) */
    BASE_X = BN_new();
    BASE_Y = BN_new();
    BN_hex2bn(&BASE_X,
        "216936D3CD6E53FEC0A4E231FDD6DC5C692CC7609525A7B2C9562D608F25D51A");
    BN_hex2bn(&BASE_Y,
        "6666666666666666666666666666666666666666666666666666666666666658");

    BN_CTX_free(ctx);
    g_init = 1;
}

/* ── Point lifecycle ───────────────────────────────────────────────────── */

static ge_point *ge_new(void) {
    ge_point *P = (ge_point *)calloc(1, sizeof(ge_point));
    P->X = BN_new(); P->Y = BN_new();
    P->Z = BN_new(); P->T = BN_new();
    return P;
}

static void ge_free(ge_point *P) {
    if (!P) return;
    BN_free(P->X); BN_free(P->Y);
    BN_free(P->Z); BN_free(P->T);
    free(P);
}

static void ge_copy(ge_point *dst, const ge_point *src) {
    BN_copy(dst->X, src->X); BN_copy(dst->Y, src->Y);
    BN_copy(dst->Z, src->Z); BN_copy(dst->T, src->T);
}

static void ge_set_identity(ge_point *P) {
    BN_zero(P->X); BN_one(P->Y);
    BN_one(P->Z);  BN_zero(P->T);
}

static ge_point *ge_base(void) {
    ensure_init();
    ge_point *B = ge_new();
    BN_CTX *ctx = BN_CTX_new();
    BN_copy(B->X, BASE_X);
    BN_copy(B->Y, BASE_Y);
    BN_one(B->Z);
    BN_mod_mul(B->T, BASE_X, BASE_Y, FP, ctx);
    BN_CTX_free(ctx);
    return B;
}

/* ── Point addition (a = -1, extended coordinates) ─────────────────────── */
/* RFC 8032 Section 5.1.4 */

static void ge_add(ge_point *R, const ge_point *P, const ge_point *Q) {
    BN_CTX *ctx = BN_CTX_new();
    BN_CTX_start(ctx);

    BIGNUM *A  = BN_CTX_get(ctx);
    BIGNUM *B  = BN_CTX_get(ctx);
    BIGNUM *C  = BN_CTX_get(ctx);
    BIGNUM *DD = BN_CTX_get(ctx);
    BIGNUM *E  = BN_CTX_get(ctx);
    BIGNUM *F  = BN_CTX_get(ctx);
    BIGNUM *G  = BN_CTX_get(ctx);
    BIGNUM *H  = BN_CTX_get(ctx);
    BIGNUM *t1 = BN_CTX_get(ctx);
    BIGNUM *t2 = BN_CTX_get(ctx);

    /* A = (Y1 - X1) * (Y2 - X2) */
    BN_mod_sub(t1, P->Y, P->X, FP, ctx);
    BN_mod_sub(t2, Q->Y, Q->X, FP, ctx);
    BN_mod_mul(A, t1, t2, FP, ctx);

    /* B = (Y1 + X1) * (Y2 + X2) */
    BN_mod_add(t1, P->Y, P->X, FP, ctx);
    BN_mod_add(t2, Q->Y, Q->X, FP, ctx);
    BN_mod_mul(B, t1, t2, FP, ctx);

    /* C = T1 * 2 * d * T2 */
    BN_mod_mul(C, P->T, Q->T, FP, ctx);
    BN_mod_mul(C, C, CURVE_D, FP, ctx);
    BN_mod_add(C, C, C, FP, ctx);

    /* DD = Z1 * 2 * Z2 */
    BN_mod_mul(DD, P->Z, Q->Z, FP, ctx);
    BN_mod_add(DD, DD, DD, FP, ctx);

    /* E = B - A,  F = DD - C,  G = DD + C,  H = B + A */
    BN_mod_sub(E, B, A, FP, ctx);
    BN_mod_sub(F, DD, C, FP, ctx);
    BN_mod_add(G, DD, C, FP, ctx);
    BN_mod_add(H, B, A, FP, ctx);

    /* X3 = E*F,  Y3 = G*H,  T3 = E*H,  Z3 = F*G */
    BN_mod_mul(R->X, E, F, FP, ctx);
    BN_mod_mul(R->Y, G, H, FP, ctx);
    BN_mod_mul(R->T, E, H, FP, ctx);
    BN_mod_mul(R->Z, F, G, FP, ctx);

    BN_CTX_end(ctx);
    BN_CTX_free(ctx);
}

/* ── Point doubling (a = -1, extended coordinates) ─────────────────────── */

static void ge_double(ge_point *R, const ge_point *P) {
    BN_CTX *ctx = BN_CTX_new();
    BN_CTX_start(ctx);

    BIGNUM *A  = BN_CTX_get(ctx);
    BIGNUM *B  = BN_CTX_get(ctx);
    BIGNUM *C  = BN_CTX_get(ctx);
    BIGNUM *E  = BN_CTX_get(ctx);
    BIGNUM *F  = BN_CTX_get(ctx);
    BIGNUM *G  = BN_CTX_get(ctx);
    BIGNUM *H  = BN_CTX_get(ctx);
    BIGNUM *t1 = BN_CTX_get(ctx);

    /* A = X1^2 */
    BN_mod_sqr(A, P->X, FP, ctx);
    /* B = Y1^2 */
    BN_mod_sqr(B, P->Y, FP, ctx);
    /* C = 2 * Z1^2 */
    BN_mod_sqr(C, P->Z, FP, ctx);
    BN_mod_add(C, C, C, FP, ctx);
    /* H = A + B */
    BN_mod_add(H, A, B, FP, ctx);
    /* E = H - (X1 + Y1)^2 */
    BN_mod_add(t1, P->X, P->Y, FP, ctx);
    BN_mod_sqr(E, t1, FP, ctx);
    BN_mod_sub(E, H, E, FP, ctx);
    /* G = A - B */
    BN_mod_sub(G, A, B, FP, ctx);
    /* F = C + G */
    BN_mod_add(F, C, G, FP, ctx);

    /* X3 = E*F,  Y3 = G*H,  T3 = E*H,  Z3 = F*G */
    BN_mod_mul(R->X, E, F, FP, ctx);
    BN_mod_mul(R->Y, G, H, FP, ctx);
    BN_mod_mul(R->T, E, H, FP, ctx);
    BN_mod_mul(R->Z, F, G, FP, ctx);

    BN_CTX_end(ctx);
    BN_CTX_free(ctx);
}

/* ── Scalar multiplication: R = s * P ──────────────────────────────────── */

static void ge_scalarmult(ge_point *R, const BIGNUM *s, const ge_point *P) {
    ge_set_identity(R);
    ge_point *Q   = ge_new();
    ge_point *tmp = ge_new();
    ge_copy(Q, P);

    int bits = BN_num_bits(s);
    for (int i = 0; i < bits; i++) {
        if (BN_is_bit_set(s, i)) {
            ge_add(tmp, R, Q);
            ge_copy(R, tmp);
        }
        ge_double(tmp, Q);
        ge_copy(Q, tmp);
    }
    ge_free(Q);
    ge_free(tmp);
}

/* ── Point encoding (compress) ─────────────────────────────────────────── */

static void ge_encode(uint8_t out[32], const ge_point *P) {
    BN_CTX *ctx = BN_CTX_new();
    BIGNUM *zinv = BN_new();
    BIGNUM *x    = BN_new();
    BIGNUM *y    = BN_new();

    BN_mod_inverse(zinv, P->Z, FP, ctx);
    BN_mod_mul(x, P->X, zinv, FP, ctx);
    BN_mod_mul(y, P->Y, zinv, FP, ctx);

    bn_to_le(y, out, 32);
    if (BN_is_odd(x))
        out[31] |= 0x80;

    BN_free(zinv); BN_free(x); BN_free(y);
    BN_CTX_free(ctx);
}

/* ── Point decoding (decompress) ───────────────────────────────────────── */
/* Returns 1 on success, 0 on failure. */

static int ge_decode(ge_point *P, const uint8_t in[32]) {
    ensure_init();
    BN_CTX *ctx = BN_CTX_new();

    /* Extract sign bit and y */
    uint8_t ybuf[32];
    memcpy(ybuf, in, 32);
    int x_sign = (ybuf[31] >> 7) & 1;
    ybuf[31] &= 0x7F;

    BIGNUM *y = le_to_bn(ybuf, 32);
    if (BN_cmp(y, FP) >= 0) { BN_free(y); BN_CTX_free(ctx); return 0; }

    /* x^2 = (y^2 - 1) / (d*y^2 + 1)  mod p */
    BIGNUM *y2   = BN_new();
    BIGNUM *num  = BN_new();
    BIGNUM *den  = BN_new();
    BIGNUM *x2   = BN_new();
    BIGNUM *x    = BN_new();
    BIGNUM *one  = BN_new();

    BN_mod_sqr(y2, y, FP, ctx);

    BN_one(one);
    BN_mod_sub(num, y2, one, FP, ctx);           /* y^2 - 1 */

    BN_mod_mul(den, CURVE_D, y2, FP, ctx);
    BN_mod_add(den, den, one, FP, ctx);           /* d*y^2 + 1 */

    BIGNUM *den_inv = BN_new();
    if (!BN_mod_inverse(den_inv, den, FP, ctx)) {
        /* denominator is zero (shouldn't happen for valid inputs) */
        BN_free(y); BN_free(y2); BN_free(num); BN_free(den);
        BN_free(x2); BN_free(x); BN_free(one); BN_free(den_inv);
        BN_CTX_free(ctx);
        return 0;
    }
    BN_mod_mul(x2, num, den_inv, FP, ctx);

    /* x = x2^((p+3)/8) mod p */
    BIGNUM *exp = BN_new();
    BN_copy(exp, FP);
    BN_add_word(exp, 3);
    BN_rshift(exp, exp, 3);                        /* (p+3)/8 */
    BN_mod_exp(x, x2, exp, FP, ctx);

    /* Check: x^2 == x2 ? */
    BIGNUM *chk = BN_new();
    BN_mod_sqr(chk, x, FP, ctx);
    if (BN_cmp(chk, x2) != 0) {
        /* Try x = x * sqrt(-1) */
        BN_mod_mul(x, x, SQRT_M1, FP, ctx);
        BN_mod_sqr(chk, x, FP, ctx);
        if (BN_cmp(chk, x2) != 0) {
            BN_free(y); BN_free(y2); BN_free(num); BN_free(den);
            BN_free(x2); BN_free(x); BN_free(one); BN_free(den_inv);
            BN_free(exp); BN_free(chk);
            BN_CTX_free(ctx);
            return 0;
        }
    }

    /* Handle x == 0 with wrong sign */
    if (BN_is_zero(x) && x_sign != 0) {
        BN_free(y); BN_free(y2); BN_free(num); BN_free(den);
        BN_free(x2); BN_free(x); BN_free(one); BN_free(den_inv);
        BN_free(exp); BN_free(chk);
        BN_CTX_free(ctx);
        return 0;
    }

    /* Adjust sign of x */
    if (BN_is_odd(x) != x_sign) {
        BN_sub(x, FP, x);
    }

    /* Set point */
    BN_copy(P->X, x);
    BN_copy(P->Y, y);
    BN_one(P->Z);
    BN_mod_mul(P->T, x, y, FP, ctx);

    BN_free(y); BN_free(y2); BN_free(num); BN_free(den);
    BN_free(x2); BN_free(x); BN_free(one); BN_free(den_inv);
    BN_free(exp); BN_free(chk);
    BN_CTX_free(ctx);
    return 1;
}

/* ── SHA-512 helpers ───────────────────────────────────────────────────── */

static void sha512_raw(const uint8_t *data, size_t len, uint8_t out[64]) {
    SHA512(data, len, out);
}

/* SHA-512 of concatenated buffers (2 or 3 parts) */
static void sha512_cat2(const uint8_t *a, size_t al,
                        const uint8_t *b, size_t bl,
                        uint8_t out[64]) {
    SHA512_CTX c;
    SHA512_Init(&c);
    if (a && al) SHA512_Update(&c, a, al);
    if (b && bl) SHA512_Update(&c, b, bl);
    SHA512_Final(out, &c);
}

static void sha512_cat3(const uint8_t *a, size_t al,
                        const uint8_t *b, size_t bl,
                        const uint8_t *c, size_t cl,
                        uint8_t out[64]) {
    SHA512_CTX sc;
    SHA512_Init(&sc);
    if (a && al) SHA512_Update(&sc, a, al);
    if (b && bl) SHA512_Update(&sc, b, bl);
    if (c && cl) SHA512_Update(&sc, c, cl);
    SHA512_Final(out, &sc);
}

/* Interpret 64-byte hash as little-endian integer, reduce mod L */
static BIGNUM *hash_mod_l(const uint8_t h[64]) {
    BN_CTX *ctx = BN_CTX_new();
    BIGNUM *full = le_to_bn(h, 64);
    BIGNUM *r = BN_new();
    BN_mod(r, full, GROUP_L, ctx);
    BN_free(full);
    BN_CTX_free(ctx);
    return r;
}

/* ── Public API ────────────────────────────────────────────────────────── */

void ed25519_derive_pubkey(const uint8_t secret[32], uint8_t pubkey[32]) {
    ensure_init();

    uint8_t h[64];
    sha512_raw(secret, 32, h);

    /* Clamp */
    h[0]  &= 248;    /* clear lowest 3 bits */
    h[31] &= 127;    /* clear highest bit   */
    h[31] |= 64;     /* set second-highest  */

    BIGNUM *a = le_to_bn(h, 32);

    ge_point *B = ge_base();
    ge_point *A = ge_new();
    ge_scalarmult(A, a, B);
    ge_encode(pubkey, A);

    BN_free(a);
    ge_free(B);
    ge_free(A);
}

void ed25519_sign(const uint8_t secret[32], const uint8_t *msg, size_t msg_len,
                  uint8_t signature[64]) {
    ensure_init();

    uint8_t h[64];
    sha512_raw(secret, 32, h);

    /* Scalar a (clamped) */
    uint8_t a_bytes[32];
    memcpy(a_bytes, h, 32);
    a_bytes[0]  &= 248;
    a_bytes[31] &= 127;
    a_bytes[31] |= 64;
    BIGNUM *a = le_to_bn(a_bytes, 32);

    /* Public key A */
    ge_point *BP = ge_base();
    ge_point *Apt = ge_new();
    ge_scalarmult(Apt, a, BP);
    uint8_t A[32];
    ge_encode(A, Apt);
    ge_free(Apt);

    /* r = H(prefix || msg) mod L */
    uint8_t r_hash[64];
    sha512_cat2(h + 32, 32, msg, msg_len, r_hash);
    BIGNUM *r = hash_mod_l(r_hash);

    /* R = [r]B */
    ge_point *Rpt = ge_new();
    ge_scalarmult(Rpt, r, BP);
    uint8_t R[32];
    ge_encode(R, Rpt);
    ge_free(Rpt);

    /* k = H(R || A || msg) mod L */
    uint8_t k_hash[64];
    sha512_cat3(R, 32, A, 32, msg, msg_len, k_hash);
    BIGNUM *k = hash_mod_l(k_hash);

    /* S = (r + k * a) mod L */
    BN_CTX *ctx = BN_CTX_new();
    BIGNUM *S = BN_new();
    BN_mod_mul(S, k, a, GROUP_L, ctx);
    BN_mod_add(S, r, S, GROUP_L, ctx);

    /* signature = R || S */
    memcpy(signature, R, 32);
    bn_to_le(S, signature + 32, 32);

    BN_free(a); BN_free(r); BN_free(k); BN_free(S);
    ge_free(BP);
    BN_CTX_free(ctx);
}

int ed25519_verify(const uint8_t pubkey[32], const uint8_t *msg, size_t msg_len,
                   const uint8_t signature[64]) {
    ensure_init();

    /* Decode A (public key) */
    ge_point *A = ge_new();
    if (!ge_decode(A, pubkey)) {
        ge_free(A);
        return 0;
    }

    /* Decode R (first half of signature) */
    ge_point *R = ge_new();
    if (!ge_decode(R, signature)) {
        ge_free(A); ge_free(R);
        return 0;
    }

    /* Parse S and check S < L */
    BIGNUM *S = le_to_bn(signature + 32, 32);
    if (BN_cmp(S, GROUP_L) >= 0) {
        ge_free(A); ge_free(R); BN_free(S);
        return 0;
    }

    /* k = H(R || A || msg) mod L */
    uint8_t k_hash[64];
    sha512_cat3(signature, 32, pubkey, 32, msg, msg_len, k_hash);
    BIGNUM *k = hash_mod_l(k_hash);

    /* LHS = [S]B */
    ge_point *BP  = ge_base();
    ge_point *lhs = ge_new();
    ge_scalarmult(lhs, S, BP);

    /* RHS = R + [k]A */
    ge_point *kA  = ge_new();
    ge_scalarmult(kA, k, A);
    ge_point *rhs = ge_new();
    ge_add(rhs, R, kA);

    /* Compare by encoding */
    uint8_t lhs_enc[32], rhs_enc[32];
    ge_encode(lhs_enc, lhs);
    ge_encode(rhs_enc, rhs);
    int ok = (memcmp(lhs_enc, rhs_enc, 32) == 0);

    ge_free(A); ge_free(R); ge_free(BP);
    ge_free(lhs); ge_free(kA); ge_free(rhs);
    BN_free(S); BN_free(k);

    return ok;
}
