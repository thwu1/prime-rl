 */

/*
 * Fixed PQC Audit Tool
 *
 * Fixes applied vs. the buggy /app/pqc-migration/pqc_audit.c:
 *   1. KEM section: added OQS_KEM_alg_is_enabled() check and NULL guard
 *      on OQS_KEM_new() — the original iterated all OQS_KEM_alg_count()
 *      slots (including disabled algorithms), causing NULL dereference.
 *   2. SIG section: replaced hardcoded "Dilithium2/3/5" names (removed in
 *      liboqs 0.15) with proper iteration via OQS_SIG_alg_identifier() +
 *      OQS_SIG_alg_is_enabled().
 *   3. SIG section: fixed signature buffer allocation from
 *      sig->length_public_key to sig->length_signature (heap overflow).
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <oqs/oqs.h>

static void write_kem_audit(FILE *audit_f, FILE *kem_f) {
    int total = OQS_KEM_alg_count();
    int first_audit = 1;
    int first_kem = 1;

    fprintf(kem_f, "[\n");

    for (int i = 0; i < total; i++) {
        const char *name = OQS_KEM_alg_identifier(i);
        if (!OQS_KEM_alg_is_enabled(name)) continue;

        OQS_KEM *kem = OQS_KEM_new(name);
        if (!kem) continue;

        /* Audit entry */
        if (!first_audit) fprintf(audit_f, ",\n");
        first_audit = 0;
        fprintf(audit_f,
            "  {\"name\": \"%s\", \"type\": \"KEM\", \"nist_level\": %d, "
            "\"public_key_length\": %zu, \"secret_key_length\": %zu, "
            "\"ciphertext_length\": %zu, \"shared_secret_length\": %zu}",
            kem->method_name,
            kem->claimed_nist_level,
            kem->length_public_key,
            kem->length_secret_key,
            kem->length_ciphertext,
            kem->length_shared_secret);

        /* Round-trip verification */
        uint8_t *pk  = malloc(kem->length_public_key);
        uint8_t *sk  = malloc(kem->length_secret_key);
        uint8_t *ct  = malloc(kem->length_ciphertext);
        uint8_t *ss1 = malloc(kem->length_shared_secret);
        uint8_t *ss2 = malloc(kem->length_shared_secret);

        int ok = 0;
        if (pk && sk && ct && ss1 && ss2) {
            OQS_STATUS r1 = OQS_KEM_keypair(kem, pk, sk);
            OQS_STATUS r2 = OQS_KEM_encaps(kem, ct, ss1, pk);
            OQS_STATUS r3 = OQS_KEM_decaps(kem, ss2, ct, sk);
            ok = (r1 == OQS_SUCCESS && r2 == OQS_SUCCESS && r3 == OQS_SUCCESS &&
                  memcmp(ss1, ss2, kem->length_shared_secret) == 0);
        }

        if (!first_kem) fprintf(kem_f, ",\n");
        first_kem = 0;
        fprintf(kem_f, "  {\"name\": \"%s\", \"success\": %s, \"shared_secrets_match\": %s}",
                name, ok ? "true" : "false", ok ? "true" : "false");

        free(pk); free(sk); free(ct); free(ss1); free(ss2);
        OQS_KEM_free(kem);
    }

    fprintf(kem_f, "\n]\n");
}

static int write_sig_audit(FILE *audit_f, FILE *sig_f, int need_comma) {
    int total = OQS_SIG_alg_count();
    int first_sig = 1;
    const char *msg = "Post-quantum cryptography verification test message";
    size_t msg_len = strlen(msg);

    fprintf(sig_f, "[\n");

    for (int i = 0; i < total; i++) {
        const char *name = OQS_SIG_alg_identifier(i);
        if (!OQS_SIG_alg_is_enabled(name)) continue;

        OQS_SIG *sig = OQS_SIG_new(name);
        if (!sig) continue;

        /* Audit entry */
        if (need_comma) fprintf(audit_f, ",\n");
        need_comma = 1;
        fprintf(audit_f,
            "  {\"name\": \"%s\", \"type\": \"SIG\", \"nist_level\": %d, "
            "\"public_key_length\": %zu, \"secret_key_length\": %zu, "
            "\"signature_length\": %zu}",
            sig->method_name,
            sig->claimed_nist_level,
            sig->length_public_key,
            sig->length_secret_key,
            sig->length_signature);

        /* Round-trip verification */
        uint8_t *pk  = malloc(sig->length_public_key);
        uint8_t *sk  = malloc(sig->length_secret_key);
        uint8_t *sigbuf = malloc(sig->length_signature);
        size_t siglen = 0;

        int ok = 0;
        if (pk && sk && sigbuf) {
            OQS_STATUS r1 = OQS_SIG_keypair(sig, pk, sk);
            OQS_STATUS r2 = OQS_SIG_sign(sig, sigbuf, &siglen,
                                          (const uint8_t *)msg, msg_len, sk);
            OQS_STATUS r3 = OQS_SIG_verify(sig, (const uint8_t *)msg, msg_len,
                                            sigbuf, siglen, pk);
            ok = (r1 == OQS_SUCCESS && r2 == OQS_SUCCESS && r3 == OQS_SUCCESS);
        }

        if (!first_sig) fprintf(sig_f, ",\n");
        first_sig = 0;
        fprintf(sig_f, "  {\"name\": \"%s\", \"success\": %s, \"signature_valid\": %s}",
                name, ok ? "true" : "false", ok ? "true" : "false");

        free(pk); free(sk); free(sigbuf);
        OQS_SIG_free(sig);
    }

    fprintf(sig_f, "\n]\n");
    return need_comma;
}

int main(void) {
    FILE *audit_f = fopen("/app/output/algorithm_audit.json", "w");
    FILE *kem_f   = fopen("/app/output/kem_verification.json", "w");
    FILE *sig_f   = fopen("/app/output/sig_verification.json", "w");

    if (!audit_f || !kem_f || !sig_f) {
        fprintf(stderr, "Failed to open output files\n");
        return 1;
    }

    fprintf(audit_f, "[\n");

    write_kem_audit(audit_f, kem_f);

    int had_kem = 1;
    write_sig_audit(audit_f, sig_f, had_kem);

    fprintf(audit_f, "\n]\n");

    fclose(audit_f);
    fclose(kem_f);
    fclose(sig_f);

    printf("C audit complete.\n");
    return 0;
}
