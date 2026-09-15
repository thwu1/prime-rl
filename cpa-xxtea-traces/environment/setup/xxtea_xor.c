/*
 * XXTEA Block Cipher with XOR Pre-processing
 * Firmware: XXTEA-XOR Encryption Module v2.1
 *
 * Encryption pipeline:
 *   plaintext -> xor_preprocess(key) -> xxtea_encrypt(key) -> ciphertext
 *
 * Decryption pipeline:
 *   ciphertext -> xxtea_decrypt(key) -> reverse_xor_preprocess(key) -> plaintext
 */

#include <stdint.h>
#include <string.h>

#define DELTA 0x9e3779b9
#define MX(z,y,sum,key,p,e) \
    ((((z>>5)^(y<<2)) + ((y>>3)^(z<<4))) ^ ((sum^y) + (key[((p)&3)^(e)]^z)))

/*
 * XOR pre-processing stage.
 * Applies 16 sequential byte-level XOR operations between
 * the data buffer and the 16-byte key.
 * Buffer indexing wraps modulo data_len.
 */
void xor_preprocess(uint8_t *data, int data_len, const uint8_t key[16]) {
    for (int i = 0; i < 16; i++) {
        data[i % data_len] ^= key[i];
    }
}

/*
 * Reverse XOR pre-processing (for decryption).
 * Must be applied in reverse order to correctly undo the preprocessing.
 */
void reverse_xor_preprocess(uint8_t *data, int data_len,
                            const uint8_t key[16]) {
    for (int i = 15; i >= 0; i--) {
        data[i % data_len] ^= key[i];
    }
}

/* Standard XXTEA encryption. */
void xxtea_encrypt(uint32_t *v, int n, const uint32_t key[4]) {
    uint32_t z, y, sum = 0;
    int rounds = 6 + 52 / n;
    z = v[n - 1];
    while (rounds-- > 0) {
        sum += DELTA;
        uint32_t e = (sum >> 2) & 3;
        for (int p = 0; p < n - 1; p++) {
            y = v[p + 1];
            v[p] += MX(z, y, sum, key, p, e);
            z = v[p];
        }
        y = v[0];
        v[n - 1] += MX(z, y, sum, key, n - 1, e);
        z = v[n - 1];
    }
}

/* Standard XXTEA decryption. */
void xxtea_decrypt(uint32_t *v, int n, const uint32_t key[4]) {
    uint32_t z, y, sum;
    int rounds = 6 + 52 / n;
    sum = rounds * DELTA;
    y = v[0];
    while (rounds-- > 0) {
        uint32_t e = (sum >> 2) & 3;
        for (int p = n - 1; p > 0; p--) {
            z = v[p - 1];
            v[p] -= MX(z, y, sum, key, p, e);
            y = v[p];
        }
        z = v[n - 1];
        v[0] -= MX(z, y, sum, key, 0, e);
        y = v[0];
        sum -= DELTA;
    }
}

/* Full encryption: preprocess then XXTEA encrypt.
 * data must be 8 bytes; key must be 16 bytes. */
void encrypt_block(uint8_t data[8], const uint8_t key[16]) {
    uint32_t key_words[4];
    for (int i = 0; i < 4; i++) {
        key_words[i] = (uint32_t)key[4*i]
                     | ((uint32_t)key[4*i+1] << 8)
                     | ((uint32_t)key[4*i+2] << 16)
                     | ((uint32_t)key[4*i+3] << 24);
    }
    xor_preprocess(data, 8, key);
    xxtea_encrypt((uint32_t *)data, 2, key_words);
}

/* Full decryption: XXTEA decrypt then reverse preprocess.
 * data must be 8 bytes; key must be 16 bytes. */
void decrypt_block(uint8_t data[8], const uint8_t key[16]) {
    uint32_t key_words[4];
    for (int i = 0; i < 4; i++) {
        key_words[i] = (uint32_t)key[4*i]
                     | ((uint32_t)key[4*i+1] << 8)
                     | ((uint32_t)key[4*i+2] << 16)
                     | ((uint32_t)key[4*i+3] << 24);
    }
    xxtea_decrypt((uint32_t *)data, 2, key_words);
    reverse_xor_preprocess(data, 8, key);
}
