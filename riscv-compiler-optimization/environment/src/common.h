#ifndef COMMON_H
#define COMMON_H

#include <stdint.h>
#include <stddef.h>

/* Crypto */
uint32_t crc32_compute(const uint8_t *data, size_t len);
void simple_hash(const uint8_t *data, size_t len, uint8_t *out);
void xtea_encrypt(uint32_t v[2], const uint32_t key[4]);
void xtea_decrypt(uint32_t v[2], const uint32_t key[4]);

/* Math utilities */
double taylor_sin(double x);
double taylor_cos(double x);
double fast_sqrt(double x);
void mat4_multiply(const double A[16], const double B[16], double C[16]);
double poly_eval(const double *coeffs, int degree, double x);
double unused_bessel_j0(double x);
double unused_gamma_approx(double x);
int scale_value(int x, int factor);

/* Compression */
int rle_compress(const uint8_t *in, int inlen, uint8_t *out, int outlen);
int rle_decompress(const uint8_t *in, int inlen, uint8_t *out, int outlen);
int delta_encode(const int32_t *in, int count, int32_t *out);
int delta_decode(const int32_t *in, int count, int32_t *out);
int bitpack_compress(const uint32_t *in, int count, uint8_t *out, int maxbits);

/* Main utilities */
uint32_t fnv1a_hash(const uint8_t *data, size_t len);
void insertion_sort(int32_t *arr, int n);
int binary_search(const int32_t *arr, int n, int32_t target);

#endif
