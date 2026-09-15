/*
 * Test: struct assignment copies all bytes correctly.
 * A struct { char a, b, c; } is 3 bytes. Assigning one to another
 * must copy all 3 bytes including the last one.
 *
 * Returns 0 on success, non-zero on failure.
 */
typedef struct { char a, b, c; } S3;

int main() {
    S3 src = {10, 20, 30};
    S3 dst = {0, 0, 0};
    dst = src;

    if (dst.a != 10) return 1;
    if (dst.b != 20) return 2;
    if (dst.c != 30) return 3;

    /* Also test with a 5-byte struct */
    typedef struct { char v[5]; } S5;
    S5 s5a = {1, 2, 3, 4, 5};
    S5 s5b = {0, 0, 0, 0, 0};
    s5b = s5a;
    if (s5b.v[4] != 5) return 4;

    /* 7-byte struct */
    typedef struct { char w[7]; } S7;
    S7 s7a = {11, 22, 33, 44, 55, 66, 77};
    S7 s7b = {0, 0, 0, 0, 0, 0, 0};
    s7b = s7a;
    if (s7b.w[6] != 77) return 5;

    return 0;
}
