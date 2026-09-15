__attribute__((section("prog"), used))
long bpf_prog(void *ctx) {
    volatile long x = 75;
    if (x > 100)
        return x * 2;
    if (x > 50)
        return x + 50;
    return x;
}
