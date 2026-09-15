__attribute__((section("prog"), used))
long bpf_prog(void *ctx) {
    volatile long x = 0xDEAD;
    long r = x;
    r = ((r & 0xFF) << 8) | ((r >> 8) & 0xFF);
    r ^= 0x1234;
    r = (r << 4) | (r >> 60);
    return r & 0xFFFF;
}
