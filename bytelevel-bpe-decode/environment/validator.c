/*
 * validator.c - Validate decoded tokenizer output against expected SHA-256 hashes.
 *
 * Reads /app/decoded_output.json and /app/expected_hashes.txt, computes SHA-256
 * of each decoded sequence value, and compares against the expected hash.
 *
 * Build: make -C /app
 * Usage: /app/validator
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/evp.h>

#define JSON_PATH "/app/decoded_output.json"
#define HASH_PATH "/app/expected_hashes.txt"

static char *read_file(const char *path, long *out_size) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    rewind(f);
    char *buf = (char *)malloc(size + 1);
    if (!buf) { fclose(f); return NULL; }
    if ((long)fread(buf, 1, size, f) != size) {
        free(buf);
        fclose(f);
        return NULL;
    }
    buf[size] = '\0';
    if (out_size) *out_size = size;
    fclose(f);
    return buf;
}

/*
 * Extract a JSON string value for a given key from the decoded_output.json content.
 * Handles JSON escape sequences: \n \t \\ \" \/ \uXXXX
 * Returns a malloc'd buffer with the unescaped bytes, sets *out_len.
 */
static char *extract_json_value(const char *json, const char *key, size_t *out_len) {
    char pattern[256];
    snprintf(pattern, sizeof(pattern), "\"%s\": \"", key);
    const char *pos = strstr(json, pattern);
    if (!pos) return NULL;
    pos += strlen(pattern);

    size_t cap = 1024;
    char *result = (char *)malloc(cap);
    size_t len = 0;

    while (*pos) {
        if (*pos == '"') break;
        if (*pos == '\\') {
            pos++;
            switch (*pos) {
                case 'n':  result[len++] = '\n'; break;
                case 't':  result[len++] = '\t'; break;
                case 'r':  result[len++] = '\r'; break;
                case '\\': result[len++] = '\\'; break;
                case '"':  result[len++] = '"';  break;
                case '/':  result[len++] = '/';  break;
                case 'u': {
                    unsigned int cp = 0;
                    if (sscanf(pos + 1, "%4x", &cp) == 1) {
                        /* Encode codepoint as UTF-8 */
                        if (cp < 0x80) {
                            result[len++] = (char)cp;
                        } else if (cp < 0x800) {
                            result[len++] = (char)(0xC0 | (cp >> 6));
                            result[len++] = (char)(0x80 | (cp & 0x3F));
                        } else {
                            result[len++] = (char)(0xE0 | (cp >> 12));
                            result[len++] = (char)(0x80 | ((cp >> 6) & 0x3F));
                            result[len++] = (char)(0x80 | (cp & 0x3F));
                        }
                        pos += 4;
                    }
                    break;
                }
                default:
                    result[len++] = *pos;
                    break;
            }
        } else {
            result[len++] = *pos;
        }
        pos++;
        if (len + 8 >= cap) {
            cap *= 2;
            result = (char *)realloc(result, cap);
        }
    }
    result[len] = '\0';
    *out_len = len;
    return result;
}

static void sha256_hex(const void *data, size_t len, char *out) {
    unsigned char md[EVP_MAX_MD_SIZE];
    unsigned int md_len = 0;
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    EVP_DigestInit_ex(ctx, EVP_sha256(), NULL);
    EVP_DigestUpdate(ctx, data, len);
    EVP_DigestFinal_ex(ctx, md, &md_len);
    EVP_MD_CTX_free(ctx);
    for (unsigned int i = 0; i < md_len; i++)
        sprintf(out + 2 * i, "%02x", md[i]);
    out[2 * md_len] = '\0';
}

int main(void) {
    char *json = read_file(JSON_PATH, NULL);
    if (!json) {
        fprintf(stderr, "Error: cannot read %s\n", JSON_PATH);
        return 1;
    }

    long hash_size = 0;
    char *hashes = read_file(HASH_PATH, &hash_size);
    if (!hashes) {
        fprintf(stderr, "Error: cannot read %s\n", HASH_PATH);
        free(json);
        return 1;
    }

    int total = 0, passed = 0, failed = 0;
    char *saveptr = NULL;
    char *line = strtok_r(hashes, "\n", &saveptr);

    while (line) {
        if (strlen(line) == 0) {
            line = strtok_r(NULL, "\n", &saveptr);
            continue;
        }

        char *tab = strchr(line, '\t');
        if (!tab) {
            line = strtok_r(NULL, "\n", &saveptr);
            continue;
        }
        *tab = '\0';
        const char *key = line;
        const char *expected_hash = tab + 1;
        total++;

        size_t val_len = 0;
        char *value = extract_json_value(json, key, &val_len);
        if (!value) {
            printf("FAIL: %-25s [key not found in output]\n", key);
            failed++;
        } else {
            char actual_hash[65];
            sha256_hex(value, val_len, actual_hash);
            if (strcmp(actual_hash, expected_hash) == 0) {
                printf("PASS: %s\n", key);
                passed++;
            } else {
                printf("FAIL: %-25s [hash mismatch]\n", key);
                failed++;
            }
            free(value);
        }
        line = strtok_r(NULL, "\n", &saveptr);
    }

    printf("\n%d/%d sequences passed", passed, total);
    if (failed > 0) printf(", %d failed", failed);
    printf("\n");

    free(json);
    free(hashes);
    return (passed == total) ? 0 : 1;
}
