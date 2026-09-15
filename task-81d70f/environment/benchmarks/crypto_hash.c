/* SHA-256-like compression function with bitwise helpers */

static unsigned int rotr(unsigned int x, int n) {
    return (x >> n) | (x << (32 - n));
}

static unsigned int ch(unsigned int x, unsigned int y, unsigned int z) {
    return (x & y) ^ (~x & z);
}

static unsigned int maj(unsigned int x, unsigned int y, unsigned int z) {
    return (x & y) ^ (x & z) ^ (y & z);
}

static unsigned int sigma0(unsigned int x) {
    return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22);
}

static unsigned int sigma1(unsigned int x) {
    return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25);
}

static unsigned int gamma0(unsigned int x) {
    return rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3);
}

static unsigned int gamma1(unsigned int x) {
    return rotr(x, 17) ^ rotr(x, 19) ^ (x >> 10);
}

void hash_block(const unsigned int *block, unsigned int *state) {
    unsigned int w[64];
    int i;

    for (i = 0; i < 16; i++)
        w[i] = block[i];
    for (i = 16; i < 64; i++)
        w[i] = gamma1(w[i-2]) + w[i-7] + gamma0(w[i-15]) + w[i-16];

    unsigned int a = state[0], b = state[1], c = state[2], d = state[3];
    unsigned int e = state[4], f = state[5], g = state[6], h = state[7];

    for (i = 0; i < 64; i++) {
        unsigned int t1 = h + sigma1(e) + ch(e, f, g) + w[i];
        unsigned int t2 = sigma0(a) + maj(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
    state[4] += e; state[5] += f; state[6] += g; state[7] += h;
}

void hash_multi_block(const unsigned int *data, int num_blocks,
                      unsigned int *state) {
    for (int b = 0; b < num_blocks; b++)
        hash_block(data + b * 16, state);
}
