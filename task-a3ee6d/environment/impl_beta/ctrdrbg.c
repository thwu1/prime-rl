/*
 * CTR_DRBG implementation with AES block cipher.
 * Implements NIST SP 800-90A Sections 10.2 and 10.3.
 * Supports use-df and no-df operational modes.
 */

#include "ctrdrbg.h"
#include <string.h>
#include <stdlib.h>
#include <openssl/evp.h>

#define OUTLEN 16

/* ---- Internal helpers ---- */

static void aes_ecb_encrypt(const uint8_t *key, int keylen,
                            const uint8_t *in, uint8_t *out) {
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    const EVP_CIPHER *cipher = NULL;
    switch (keylen) {
        case 16: cipher = EVP_aes_128_ecb(); break;
        case 24: cipher = EVP_aes_192_ecb(); break;
        case 32: cipher = EVP_aes_256_ecb(); break;
        default: EVP_CIPHER_CTX_free(ctx); return;
    }
    EVP_EncryptInit_ex(ctx, cipher, NULL, key, NULL);
    EVP_CIPHER_CTX_set_padding(ctx, 0);
    int outlen = 0;
    EVP_EncryptUpdate(ctx, out, &outlen, in, OUTLEN);
    int finlen = 0;
    EVP_EncryptFinal_ex(ctx, out + outlen, &finlen);
    EVP_CIPHER_CTX_free(ctx);
}

static void xor_bytes(uint8_t *out, const uint8_t *a,
                      const uint8_t *b, size_t len) {
    for (size_t i = 0; i < len; i++)
        out[i] = a[i] ^ b[i];
}

static void inc_v(uint8_t *v) {
    for (int i = OUTLEN - 1; i >= 0; i--) {
        if (++v[i] != 0) break;
    }
}

/* ---- BCC (Section 10.3.3) ---- */

static void bcc_func(const uint8_t *bcc_key, int keylen,
                     const uint8_t *data, size_t data_len,
                     uint8_t *output) {
    uint8_t chaining[OUTLEN];
    uint8_t temp[OUTLEN];
    memset(chaining, 0, OUTLEN);
    size_t num_blocks = data_len / OUTLEN;
    for (size_t i = 0; i < num_blocks; i++) {
        xor_bytes(temp, chaining, data + i * OUTLEN, OUTLEN);
        aes_ecb_encrypt(bcc_key, keylen, temp, chaining);
    }
    memcpy(output, chaining, OUTLEN);
}

/* ---- Block_Cipher_df (Section 10.3.2) ---- */

static int block_cipher_df(int keylen,
                           const uint8_t *input_string, size_t input_len,
                           uint8_t *output, size_t output_len) {
    int seedlen = keylen + OUTLEN;

    /* Build S = L || N || input_string || 0x80 || zero-pad */
    size_t s_content = 4 + 4 + input_len + 1;
    size_t pad = OUTLEN - (s_content % OUTLEN);
    if (pad == OUTLEN) pad = 0;
    size_t s_len = s_content + pad;

    uint8_t *S = (uint8_t *)calloc(s_len, 1);
    if (!S) return -1;

    /* Encode L and N as 32-bit integers into S */
    uint32_t L = (uint32_t)input_len;
    uint32_t N = (uint32_t)output_len;
    S[0] = (uint8_t)((L)       & 0xFF);
    S[1] = (uint8_t)((L >> 8)  & 0xFF);
    S[2] = (uint8_t)((L >> 16) & 0xFF);
    S[3] = (uint8_t)((L >> 24) & 0xFF);
    S[4] = (uint8_t)((N)       & 0xFF);
    S[5] = (uint8_t)((N >> 8)  & 0xFF);
    S[6] = (uint8_t)((N >> 16) & 0xFF);
    S[7] = (uint8_t)((N >> 24) & 0xFF);

    memcpy(S + 8, input_string, input_len);
    S[8 + input_len] = 0x80;

    /* K = 0x00, 0x01, 0x02, ..., keylen-1 */
    uint8_t K[32];
    for (int i = 0; i < keylen; i++) K[i] = (uint8_t)i;

    /* Compute temp via BCC iterations */
    uint8_t temp[48]; /* max seedlen = 48 for AES-256 */
    size_t temp_pos = 0;
    int counter = 0;

    while (temp_pos < (size_t)seedlen) {
        size_t iv_s_len = OUTLEN + s_len;
        uint8_t *iv_s = (uint8_t *)calloc(iv_s_len, 1);
        if (!iv_s) { free(S); return -1; }

        /* IV = counter (big-endian 32-bit) || zeros */
        iv_s[0] = (uint8_t)((counter >> 24) & 0xFF);
        iv_s[1] = (uint8_t)((counter >> 16) & 0xFF);
        iv_s[2] = (uint8_t)((counter >> 8)  & 0xFF);
        iv_s[3] = (uint8_t)(counter & 0xFF);
        memcpy(iv_s + OUTLEN, S, s_len);

        uint8_t bcc_out[OUTLEN];
        bcc_func(K, keylen, iv_s, iv_s_len, bcc_out);
        memcpy(temp + temp_pos, bcc_out, OUTLEN);
        temp_pos += OUTLEN;
        counter++;
        free(iv_s);
    }

    free(S);

    /* Extract derived key and X from temp */
    uint8_t derived_key[32];
    uint8_t X[OUTLEN];
    memcpy(derived_key, temp, keylen);
    memcpy(X, temp + keylen, OUTLEN);

    /* Generate output blocks using derived_key */
    size_t out_pos = 0;
    uint8_t enc_out[OUTLEN];
    while (out_pos < output_len) {
        aes_ecb_encrypt(derived_key, keylen, X, enc_out);
        memcpy(X, enc_out, OUTLEN);
        size_t to_copy = output_len - out_pos;
        if (to_copy > OUTLEN) to_copy = OUTLEN;
        memcpy(output + out_pos, X, to_copy);
        out_pos += OUTLEN;
    }

    return 0;
}

/* ---- CTR_DRBG_Update (Section 10.2.1.2) ---- */

static void ctr_drbg_update_internal(CTR_DRBG_CTX *ctx,
                                     const uint8_t *provided_data) {
    uint8_t temp[48]; /* max seedlen */
    size_t temp_pos = 0;

    uint8_t v_work[OUTLEN];
    memcpy(v_work, ctx->v, OUTLEN);

    while (temp_pos < (size_t)ctx->seedlen) {
        inc_v(v_work);
        aes_ecb_encrypt(ctx->key, ctx->keylen, v_work, temp + temp_pos);
        temp_pos += OUTLEN;
    }

    xor_bytes(temp, temp, provided_data, ctx->seedlen);

    memcpy(ctx->key, temp, ctx->keylen);
    memcpy(ctx->v, temp + ctx->keylen, OUTLEN);
}

/* ---- Public API ---- */

void ctr_drbg_init(CTR_DRBG_CTX *ctx, int keylen, int use_df) {
    memset(ctx, 0, sizeof(*ctx));
    ctx->keylen = keylen;
    ctx->seedlen = keylen + OUTLEN;
    ctx->use_df = use_df;
}

int ctr_drbg_instantiate(CTR_DRBG_CTX *ctx,
                         const uint8_t *entropy, size_t entropy_len,
                         const uint8_t *nonce, size_t nonce_len,
                         const uint8_t *pers, size_t pers_len) {
    uint8_t seed_material[48];
    memset(seed_material, 0, sizeof(seed_material));

    if (ctx->use_df) {
        size_t total_len = entropy_len + nonce_len + pers_len;
        uint8_t *combined = (uint8_t *)malloc(total_len > 0 ? total_len : 1);
        if (!combined) return -1;
        memcpy(combined, entropy, entropy_len);
        if (nonce_len > 0)
            memcpy(combined + entropy_len, nonce, nonce_len);
        if (pers_len > 0)
            memcpy(combined + entropy_len + nonce_len, pers, pers_len);

        block_cipher_df(ctx->keylen, combined, total_len,
                        seed_material, ctx->seedlen);
        free(combined);
    } else {
        /* No df: entropy_input length == seedlen */
        size_t elen = entropy_len < (size_t)ctx->seedlen
                      ? entropy_len : (size_t)ctx->seedlen;
        memcpy(seed_material, entropy, elen);

        if (pers_len > 0) {
            uint8_t ps_padded[48];
            memset(ps_padded, 0, sizeof(ps_padded));
            size_t copy_len = pers_len < (size_t)ctx->seedlen
                              ? pers_len : (size_t)ctx->seedlen;
            /* Copy personalization string in reversed byte order */
            size_t j;
            for (j = 0; j < copy_len; j++)
                ps_padded[j] = pers[copy_len - 1 - j];
            xor_bytes(seed_material, seed_material, ps_padded, ctx->seedlen);
        }
    }

    memset(ctx->key, 0, ctx->keylen);
    memset(ctx->v, 0, OUTLEN);

    ctr_drbg_update_internal(ctx, seed_material);

    return 0;
}

int ctr_drbg_generate(CTR_DRBG_CTX *ctx,
                      uint8_t *output, size_t output_len,
                      const uint8_t *additional, size_t additional_len) {
    uint8_t processed_ai[48];
    memset(processed_ai, 0, sizeof(processed_ai));

    if (additional && additional_len > 0) {
        if (ctx->use_df) {
            block_cipher_df(ctx->keylen, additional, additional_len,
                            processed_ai, ctx->seedlen);
        } else {
            size_t copy_len = additional_len < (size_t)ctx->seedlen
                              ? additional_len : (size_t)ctx->seedlen;
            memcpy(processed_ai, additional, copy_len);
        }
        ctr_drbg_update_internal(ctx, processed_ai);
    }

    /* Generate output blocks */
    size_t out_pos = 0;
    while (out_pos < output_len) {
        inc_v(ctx->v);
        uint8_t block[OUTLEN];
        aes_ecb_encrypt(ctx->key, ctx->keylen, ctx->v, block);
        size_t to_copy = output_len - out_pos;
        if (to_copy > OUTLEN) to_copy = OUTLEN;
        memcpy(output + out_pos, block, to_copy);
        out_pos += OUTLEN;
    }

    /* Post-generate state update */
    ctr_drbg_update_internal(ctx, processed_ai);

    return 0;
}

void ctr_drbg_get_state(const CTR_DRBG_CTX *ctx,
                        uint8_t *key_out, uint8_t *v_out) {
    if (key_out) memcpy(key_out, ctx->key, ctx->keylen);
    if (v_out) memcpy(v_out, ctx->v, OUTLEN);
}
