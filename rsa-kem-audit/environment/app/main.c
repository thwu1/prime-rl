/*
 * RSA-KEM command-line tool
 *
 * Usage:
 *   ./secure_kem keygen <bits> <pub.pem> <priv.pem>
 *   ./secure_kem encap  <pub.pem>
 *   ./secure_kem decap  <priv.pem> <ciphertext_file>
 */

#include "rsa_kem.h"
#include "util.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int cmd_keygen(int bits, const char *pubfile, const char *privfile)
{
    RSA *rsa = generate_rsa_keypair(bits);

    if (rsa == NULL) {
        fprintf(stderr, "Key generation failed\n");
        print_openssl_errors();
        return 1;
    }

    if (!save_rsa_keypair(rsa, pubfile, privfile)) {
        fprintf(stderr, "Failed to save key pair\n");
        RSA_free(rsa);
        return 1;
    }

    printf("Generated %d-bit RSA key pair\n", bits);
    printf("  Public key:  %s\n", pubfile);
    printf("  Private key: %s\n", privfile);

    RSA_free(rsa);
    return 0;
}

static int cmd_encapsulate(const char *pubfile)
{
    RSA *rsa = load_rsa_pubkey(pubfile);
    RSA_KEM_CTX *ctx = NULL;
    unsigned char *out = NULL, *secret = NULL;
    size_t outlen, secretlen;
    int nlen, rc = 1;

    if (rsa == NULL) {
        fprintf(stderr, "Failed to load public key from %s\n", pubfile);
        print_openssl_errors();
        return 1;
    }

    ctx = rsa_kem_ctx_new(rsa, RSA_KEM_OP_ENCAPSULATE);
    if (ctx == NULL) {
        fprintf(stderr, "Failed to create KEM context\n");
        goto done;
    }

    nlen = rsa_kem_get_size(ctx);
    out = OPENSSL_malloc(nlen);
    secret = OPENSSL_malloc(nlen);
    if (out == NULL || secret == NULL)
        goto done;

    if (rsasve_generate(ctx, out, &outlen, secret, &secretlen) != 1) {
        fprintf(stderr, "Encapsulation failed\n");
        print_openssl_errors();
        goto done;
    }

    print_hex("Ciphertext", out, outlen);
    print_hex("Shared secret", secret, secretlen);
    rc = 0;

done:
    if (secret != NULL) {
        OPENSSL_cleanse(secret, nlen);
        OPENSSL_free(secret);
    }
    OPENSSL_free(out);
    rsa_kem_ctx_free(ctx);
    RSA_free(rsa);
    return rc;
}

static void usage(const char *prog)
{
    fprintf(stderr,
            "Usage:\n"
            "  %s keygen <bits> <pub.pem> <priv.pem>\n"
            "  %s encap  <pub.pem>\n",
            prog, prog);
}

int main(int argc, char *argv[])
{
    if (argc < 2) {
        usage(argv[0]);
        return 1;
    }

    if (strcmp(argv[1], "keygen") == 0) {
        if (argc != 5) { usage(argv[0]); return 1; }
        return cmd_keygen(atoi(argv[2]), argv[3], argv[4]);
    }

    if (strcmp(argv[1], "encap") == 0) {
        if (argc != 3) { usage(argv[0]); return 1; }
        return cmd_encapsulate(argv[2]);
    }

    fprintf(stderr, "Unknown command: %s\n", argv[1]);
    usage(argv[0]);
    return 1;
}
