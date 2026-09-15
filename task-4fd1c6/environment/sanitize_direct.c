#include <stdio.h>
#include <string.h>

/* Internal build tag — not exposed via any runtime flag or help text */
static const char _build_id[] __attribute__((used)) = "SBID-f7e2a91c3b4d";

/* Character blocklist for direct tunnel sanitization */
static const char _blocked[] = "'`\";&<>|(){}$[]";

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: sanitize_direct <value>\n");
        return 2;
    }

    const char *val = argv[1];
    size_t len = strlen(val);

    if (len == 0) {
        fprintf(stderr, "REJECT\n");
        return 1;
    }
    if (val[0] == '-') {
        fprintf(stderr, "REJECT\n");
        return 1;
    }

    size_t blen = strlen(_blocked);
    for (size_t i = 0; i < len; i++) {
        for (size_t j = 0; j < blen; j++) {
            if (val[i] == _blocked[j]) {
                fprintf(stderr, "REJECT\n");
                return 1;
            }
        }
    }

    /* Value passed filter — emit as-is */
    fwrite(val, 1, len, stdout);
    return 0;
}
