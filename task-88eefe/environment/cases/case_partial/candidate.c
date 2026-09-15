int managed_a(int size, int flags) {
    if (size <= 0)
        return -1;
    return size;
}

int managed_b(int size, int flags) {
    if (size <= 0)
        return -1;
    return size;
}

int alloc_c(int size) {
    return size;
}

int setup(void) {
    int a;
    int b;
    int c;
    a = managed_a(10, 0);
    if (a < 0)
        return a;
    b = managed_b(20, 0);
    if (b < 0)
        return b;
    c = alloc_c(30);
    return a + b + c;
}

void cleanup(void) {
}
