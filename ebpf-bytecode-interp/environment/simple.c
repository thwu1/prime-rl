__attribute__((section("prog"), used))
long bpf_prog(void *ctx) {
    return 42;
}
