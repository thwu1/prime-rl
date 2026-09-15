#include <stdio.h>
#include <string.h>
#include "common.h"

uint32_t fnv1a_hash(const uint8_t *data, size_t len) {
    uint32_t hash = 0x811c9dc5u;
    for (size_t i = 0; i < len; i++) {
        hash ^= data[i];
        hash *= 0x01000193u;
    }
    return hash;
}

void insertion_sort(int32_t *arr, int n) {
    for (int i = 1; i < n; i++) {
        int32_t key = arr[i];
        int j = i - 1;
        while (j >= 0 && arr[j] > key) {
            arr[j + 1] = arr[j];
            j--;
        }
        arr[j + 1] = key;
    }
}

int binary_search(const int32_t *arr, int n, int32_t target) {
    int lo = 0, hi = n - 1;
    while (lo <= hi) {
        int mid = lo + (hi - lo) / 2;
        if (arr[mid] == target) return mid;
        else if (arr[mid] < target) lo = mid + 1;
        else hi = mid - 1;
    }
    return -1;
}

int main(void) {
    const char *test_str = "Hello RISC-V";

    /* CRC32 */
    uint32_t crc = crc32_compute((const uint8_t *)test_str, strlen(test_str));
    printf("CRC32: %08x\n", crc);

    /* Simple hash */
    uint8_t hash[16];
    simple_hash((const uint8_t *)test_str, strlen(test_str), hash);
    printf("HASH:");
    for (int i = 0; i < 16; i++)
        printf("%02x", hash[i]);
    printf("\n");

    /* XTEA encrypt/decrypt round-trip */
    uint32_t key[4] = {0x01234567, 0x89ABCDEF, 0xFEDCBA98, 0x76543210};
    uint32_t block[2] = {0xDEADBEEF, 0xCAFEBABE};
    uint32_t orig0 = block[0], orig1 = block[1];
    xtea_encrypt(block, key);
    printf("XTEA_ENC: %08x %08x\n", block[0], block[1]);
    xtea_decrypt(block, key);
    printf("XTEA_DEC: %s\n",
           (block[0] == orig0 && block[1] == orig1) ? "OK" : "FAIL");

    /* Taylor series */
    printf("SIN: %.6f\n", taylor_sin(1.0));
    printf("COS: %.6f\n", taylor_cos(1.0));
    printf("SQRT: %.6f\n", fast_sqrt(2.0));

    /* 4x4 matrix multiply */
    double A[16], B[16], C[16];
    for (int i = 0; i < 16; i++) {
        A[i] = (i + 1) * 0.5;
        B[i] = (16 - i) * 0.25;
    }
    mat4_multiply(A, B, C);
    printf("MAT[0]: %.2f MAT[5]: %.2f MAT[15]: %.2f\n", C[0], C[5], C[15]);

    /* Polynomial evaluation */
    double coeffs[] = {1.0, -2.0, 3.0, -4.0, 5.0};
    printf("POLY: %.2f\n", poly_eval(coeffs, 4, 0.5));

    /* Scale value (UB bug test) */
    printf("SCALE1: %d\n", scale_value(100, 42));
    printf("SCALE2: %d\n", scale_value(100000, 30000));

    /* RLE */
    const uint8_t data[] = "AAABBBCCCAAABBBCCC";
    uint8_t comp[64], decomp[64];
    int clen = rle_compress(data, 18, comp, 64);
    int dlen = rle_decompress(comp, clen, decomp, 64);
    printf("RLE: %d %d %d\n", 18, clen, dlen);

    /* Delta encoding */
    int32_t samples[] = {10, 13, 15, 14, 18, 22, 21, 25};
    int32_t encoded[8], decoded[8];
    delta_encode(samples, 8, encoded);
    delta_decode(encoded, 8, decoded);
    printf("DELTA: %s\n", (decoded[7] == samples[7]) ? "OK" : "FAIL");

    /* Bitpack compression */
    uint32_t values[] = {3, 7, 2, 5, 1, 6, 4, 0};
    uint8_t packed[16];
    int plen = bitpack_compress(values, 8, packed, 3);
    printf("BITPACK: %d bytes\n", plen);

    /* FNV-1a hash */
    uint32_t fnv = fnv1a_hash((const uint8_t *)test_str, strlen(test_str));
    printf("FNV1A: %08x\n", fnv);

    /* Sort and search */
    int32_t arr[] = {42, 17, 88, 3, 55, 71, 29, 64};
    insertion_sort(arr, 8);
    int idx = binary_search(arr, 8, 55);
    printf("SORT_SEARCH: %d at %d\n", arr[0], idx);

    return 0;
}
