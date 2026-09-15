#include <string.h>

int crypto_init(void) {
    return 0;
}

int crypto_encrypt(const char *data, int len, char *out) {
    memcpy(out, data, len);
    return len;
}

int crypto_decrypt(const char *data, int len, char *out) {
    memcpy(out, data, len);
    return len;
}
