/* Bit manipulation and encoding operations */

static unsigned int popcount32(unsigned int x) {
    x = x - ((x >> 1) & 0x55555555u);
    x = (x & 0x33333333u) + ((x >> 2) & 0x33333333u);
    return (((x + (x >> 4)) & 0x0F0F0F0Fu) * 0x01010101u) >> 24;
}

static unsigned int reverse_bits32(unsigned int x) {
    x = ((x & 0x55555555u) << 1) | ((x >> 1) & 0x55555555u);
    x = ((x & 0x33333333u) << 2) | ((x >> 2) & 0x33333333u);
    x = ((x & 0x0F0F0F0Fu) << 4) | ((x >> 4) & 0x0F0F0F0Fu);
    x = ((x & 0x00FF00FFu) << 8) | ((x >> 8) & 0x00FF00FFu);
    return (x << 16) | (x >> 16);
}

unsigned int morton_encode(unsigned int x, unsigned int y) {
    x = (x | (x << 16)) & 0x0000FFFFu;
    x = (x | (x << 8))  & 0x00FF00FFu;
    x = (x | (x << 4))  & 0x0F0F0F0Fu;
    x = (x | (x << 2))  & 0x33333333u;
    x = (x | (x << 1))  & 0x55555555u;
    y = (y | (y << 16)) & 0x0000FFFFu;
    y = (y | (y << 8))  & 0x00FF00FFu;
    y = (y | (y << 4))  & 0x0F0F0F0Fu;
    y = (y | (y << 2))  & 0x33333333u;
    y = (y | (y << 1))  & 0x55555555u;
    return x | (y << 1);
}

void morton_decode(unsigned int z, unsigned int *x, unsigned int *y) {
    unsigned int xm = z & 0x55555555u;
    xm = (xm | (xm >> 1))  & 0x33333333u;
    xm = (xm | (xm >> 2))  & 0x0F0F0F0Fu;
    xm = (xm | (xm >> 4))  & 0x00FF00FFu;
    xm = (xm | (xm >> 8))  & 0x0000FFFFu;
    unsigned int ym = (z >> 1) & 0x55555555u;
    ym = (ym | (ym >> 1))  & 0x33333333u;
    ym = (ym | (ym >> 2))  & 0x0F0F0F0Fu;
    ym = (ym | (ym >> 4))  & 0x00FF00FFu;
    ym = (ym | (ym >> 8))  & 0x0000FFFFu;
    *x = xm;
    *y = ym;
}

int hamming_distance(const unsigned int *a, const unsigned int *b, int n) {
    int total = 0;
    for (int i = 0; i < n; i++)
        total += popcount32(a[i] ^ b[i]);
    return total;
}

void gray_code_sequence(unsigned int *out, int n) {
    for (int i = 0; i < n; i++)
        out[i] = (unsigned int)i ^ ((unsigned int)i >> 1);
}

void bit_reverse_permute(unsigned int *arr, int log2n) {
    int n = 1 << log2n;
    for (int i = 0; i < n; i++) {
        unsigned int j = reverse_bits32((unsigned int)i) >> (32 - log2n);
        if ((int)j > i) {
            unsigned int tmp = arr[i];
            arr[i] = arr[j];
            arr[j] = tmp;
        }
    }
}

void enumerate_submasks(unsigned int mask, unsigned int *out, int *count) {
    int c = 0;
    for (unsigned int sub = mask; sub > 0; sub = (sub - 1) & mask)
        out[c++] = sub;
    out[c++] = 0;
    *count = c;
}
