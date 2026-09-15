/*
 * monty_check.c - Montgomery representation parameter calculator
 * Computes correct Montgomery arithmetic parameters for a given prime
 * using OpenSSL BIGNUM for arbitrary precision.
 *
 * Compile: gcc -o monty_check monty_check.c -lcrypto
 * Usage:   ./monty_check <prime_hex> <word_bits>
 *
 */

#include <openssl/bn.h>
#include <openssl/crypto.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[]) {
    if (argc != 3) {
        fprintf(stderr, "Montgomery representation parameter calculator\n");
        fprintf(stderr, "Usage: %s <prime_hex> <word_bits>\n", argv[0]);
        fprintf(stderr, "  prime_hex : prime modulus in hexadecimal (0x prefix optional)\n");
        fprintf(stderr, "  word_bits : machine word size in bits (e.g. 64)\n");
        return 1;
    }

    const char *hex_input = argv[1];
    if (hex_input[0] == '0' && (hex_input[1] == 'x' || hex_input[1] == 'X'))
        hex_input += 2;

    BIGNUM *p = NULL;
    if (!BN_hex2bn(&p, hex_input)) {
        fprintf(stderr, "Error: invalid hexadecimal value for prime\n");
        return 1;
    }

    int wlen = atoi(argv[2]);
    if (wlen <= 0 || wlen > 512) {
        fprintf(stderr, "Error: word_bits must be between 1 and 512\n");
        BN_free(p);
        return 1;
    }

    int bitlen = BN_num_bits(p);
    int pbitlen = ((bitlen + wlen - 1) / wlen) * wlen;

    BN_CTX *ctx = BN_CTX_new();
    BIGNUM *r = BN_new();
    BIGNUM *r2 = BN_new();
    BIGNUM *tmp = BN_new();
    BIGNUM *wmod = BN_new();
    BIGNUM *p_low = BN_new();
    BIGNUM *p_inv = BN_new();
    BIGNUM *mpinv = BN_new();

    /* r = 2^pbitlen mod p */
    BN_zero(tmp);
    BN_set_bit(tmp, pbitlen);
    BN_mod(r, tmp, p, ctx);

    /* r_square = 2^(2*pbitlen) mod p */
    BN_zero(tmp);
    BN_set_bit(tmp, 2 * pbitlen);
    BN_mod(r2, tmp, p, ctx);

    /* mpinv = 2^wlen - modinv(p mod 2^wlen, 2^wlen) */
    BN_zero(wmod);
    BN_set_bit(wmod, wlen);
    BN_mod(p_low, p, wmod, ctx);
    BN_mod_inverse(p_inv, p_low, wmod, ctx);
    BN_sub(mpinv, wmod, p_inv);
    BN_mod(mpinv, mpinv, wmod, ctx);

    char *r_hex = BN_bn2hex(r);
    char *r2_hex = BN_bn2hex(r2);
    char *mpinv_hex = BN_bn2hex(mpinv);

    printf("prime_bits=%d\n", bitlen);
    printf("pbitlen=%d\n", pbitlen);
    printf("r=0x%s\n", r_hex);
    printf("r_square=0x%s\n", r2_hex);
    printf("mpinv=0x%s\n", mpinv_hex);

    OPENSSL_free(r_hex);
    OPENSSL_free(r2_hex);
    OPENSSL_free(mpinv_hex);
    BN_free(p);
    BN_free(r);
    BN_free(r2);
    BN_free(tmp);
    BN_free(wmod);
    BN_free(p_low);
    BN_free(p_inv);
    BN_free(mpinv);
    BN_CTX_free(ctx);

    return 0;
}
