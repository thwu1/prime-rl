__attribute__((section("prog"), used))
long bpf_prog(void *ctx) {
    volatile long a = 100;
    volatile long b = 200;
    volatile long c = a * b;
    return c + 42;
}
