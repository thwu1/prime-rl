/*
 * ACVP Module Wrapper — OpenSSL 3 (corrected)
 *
 * Implements NIST ACVP subprocess binary protocol.
 * Handles SHA2-256, HMAC-SHA2-256, AES-256-GCM, HKDF/SHA2-256,
 *         CMAC-AES-256, PBKDF2-HMAC-SHA256.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include <openssl/evp.h>
#include <openssl/kdf.h>
#include <openssl/params.h>
#include <openssl/core_names.h>

/* ---- Low-level I/O ---- */

static int read_exact(uint8_t *buf, size_t n) {
    size_t done = 0;
    while (done < n) {
        size_t r = fread(buf + done, 1, n - done, stdin);
        if (r == 0) return -1;
        done += r;
    }
    return 0;
}

static void write_u32le(uint32_t v) {
    uint8_t b[4] = {v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >> 24) & 0xff};
    fwrite(b, 1, 4, stdout);
}

static uint32_t decode_u32le(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* ---- ACVP framing ---- */

typedef struct {
    uint32_t  n;
    uint32_t *lens;
    uint8_t **data;
} acvp_msg;

static int acvp_read(acvp_msg *m) {
    uint8_t buf[4];
    if (read_exact(buf, 4) < 0) return -1;
    m->n = decode_u32le(buf);
    m->lens = calloc(m->n, sizeof(uint32_t));
    for (uint32_t i = 0; i < m->n; i++) {
        if (read_exact(buf, 4) < 0) { free(m->lens); return -1; }
        m->lens[i] = decode_u32le(buf);
    }
    m->data = calloc(m->n, sizeof(uint8_t *));
    for (uint32_t i = 0; i < m->n; i++) {
        m->data[i] = malloc(m->lens[i] + 1);
        if (m->lens[i] > 0 && read_exact(m->data[i], m->lens[i]) < 0) {
            for (uint32_t j = 0; j <= i; j++) free(m->data[j]);
            free(m->data); free(m->lens);
            return -1;
        }
        m->data[i][m->lens[i]] = '\0';
    }
    return 0;
}

static void acvp_write(uint32_t n, const uint8_t **d, const uint32_t *l) {
    write_u32le(n);
    for (uint32_t i = 0; i < n; i++) write_u32le(l[i]);
    for (uint32_t i = 0; i < n; i++) {
        if (l[i] > 0) fwrite(d[i], 1, l[i], stdout);
    }
    fflush(stdout);
}

static void acvp_free(acvp_msg *m) {
    for (uint32_t i = 0; i < m->n; i++) free(m->data[i]);
    free(m->data);
    free(m->lens);
}

static void respond1(const uint8_t *a, uint32_t la) {
    const uint8_t *d[] = {a};
    uint32_t l[] = {la};
    acvp_write(1, d, l);
}

static void respond2(const uint8_t *a, uint32_t la,
                     const uint8_t *b, uint32_t lb) {
    const uint8_t *d[] = {a, b};
    uint32_t l[] = {la, lb};
    acvp_write(2, d, l);
}

/* ---- Command handlers ---- */

static void cmd_get_config(void) {
    const char *j =
        "[{\"algorithm\":\"SHA2-256\"},{\"algorithm\":\"HMAC-SHA2-256\"},"
         "{\"algorithm\":\"AES-256-GCM\"},{\"algorithm\":\"HKDF/SHA2-256\"},"
         "{\"algorithm\":\"CMAC-AES-256\"},{\"algorithm\":\"PBKDF2-HMAC-SHA256\"}]";
    respond1((const uint8_t *)j, (uint32_t)strlen(j));
}

static void cmd_sha256(acvp_msg *m) {
    uint8_t digest[32];
    unsigned int dlen = 32;
    EVP_Digest(m->data[1], m->lens[1], digest, &dlen, EVP_sha256(), NULL);
    respond1(digest, dlen);
}

static void cmd_hmac_sha256(acvp_msg *m) {
    /* ACVP order: data[1] = message, data[2] = key */
    uint8_t mac_buf[32];
    size_t mac_len = sizeof(mac_buf);

    EVP_MAC *mac = EVP_MAC_fetch(NULL, "HMAC", NULL);
    EVP_MAC_CTX *mctx = EVP_MAC_CTX_new(mac);

    char digest_name[] = "SHA256";
    OSSL_PARAM params[2];
    params[0] = OSSL_PARAM_construct_utf8_string(OSSL_MAC_PARAM_DIGEST,
                                                  digest_name, 0);
    params[1] = OSSL_PARAM_construct_end();

    /* data[2] is the key, data[1] is the message */
    EVP_MAC_init(mctx, m->data[2], m->lens[2], params);
    EVP_MAC_update(mctx, m->data[1], m->lens[1]);
    EVP_MAC_final(mctx, mac_buf, &mac_len, sizeof(mac_buf));

    EVP_MAC_CTX_free(mctx);
    EVP_MAC_free(mac);
    respond1(mac_buf, (uint32_t)mac_len);
}

static void cmd_aes_gcm_seal(acvp_msg *m) {
    uint32_t tag_len   = decode_u32le(m->data[1]);
    uint8_t *key       = m->data[2];
    uint8_t *pt        = m->data[3];
    uint32_t pt_len    = m->lens[3];
    uint8_t *nonce     = m->data[4];
    uint32_t nonce_len = m->lens[4];
    uint8_t *ad        = m->data[5];
    uint32_t ad_len    = m->lens[5];

    uint32_t out_cap = pt_len + tag_len;
    uint8_t *out = calloc(1, out_cap > 0 ? out_cap : 1);

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    EVP_EncryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL);
    EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, (int)nonce_len, NULL);
    EVP_EncryptInit_ex(ctx, NULL, NULL, key, nonce);

    int len;
    if (ad_len > 0)
        EVP_EncryptUpdate(ctx, NULL, &len, ad, (int)ad_len);

    int ct_len = 0;
    if (pt_len > 0) {
        /* Ciphertext at the start of buffer */
        EVP_EncryptUpdate(ctx, out, &len, pt, (int)pt_len);
        ct_len = len;
    }
    EVP_EncryptFinal_ex(ctx, out + ct_len, &len);
    ct_len += len;

    /* Tag at the end: ct || tag */
    EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_GET_TAG, (int)tag_len, out + ct_len);
    EVP_CIPHER_CTX_free(ctx);

    respond1(out, (uint32_t)(ct_len + tag_len));
    free(out);
}

static void cmd_aes_gcm_open(acvp_msg *m) {
    uint32_t tag_len     = decode_u32le(m->data[1]);
    uint8_t *key         = m->data[2];
    uint8_t *ct_tag      = m->data[3];
    uint32_t ct_tag_len  = m->lens[3];
    uint8_t *nonce       = m->data[4];
    uint32_t nonce_len   = m->lens[4];
    uint8_t *ad          = m->data[5];
    uint32_t ad_len      = m->lens[5];

    if (ct_tag_len < tag_len) {
        uint8_t f = 0x00;
        respond2(&f, 1, (const uint8_t *)"", 0);
        return;
    }

    uint32_t ct_len = ct_tag_len - tag_len;
    uint8_t *pt_buf = calloc(1, ct_len > 0 ? ct_len : 1);

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    EVP_DecryptInit_ex(ctx, EVP_aes_256_gcm(), NULL, NULL, NULL);
    EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_IVLEN, (int)nonce_len, NULL);
    EVP_DecryptInit_ex(ctx, NULL, NULL, key, nonce);

    int len;
    if (ad_len > 0)
        EVP_DecryptUpdate(ctx, NULL, &len, ad, (int)ad_len);

    int pt_out = 0;
    if (ct_len > 0) {
        /* Ciphertext at start: ct || tag layout */
        EVP_DecryptUpdate(ctx, pt_buf, &len, ct_tag, (int)ct_len);
        pt_out = len;
    }

    /* Tag at end of buffer */
    EVP_CIPHER_CTX_ctrl(ctx, EVP_CTRL_GCM_SET_TAG, (int)tag_len,
                        (void *)(ct_tag + ct_len));
    int ok = EVP_DecryptFinal_ex(ctx, pt_buf + pt_out, &len);
    EVP_CIPHER_CTX_free(ctx);

    if (ok > 0) {
        pt_out += len;
        uint8_t s = 0x01;
        respond2(&s, 1, pt_buf, (uint32_t)pt_out);
    } else {
        uint8_t f = 0x00;
        respond2(&f, 1, (const uint8_t *)"", 0);
    }
    free(pt_buf);
}

static void cmd_hkdf_sha256(acvp_msg *m) {
    uint8_t *ikm      = m->data[1];
    uint32_t ikm_len  = m->lens[1];
    uint8_t *salt     = m->data[2];
    uint32_t salt_len = m->lens[2];
    uint8_t *info     = m->data[3];
    uint32_t info_len = m->lens[3];
    uint32_t out_len  = decode_u32le(m->data[4]);

    uint8_t *okm = malloc(out_len);

    EVP_KDF *kdf = EVP_KDF_fetch(NULL, "HKDF", NULL);
    EVP_KDF_CTX *kctx = EVP_KDF_CTX_new(kdf);

    OSSL_PARAM params[5];
    int idx = 0;
    char digest_name[] = "SHA256";

    /* Default mode is EXTRACT_AND_EXPAND per RFC 5869 */
    params[idx++] = OSSL_PARAM_construct_utf8_string(OSSL_KDF_PARAM_DIGEST,
                                                      digest_name, 0);
    params[idx++] = OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_KEY,
                                                       (void *)ikm, ikm_len);
    if (salt_len > 0)
        params[idx++] = OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_SALT,
                                                           (void *)salt, salt_len);
    if (info_len > 0)
        params[idx++] = OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_INFO,
                                                           (void *)info, info_len);
    params[idx] = OSSL_PARAM_construct_end();

    EVP_KDF_derive(kctx, okm, out_len, params);

    EVP_KDF_CTX_free(kctx);
    EVP_KDF_free(kdf);

    respond1(okm, out_len);
    free(okm);
}

static void cmd_cmac_aes256(acvp_msg *m) {
    /* data[1]=out_len, data[2]=key(32B), data[3]=message */
    uint32_t out_len = decode_u32le(m->data[1]);
    uint8_t *key     = m->data[2];
    uint8_t *msg     = m->data[3];
    uint32_t msg_len = m->lens[3];

    uint8_t mac_buf[16];
    size_t mac_len = sizeof(mac_buf);

    EVP_MAC *mac = EVP_MAC_fetch(NULL, "CMAC", NULL);
    EVP_MAC_CTX *mctx = EVP_MAC_CTX_new(mac);

    /* CMAC requires a cipher parameter, not a digest */
    char cipher_name[] = "AES-256-CBC";
    OSSL_PARAM params[2];
    params[0] = OSSL_PARAM_construct_utf8_string(OSSL_MAC_PARAM_CIPHER,
                                                  cipher_name, 0);
    params[1] = OSSL_PARAM_construct_end();

    EVP_MAC_init(mctx, key, 32, params);
    EVP_MAC_update(mctx, msg, msg_len);
    EVP_MAC_final(mctx, mac_buf, &mac_len, sizeof(mac_buf));

    EVP_MAC_CTX_free(mctx);
    EVP_MAC_free(mac);

    uint32_t result_len = (out_len <= (uint32_t)mac_len) ? out_len : (uint32_t)mac_len;
    respond1(mac_buf, result_len);
}

static void cmd_pbkdf2_sha256(acvp_msg *m) {
    /* data[1]=password, data[2]=salt, data[3]=iterations, data[4]=out_len */
    uint8_t *password  = m->data[1];
    uint32_t pass_len  = m->lens[1];
    uint8_t *salt      = m->data[2];
    uint32_t salt_len  = m->lens[2];
    uint32_t iterations = decode_u32le(m->data[3]);
    uint32_t out_len    = decode_u32le(m->data[4]);

    uint8_t *okm = malloc(out_len);

    EVP_KDF *kdf = EVP_KDF_fetch(NULL, "PBKDF2", NULL);
    EVP_KDF_CTX *kctx = EVP_KDF_CTX_new(kdf);

    char digest_name[] = "SHA256";
    int pkcs5 = 1;  /* Allow arbitrary iteration counts and salt lengths */
    unsigned int iter_val = (unsigned int)iterations;

    OSSL_PARAM params[6];
    int idx = 0;
    params[idx++] = OSSL_PARAM_construct_utf8_string(OSSL_KDF_PARAM_DIGEST,
                                                      digest_name, 0);
    params[idx++] = OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_PASSWORD,
                                                       (void *)password, pass_len);
    params[idx++] = OSSL_PARAM_construct_octet_string(OSSL_KDF_PARAM_SALT,
                                                       (void *)salt, salt_len);
    params[idx++] = OSSL_PARAM_construct_uint(OSSL_KDF_PARAM_ITER, &iter_val);
    params[idx++] = OSSL_PARAM_construct_int(OSSL_KDF_PARAM_PKCS5, &pkcs5);
    params[idx] = OSSL_PARAM_construct_end();

    EVP_KDF_derive(kctx, okm, out_len, params);

    EVP_KDF_CTX_free(kctx);
    EVP_KDF_free(kdf);

    respond1(okm, out_len);
    free(okm);
}

/* ---- Main loop ---- */

int main(void) {
    for (;;) {
        acvp_msg req;
        if (acvp_read(&req) < 0) break;
        const char *cmd = (const char *)req.data[0];
        if      (strcmp(cmd, "getConfig")           == 0) cmd_get_config();
        else if (strcmp(cmd, "SHA2-256")            == 0) cmd_sha256(&req);
        else if (strcmp(cmd, "HMAC-SHA2-256")       == 0) cmd_hmac_sha256(&req);
        else if (strcmp(cmd, "AES-256-GCM/seal")    == 0) cmd_aes_gcm_seal(&req);
        else if (strcmp(cmd, "AES-256-GCM/open")    == 0) cmd_aes_gcm_open(&req);
        else if (strcmp(cmd, "HKDF/SHA2-256")       == 0) cmd_hkdf_sha256(&req);
        else if (strcmp(cmd, "CMAC-AES-256")        == 0) cmd_cmac_aes256(&req);
        else if (strcmp(cmd, "PBKDF2-HMAC-SHA256")  == 0) cmd_pbkdf2_sha256(&req);
        acvp_free(&req);
    }
    return 0;
}
