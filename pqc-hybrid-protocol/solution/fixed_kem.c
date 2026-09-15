/*
 * fixed_kem.c — Corrected ML-KEM-768 key exchange program.
 *
 * Fixes applied:
 *   1. Added OQS_init() / OQS_destroy() for proper library lifecycle
 *   2. Algorithm name corrected: "MLKEM768" -> "ML-KEM-768"
 *   3. Secret key buffer uses length_secret_key (not length_public_key)
 *   4. Keypair generation moved before encapsulation
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <oqs/oqs.h>

int main(void) {
    OQS_init();

    OQS_KEM *kem = OQS_KEM_new("ML-KEM-768");
    if (kem == NULL) {
        fprintf(stderr, "KEM instantiation failed\n");
        OQS_destroy();
        return 1;
    }

    uint8_t *pk  = malloc(kem->length_public_key);
    uint8_t *sk  = malloc(kem->length_secret_key);
    uint8_t *ct  = malloc(kem->length_ciphertext);
    uint8_t *sse = malloc(kem->length_shared_secret);
    uint8_t *ssd = malloc(kem->length_shared_secret);

    if (!pk || !sk || !ct || !sse || !ssd) {
        fprintf(stderr, "Memory allocation failed\n");
        OQS_KEM_free(kem);
        OQS_destroy();
        return 1;
    }

    OQS_STATUS rc;

    rc = OQS_KEM_keypair(kem, pk, sk);
    if (rc != OQS_SUCCESS) {
        fprintf(stderr, "Key generation failed\n");
        goto cleanup;
    }

    rc = OQS_KEM_encaps(kem, ct, sse, pk);
    if (rc != OQS_SUCCESS) {
        fprintf(stderr, "Encapsulation failed\n");
        goto cleanup;
    }

    rc = OQS_KEM_decaps(kem, ssd, ct, sk);
    if (rc != OQS_SUCCESS) {
        fprintf(stderr, "Decapsulation failed\n");
        goto cleanup;
    }

    if (memcmp(sse, ssd, kem->length_shared_secret) == 0) {
        printf("KEM_EXCHANGE_SUCCESS\n");
    } else {
        printf("KEM_EXCHANGE_FAILURE\n");
    }

    FILE *f = fopen("/app/output/kem_result.json", "w");
    if (f) {
        fprintf(f, "{\"algorithm\":\"%s\",\"pk_bytes\":%zu,\"ct_bytes\":%zu,\"ss_bytes\":%zu}\n",
                kem->method_name, kem->length_public_key,
                kem->length_ciphertext, kem->length_shared_secret);
        fclose(f);
    }

cleanup:
    free(pk); free(sk); free(ct); free(sse); free(ssd);
    OQS_KEM_free(kem);
    OQS_destroy();
    return 0;
}
