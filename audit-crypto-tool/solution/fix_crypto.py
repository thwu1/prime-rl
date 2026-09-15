#!/usr/bin/env python3
"""
Fix cryptographic vulnerabilities in /app/cryptvault.c.

Reads the buggy source, identifies 4 security issues by matching their
code patterns, applies targeted fixes, and writes the corrected source.

Vulnerabilities fixed:
  1. Password KDF: BLAKE2b (fast) -> Argon2id via crypto_pwhash (memory-hard)
  2. Nonce generation: deterministic from key -> random via randombytes_buf
  3. MAC verification: warning-only -> hard error with -1 return
  4. Large-file encryption: bare crypto_stream_xor -> crypto_secretstream with auth
"""

import sys
import os


def apply_fixes(source):
    """Apply all cryptographic fixes and return (fixed_source, num_fixes)."""
    fixes = 0

    # ------------------------------------------------------------------
    # Fix 1: Replace BLAKE2b-based password KDF with Argon2id
    # ------------------------------------------------------------------
    old_kdf = (
        "    crypto_generichash_state st;\n"
        "    crypto_generichash_init(&st, NULL, 0, crypto_secretbox_KEYBYTES);\n"
        "    crypto_generichash_update(&st, salt, SALT_LEN);\n"
        "    crypto_generichash_update(&st, (const unsigned char *)password,\n"
        "                              strlen(password));\n"
        "    crypto_generichash_final(&st, key, crypto_secretbox_KEYBYTES);\n"
        "    return 0;\n"
        "}"
    )
    new_kdf = (
        "    if (crypto_pwhash(key, crypto_secretbox_KEYBYTES,\n"
        "                      password, strlen(password), salt,\n"
        "                      crypto_pwhash_OPSLIMIT_MODERATE,\n"
        "                      crypto_pwhash_MEMLIMIT_MODERATE,\n"
        "                      crypto_pwhash_ALG_ARGON2ID13) != 0) {\n"
        '        fprintf(stderr, "Error: key derivation failed\\n");\n'
        "        return -1;\n"
        "    }\n"
        "    return 0;\n"
        "}"
    )
    if old_kdf in source:
        source = source.replace(old_kdf, new_kdf)
        fixes += 1
        print("[+] Fix 1: Replaced BLAKE2b KDF with Argon2id (crypto_pwhash)")
    else:
        print("[-] Fix 1: KDF pattern not found")

    # ------------------------------------------------------------------
    # Fix 2: Replace deterministic nonce with random generation
    # ------------------------------------------------------------------
    old_nonce_body = (
        "    crypto_generichash(nonce, crypto_secretbox_NONCEBYTES,\n"
        "                       key, crypto_secretbox_KEYBYTES, NULL, 0);\n"
        "}"
    )
    new_nonce_body = (
        "    (void)key;\n"
        "    randombytes_buf(nonce, crypto_secretbox_NONCEBYTES);\n"
        "}"
    )
    if old_nonce_body in source:
        source = source.replace(old_nonce_body, new_nonce_body)
        fixes += 1
        print("[+] Fix 2: Replaced deterministic nonce with randombytes_buf")
    else:
        print("[-] Fix 2: Nonce generation pattern not found")

    # ------------------------------------------------------------------
    # Fix 3: Enforce MAC verification (return error, don't just warn)
    # ------------------------------------------------------------------
    old_mac = (
        '    if (crypto_secretbox_open_easy(*out, ct, ct_len, nonce, key) != 0) {\n'
        '        fprintf(stderr, "Warning: MAC verification failed\\n");\n'
        '    }\n'
        '    return 0;\n'
        '}'
    )
    new_mac = (
        '    if (crypto_secretbox_open_easy(*out, ct, ct_len, nonce, key) != 0) {\n'
        '        free(*out);\n'
        '        *out = NULL;\n'
        '        *out_len = 0;\n'
        '        fprintf(stderr, "Error: MAC verification failed\\n");\n'
        '        return -1;\n'
        '    }\n'
        '    return 0;\n'
        '}'
    )
    if old_mac in source:
        source = source.replace(old_mac, new_mac)
        fixes += 1
        print("[+] Fix 3: MAC verification now returns error on failure")
    else:
        print("[-] Fix 3: MAC check pattern not found")

    # ------------------------------------------------------------------
    # Fix 4: Replace unauthenticated stream cipher with secretstream
    # ------------------------------------------------------------------
    old_encrypt_large = (
        '/* Encrypt large files using XSalsa20 stream cipher.\n'
        ' * This avoids the memory overhead of an authentication tag per chunk\n'
        ' * and provides better throughput on large payloads. */\n'
        'static int encrypt_large(const unsigned char *pt, size_t pt_len,\n'
        '                         const unsigned char *key,\n'
        '                         unsigned char **out, size_t *out_len) {\n'
        '    unsigned char nonce[crypto_stream_NONCEBYTES];\n'
        '    generate_nonce(key, nonce);\n'
        '\n'
        '    *out_len = crypto_stream_NONCEBYTES + pt_len;\n'
        '    *out = malloc(*out_len);\n'
        '    if (!*out) return -1;\n'
        '\n'
        '    memcpy(*out, nonce, crypto_stream_NONCEBYTES);\n'
        '    crypto_stream_xor(*out + crypto_stream_NONCEBYTES,\n'
        '                      pt, pt_len, nonce, key);\n'
        '    return 0;\n'
        '}'
    )
    new_encrypt_large = (
        '/* Encrypt large files using authenticated secretstream */\n'
        'static int encrypt_large(const unsigned char *pt, size_t pt_len,\n'
        '                         const unsigned char *key,\n'
        '                         unsigned char **out, size_t *out_len) {\n'
        '    crypto_secretstream_xchacha20poly1305_state state;\n'
        '    unsigned char header[crypto_secretstream_xchacha20poly1305_HEADERBYTES];\n'
        '    size_t num_chunks = (pt_len + CHUNK_SIZE - 1) / CHUNK_SIZE;\n'
        '    size_t max_out = crypto_secretstream_xchacha20poly1305_HEADERBYTES +\n'
        '                     pt_len + num_chunks * crypto_secretstream_xchacha20poly1305_ABYTES;\n'
        '\n'
        '    *out = malloc(max_out);\n'
        '    if (!*out) return -1;\n'
        '\n'
        '    crypto_secretstream_xchacha20poly1305_init_push(&state, header, key);\n'
        '    memcpy(*out, header, crypto_secretstream_xchacha20poly1305_HEADERBYTES);\n'
        '\n'
        '    size_t out_pos = crypto_secretstream_xchacha20poly1305_HEADERBYTES;\n'
        '    size_t in_pos = 0;\n'
        '\n'
        '    while (in_pos < pt_len) {\n'
        '        size_t chunk_len = CHUNK_SIZE;\n'
        '        if (in_pos + chunk_len > pt_len)\n'
        '            chunk_len = pt_len - in_pos;\n'
        '\n'
        '        unsigned char tag = (in_pos + chunk_len >= pt_len) ?\n'
        '            crypto_secretstream_xchacha20poly1305_TAG_FINAL :\n'
        '            crypto_secretstream_xchacha20poly1305_TAG_MESSAGE;\n'
        '\n'
        '        unsigned long long clen;\n'
        '        crypto_secretstream_xchacha20poly1305_push(&state,\n'
        '            *out + out_pos, &clen, pt + in_pos, chunk_len, NULL, 0, tag);\n'
        '        out_pos += (size_t)clen;\n'
        '        in_pos += chunk_len;\n'
        '    }\n'
        '\n'
        '    *out_len = out_pos;\n'
        '    return 0;\n'
        '}'
    )
    if old_encrypt_large in source:
        source = source.replace(old_encrypt_large, new_encrypt_large)
        fixes += 1
        print("[+] Fix 4a: Replaced stream cipher encrypt_large with secretstream")
    else:
        print("[-] Fix 4a: encrypt_large pattern not found")

    old_decrypt_large = (
        '/* Decrypt large files using XSalsa20 stream cipher */\n'
        'static int decrypt_large(const unsigned char *data, size_t data_len,\n'
        '                         const unsigned char *key,\n'
        '                         unsigned char **out, size_t *out_len) {\n'
        '    if (data_len < crypto_stream_NONCEBYTES) {\n'
        '        fprintf(stderr, "Error: data too short\\n");\n'
        '        return -1;\n'
        '    }\n'
        '\n'
        '    const unsigned char *nonce = data;\n'
        '    const unsigned char *ct = data + crypto_stream_NONCEBYTES;\n'
        '    size_t ct_len = data_len - crypto_stream_NONCEBYTES;\n'
        '\n'
        '    *out_len = ct_len;\n'
        '    *out = malloc(*out_len);\n'
        '    if (!*out) return -1;\n'
        '\n'
        '    crypto_stream_xor(*out, ct, ct_len, nonce, key);\n'
        '    return 0;\n'
        '}'
    )
    new_decrypt_large = (
        '/* Decrypt large files using authenticated secretstream */\n'
        'static int decrypt_large(const unsigned char *data, size_t data_len,\n'
        '                         const unsigned char *key,\n'
        '                         unsigned char **out, size_t *out_len) {\n'
        '    if (data_len < crypto_secretstream_xchacha20poly1305_HEADERBYTES) {\n'
        '        fprintf(stderr, "Error: data too short\\n");\n'
        '        return -1;\n'
        '    }\n'
        '\n'
        '    crypto_secretstream_xchacha20poly1305_state state;\n'
        '    if (crypto_secretstream_xchacha20poly1305_init_pull(&state, data, key) != 0) {\n'
        '        fprintf(stderr, "Error: invalid stream header\\n");\n'
        '        return -1;\n'
        '    }\n'
        '\n'
        '    *out = malloc(data_len);\n'
        '    if (!*out) return -1;\n'
        '\n'
        '    size_t in_pos = crypto_secretstream_xchacha20poly1305_HEADERBYTES;\n'
        '    size_t out_pos = 0;\n'
        '\n'
        '    while (in_pos < data_len) {\n'
        '        size_t max_ct = CHUNK_SIZE + crypto_secretstream_xchacha20poly1305_ABYTES;\n'
        '        size_t avail = data_len - in_pos;\n'
        '        size_t chunk_ct_len = (avail < max_ct) ? avail : max_ct;\n'
        '\n'
        '        unsigned char tag;\n'
        '        unsigned long long mlen;\n'
        '\n'
        '        if (crypto_secretstream_xchacha20poly1305_pull(&state,\n'
        '                *out + out_pos, &mlen, &tag,\n'
        '                data + in_pos, chunk_ct_len, NULL, 0) != 0) {\n'
        '            free(*out);\n'
        '            *out = NULL;\n'
        '            fprintf(stderr, "Error: stream authentication failed\\n");\n'
        '            return -1;\n'
        '        }\n'
        '\n'
        '        out_pos += (size_t)mlen;\n'
        '        in_pos += chunk_ct_len;\n'
        '\n'
        '        if (tag == crypto_secretstream_xchacha20poly1305_TAG_FINAL)\n'
        '            break;\n'
        '    }\n'
        '\n'
        '    *out_len = out_pos;\n'
        '    return 0;\n'
        '}'
    )
    if old_decrypt_large in source:
        source = source.replace(old_decrypt_large, new_decrypt_large)
        print("[+] Fix 4b: Replaced stream cipher decrypt_large with secretstream")
    else:
        print("[-] Fix 4b: decrypt_large pattern not found")

    # ------------------------------------------------------------------
    # Bonus: handle pwhash failure in cmd_encrypt
    # ------------------------------------------------------------------
    old_enc_call = (
        "    if (password) {\n"
        "        derive_key_from_password(password, salt, key);\n"
        "    } else {\n"
        "        if (load_key_from_file(keyfile, key) != 0) {\n"
        '            fprintf(stderr, "Error: failed to load key\\n");\n'
        "            return 1;\n"
        "        }\n"
        "    }"
    )
    new_enc_call = (
        "    if (password) {\n"
        "        if (derive_key_from_password(password, salt, key) != 0) {\n"
        '            fprintf(stderr, "Error: key derivation failed\\n");\n'
        "            return 1;\n"
        "        }\n"
        "    } else {\n"
        "        if (load_key_from_file(keyfile, key) != 0) {\n"
        '            fprintf(stderr, "Error: failed to load key\\n");\n'
        "            return 1;\n"
        "        }\n"
        "    }"
    )
    # This pattern appears twice (cmd_encrypt and cmd_decrypt); handle both
    if old_enc_call in source:
        # First occurrence is in cmd_encrypt (no free(payload) nearby)
        source = source.replace(old_enc_call, new_enc_call, 1)
        print("[+] Bonus: Added pwhash error handling in cmd_encrypt")

    # Handle cmd_decrypt call (has free(payload) in else branch)
    old_dec_call = (
        "    if (password) {\n"
        "        derive_key_from_password(password, salt, key);\n"
        "    } else {\n"
        "        if (load_key_from_file(keyfile, key) != 0) {\n"
        "            free(payload);\n"
        '            fprintf(stderr, "Error: failed to load key\\n");\n'
        "            return 1;\n"
        "        }\n"
        "    }"
    )
    new_dec_call = (
        "    if (password) {\n"
        "        if (derive_key_from_password(password, salt, key) != 0) {\n"
        "            free(payload);\n"
        '            fprintf(stderr, "Error: key derivation failed\\n");\n'
        "            return 1;\n"
        "        }\n"
        "    } else {\n"
        "        if (load_key_from_file(keyfile, key) != 0) {\n"
        "            free(payload);\n"
        '            fprintf(stderr, "Error: failed to load key\\n");\n'
        "            return 1;\n"
        "        }\n"
        "    }"
    )
    if old_dec_call in source:
        source = source.replace(old_dec_call, new_dec_call)
        print("[+] Bonus: Added pwhash error handling in cmd_decrypt")

    # Update comments to reflect fixes
    source = source.replace(
        "/* Derive an encryption key from a password and salt using BLAKE2b.\n"
        " * The salt is mixed in to prevent rainbow-table attacks. */",
        "/* Derive an encryption key from a password and salt using Argon2id.\n"
        " * Memory-hard KDF prevents brute-force attacks. */"
    )
    source = source.replace(
        "/* Generate a nonce deterministically from the key.\n"
        " * This ensures reproducible behaviour for the same key. */",
        "/* Generate a random nonce for each encryption operation. */"
    )

    return source, fixes


def main():
    source_path = "/app/cryptvault.c"

    if not os.path.exists(source_path):
        print(f"Error: {source_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(source_path, "r") as f:
        source = f.read()

    print(f"Read {len(source)} bytes from {source_path}")
    print("Applying cryptographic fixes...\n")

    fixed_source, num_fixes = apply_fixes(source)

    with open(source_path, "w") as f:
        f.write(fixed_source)

    print(f"\nApplied {num_fixes} security fixes to {source_path}")

    if num_fixes < 4:
        print("WARNING: Not all fixes were applied!", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
