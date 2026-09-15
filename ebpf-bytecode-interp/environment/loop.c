__attribute__((section("prog"), used))
long bpf_prog(void *ctx) {
    long sum = 0;
    volatile long i;
    for (i = 1; i <= 10; i++) {
        sum += i;
    }
    return sum;
}
