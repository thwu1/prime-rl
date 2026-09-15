/*
 * hybrid_kem.c — Hybrid dual-KEM combining ML-KEM-512 and ML-KEM-1024.
 *
 * The combined shared secret is the byte-wise XOR of the two individual
 * 32-byte shared secrets. This provides security as long as at least one
 * of the two KEM constructions remains unbroken.
 *
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <oqs/oqs.h>

#define SS_LEN 32

int main(void) {
    int ret = 1;
    OQS_init();

    OQS_KEM *kem1 = OQS_KEM_new("ML-KEM-512");
    OQS_KEM *kem2 = OQS_KEM_new("ML-KEM-1024");
    if (!kem1 || !kem2) {
        fprintf(stderr, "KEM instantiation failed\n");
        goto free_kems;
    }

    uint8_t *pk1 = malloc(kem1->length_public_key);
    uint8_t *sk1 = malloc(kem1->length_secret_key);
    uint8_t *ct1 = malloc(kem1->length_ciphertext);
    uint8_t *ss1_enc = malloc(kem1->length_shared_secret);
    uint8_t *ss1_dec = malloc(kem1->length_shared_secret);

    uint8_t *pk2 = malloc(kem2->length_public_key);
    uint8_t *sk2 = malloc(kem2->length_secret_key);
    uint8_t *ct2 = malloc(kem2->length_ciphertext);
    uint8_t *ss2_enc = malloc(kem2->length_shared_secret);
    uint8_t *ss2_dec = malloc(kem2->length_shared_secret);

    if (!pk1 || !sk1 || !ct1 || !ss1_enc || !ss1_dec ||
        !pk2 || !sk2 || !ct2 || !ss2_enc || !ss2_dec) {
        fprintf(stderr, "Memory allocation failed\n");
        goto free_bufs;
    }

    uint8_t combined_enc[SS_LEN], combined_dec[SS_LEN];
    int success = 0;
    OQS_STATUS rc;

    /* Alice generates keypairs for both KEMs */
    rc = OQS_KEM_keypair(kem1, pk1, sk1);
    if (rc != OQS_SUCCESS) { fprintf(stderr, "keypair1 failed\n"); goto output; }
    rc = OQS_KEM_keypair(kem2, pk2, sk2);
    if (rc != OQS_SUCCESS) { fprintf(stderr, "keypair2 failed\n"); goto output; }

    /* Bob encapsulates with both public keys */
    rc = OQS_KEM_encaps(kem1, ct1, ss1_enc, pk1);
    if (rc != OQS_SUCCESS) { fprintf(stderr, "encaps1 failed\n"); goto output; }
    rc = OQS_KEM_encaps(kem2, ct2, ss2_enc, pk2);
    if (rc != OQS_SUCCESS) { fprintf(stderr, "encaps2 failed\n"); goto output; }

    /* Alice decapsulates both ciphertexts */
    rc = OQS_KEM_decaps(kem1, ss1_dec, ct1, sk1);
    if (rc != OQS_SUCCESS) { fprintf(stderr, "decaps1 failed\n"); goto output; }
    rc = OQS_KEM_decaps(kem2, ss2_dec, ct2, sk2);
    if (rc != OQS_SUCCESS) { fprintf(stderr, "decaps2 failed\n"); goto output; }

    /* XOR shared secrets to produce combined secret */
    for (int i = 0; i < SS_LEN; i++) {
        combined_enc[i] = ss1_enc[i] ^ ss2_enc[i];
        combined_dec[i] = ss1_dec[i] ^ ss2_dec[i];
    }

    success = (memcmp(combined_enc, combined_dec, SS_LEN) == 0);

output:
    printf("HYBRID_KEM_%s\n", success ? "SUCCESS" : "FAILURE");

    {
        FILE *f = fopen("/app/output/hybrid_result.json", "w");
        if (f) {
            fprintf(f, "{\n");
            fprintf(f, "  \"algorithms\": [\"%s\", \"%s\"],\n",
                    kem1->method_name, kem2->method_name);
            fprintf(f, "  \"success\": %s,\n", success ? "true" : "false");
            fprintf(f, "  \"combined_pk_bytes\": %zu,\n",
                    kem1->length_public_key + kem2->length_public_key);
            fprintf(f, "  \"combined_ct_bytes\": %zu,\n",
                    kem1->length_ciphertext + kem2->length_ciphertext);
            fprintf(f, "  \"ss_bytes\": %d\n", SS_LEN);
            fprintf(f, "}\n");
            fclose(f);
        }
    }

    ret = success ? 0 : 1;

free_bufs:
    free(pk1); free(sk1); free(ct1); free(ss1_enc); free(ss1_dec);
    free(pk2); free(sk2); free(ct2); free(ss2_enc); free(ss2_dec);
free_kems:
    OQS_KEM_free(kem1);
    OQS_KEM_free(kem2);
    OQS_destroy();
    return ret;
}
