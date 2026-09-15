/*
 * sig_matrix.c — Signature verification matrix for ML-DSA-{44,65,87}.
 *
 * For each algorithm: generate two keypairs (A, B), sign with A, verify
 * with A's public key (must succeed) and B's public key (must fail).
 * Reports parameters and NIST security levels.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <oqs/oqs.h>

#define NUM_ALGS 3
#define MSG "NIST Post-Quantum Cryptography Standardization"

int main(void) {
    OQS_init();

    const char *alg_names[NUM_ALGS] = {"ML-DSA-44", "ML-DSA-65", "ML-DSA-87"};
    OQS_SIG *sigs[NUM_ALGS] = {NULL};
    int ok = 1;

    for (int i = 0; i < NUM_ALGS; i++) {
        sigs[i] = OQS_SIG_new(alg_names[i]);
        if (!sigs[i]) {
            fprintf(stderr, "Failed to create %s\n", alg_names[i]);
            ok = 0;
            goto cleanup;
        }
    }

    FILE *f = fopen("/app/output/sig_matrix.json", "w");
    if (!f) {
        fprintf(stderr, "Cannot open output file\n");
        ok = 0;
        goto cleanup;
    }

    const uint8_t *message = (const uint8_t *)MSG;
    size_t message_len = strlen(MSG);

    fprintf(f, "{\n");
    fprintf(f, "  \"message\": \"%s\",\n", MSG);
    fprintf(f, "  \"results\": [\n");

    for (int i = 0; i < NUM_ALGS; i++) {
        OQS_SIG *sig = sigs[i];

        uint8_t *pk_a = malloc(sig->length_public_key);
        uint8_t *sk_a = malloc(sig->length_secret_key);
        uint8_t *pk_b = malloc(sig->length_public_key);
        uint8_t *sk_b = malloc(sig->length_secret_key);
        uint8_t *signature = malloc(sig->length_signature);
        size_t sig_len = 0;

        if (!pk_a || !sk_a || !pk_b || !sk_b || !signature) {
            fprintf(stderr, "Allocation failed for %s\n", alg_names[i]);
            free(pk_a); free(sk_a); free(pk_b); free(sk_b); free(signature);
            ok = 0;
            fclose(f);
            goto cleanup;
        }

        OQS_STATUS rc;

        /* Generate keypair A */
        rc = OQS_SIG_keypair(sig, pk_a, sk_a);
        if (rc != OQS_SUCCESS) {
            fprintf(stderr, "keypair A failed for %s\n", alg_names[i]);
            free(pk_a); free(sk_a); free(pk_b); free(sk_b); free(signature);
            ok = 0;
            fclose(f);
            goto cleanup;
        }

        /* Generate keypair B */
        rc = OQS_SIG_keypair(sig, pk_b, sk_b);
        if (rc != OQS_SUCCESS) {
            fprintf(stderr, "keypair B failed for %s\n", alg_names[i]);
            free(pk_a); free(sk_a); free(pk_b); free(sk_b); free(signature);
            ok = 0;
            fclose(f);
            goto cleanup;
        }

        /* Sign with A's secret key */
        rc = OQS_SIG_sign(sig, signature, &sig_len, message, message_len, sk_a);
        if (rc != OQS_SUCCESS) {
            fprintf(stderr, "sign failed for %s\n", alg_names[i]);
            free(pk_a); free(sk_a); free(pk_b); free(sk_b); free(signature);
            ok = 0;
            fclose(f);
            goto cleanup;
        }

        /* Verify with correct key (A's public key) — should succeed */
        OQS_STATUS verify_correct = OQS_SIG_verify(
            sig, message, message_len, signature, sig_len, pk_a);

        /* Verify with wrong key (B's public key) — should fail */
        OQS_STATUS verify_wrong = OQS_SIG_verify(
            sig, message, message_len, signature, sig_len, pk_b);

        fprintf(f, "    {\n");
        fprintf(f, "      \"algorithm\": \"%s\",\n", sig->method_name);
        fprintf(f, "      \"correct_key_verify\": %s,\n",
                verify_correct == OQS_SUCCESS ? "true" : "false");
        fprintf(f, "      \"wrong_key_verify\": %s,\n",
                verify_wrong == OQS_SUCCESS ? "true" : "false");
        fprintf(f, "      \"pk_bytes\": %zu,\n", sig->length_public_key);
        fprintf(f, "      \"sig_bytes\": %zu,\n", sig->length_signature);
        fprintf(f, "      \"nist_level\": %d\n", sig->claimed_nist_level);
        fprintf(f, "    }%s\n", (i < NUM_ALGS - 1) ? "," : "");

        free(pk_a); free(sk_a); free(pk_b); free(sk_b); free(signature);
    }

    fprintf(f, "  ]\n");
    fprintf(f, "}\n");
    fclose(f);

    printf("SIG_MATRIX_COMPLETE\n");

cleanup:
    for (int i = 0; i < NUM_ALGS; i++) {
        OQS_SIG_free(sigs[i]);
    }
    OQS_destroy();
    return ok ? 0 : 1;
}
