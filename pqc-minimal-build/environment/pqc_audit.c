/*
 * PQC Migration Audit Tool
 *
 * Enumerates post-quantum cryptographic algorithms available in liboqs,
 * verifies KEM key exchange and signature round-trips, and produces
 * JSON reports for compliance auditing.
 *
 * Output files:
 *   /app/output/algorithm_audit.json   - algorithm parameter catalog
 *   /app/output/kem_verification.json  - KEM encaps/decaps round-trip results
 *   /app/output/sig_verification.json  - signature sign/verify round-trip results
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <oqs/oqs.h>

/* Post-quantum signature algorithm names (CRYSTALS-Dilithium family) */
static const char *SIG_ALGO_NAMES[] = {
    "Dilithium2",
    "Dilithium3",
    "Dilithium5"
};
static const int NUM_SIG_ALGOS = 3;

static void write_kem_section(FILE *audit_f, FILE *kem_f) {
    int total = OQS_KEM_alg_count();
    int first_a = 1, first_k = 1;

    fprintf(kem_f, "[\n");

    for (int i = 0; i < total; i++) {
        const char *name = OQS_KEM_alg_identifier(i);
        OQS_KEM *kem = OQS_KEM_new(name);

        /* Audit entry */
        if (!first_a) fprintf(audit_f, ",\n");
        first_a = 0;
        fprintf(audit_f,
            "  {\"name\": \"%s\", \"type\": \"KEM\", \"nist_level\": %d, "
            "\"public_key_length\": %zu, \"secret_key_length\": %zu, "
            "\"ciphertext_length\": %zu, \"shared_secret_length\": %zu}",
            kem->method_name, kem->claimed_nist_level,
            kem->length_public_key, kem->length_secret_key,
            kem->length_ciphertext, kem->length_shared_secret);

        /* KEM round-trip: keypair → encaps → decaps → compare shared secrets */
        uint8_t *pk  = malloc(kem->length_public_key);
        uint8_t *sk  = malloc(kem->length_secret_key);
        uint8_t *ct  = malloc(kem->length_ciphertext);
        uint8_t *ss_enc = malloc(kem->length_shared_secret);
        uint8_t *ss_dec = malloc(kem->length_shared_secret);

        int success = 1, match = 0;
        if (OQS_KEM_keypair(kem, pk, sk) != OQS_SUCCESS) success = 0;
        if (success && OQS_KEM_encaps(kem, ct, ss_enc, pk) != OQS_SUCCESS) success = 0;
        if (success && OQS_KEM_decaps(kem, ss_dec, ct, sk) != OQS_SUCCESS) success = 0;
        if (success) match = (memcmp(ss_enc, ss_dec, kem->length_shared_secret) == 0);

        if (!first_k) fprintf(kem_f, ",\n");
        first_k = 0;
        fprintf(kem_f,
            "  {\"name\": \"%s\", \"success\": %s, \"shared_secrets_match\": %s}",
            name, success ? "true" : "false", match ? "true" : "false");

        free(pk); free(sk); free(ct); free(ss_enc); free(ss_dec);
        OQS_KEM_free(kem);
    }

    fprintf(kem_f, "\n]\n");
}

static void write_sig_section(FILE *audit_f, FILE *sig_f, int need_comma) {
    int first_s = 1;
    const char *test_msg = "PQC migration verification test message";
    size_t msg_len = strlen(test_msg);

    fprintf(sig_f, "[\n");

    for (int i = 0; i < NUM_SIG_ALGOS; i++) {
        OQS_SIG *sig = OQS_SIG_new(SIG_ALGO_NAMES[i]);
        if (!sig) {
            fprintf(stderr, "Warning: algorithm %s unavailable\n", SIG_ALGO_NAMES[i]);
            continue;
        }

        /* Audit entry */
        if (need_comma) fprintf(audit_f, ",\n");
        need_comma = 1;
        fprintf(audit_f,
            "  {\"name\": \"%s\", \"type\": \"SIG\", \"nist_level\": %d, "
            "\"public_key_length\": %zu, \"secret_key_length\": %zu, "
            "\"signature_length\": %zu}",
            sig->method_name, sig->claimed_nist_level,
            sig->length_public_key, sig->length_secret_key,
            sig->length_signature);

        /* Signature round-trip: keypair → sign → verify */
        uint8_t *pk     = malloc(sig->length_public_key);
        uint8_t *sk     = malloc(sig->length_secret_key);
        uint8_t *sigbuf = malloc(sig->length_public_key);  /* signature output buffer */
        size_t siglen = 0;

        int ok = 0;
        if (pk && sk && sigbuf) {
            OQS_STATUS r1 = OQS_SIG_keypair(sig, pk, sk);
            OQS_STATUS r2 = OQS_SIG_sign(sig, sigbuf, &siglen,
                                          (const uint8_t *)test_msg, msg_len, sk);
            OQS_STATUS r3 = OQS_SIG_verify(sig, (const uint8_t *)test_msg, msg_len,
                                            sigbuf, siglen, pk);
            ok = (r1 == OQS_SUCCESS && r2 == OQS_SUCCESS && r3 == OQS_SUCCESS);
        }

        if (!first_s) fprintf(sig_f, ",\n");
        first_s = 0;
        fprintf(sig_f,
            "  {\"name\": \"%s\", \"success\": %s, \"signature_valid\": %s}",
            SIG_ALGO_NAMES[i], ok ? "true" : "false", ok ? "true" : "false");

        free(pk); free(sk); free(sigbuf);
        OQS_SIG_free(sig);
    }

    fprintf(sig_f, "\n]\n");
}

int main(void) {
    OQS_init();

    FILE *audit_f = fopen("/app/output/algorithm_audit.json", "w");
    FILE *kem_f   = fopen("/app/output/kem_verification.json", "w");
    FILE *sig_f   = fopen("/app/output/sig_verification.json", "w");

    if (!audit_f || !kem_f || !sig_f) {
        fprintf(stderr, "Failed to open output files\n");
        return 1;
    }

    fprintf(audit_f, "[\n");

    write_kem_section(audit_f, kem_f);
    write_sig_section(audit_f, sig_f, 1);

    fprintf(audit_f, "\n]\n");

    fclose(audit_f);
    fclose(kem_f);
    fclose(sig_f);

    OQS_destroy();
    printf("PQC audit complete.\n");
    return 0;
}
